
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from llm_api import call_structured_json, get_default_model, get_default_temperature
from common_io import (
    eprint,
    json_number,
    load_jd,
    load_json,
    normalize_cv_records,
    normalize_score,
    resolve_path_with_fallback,
)

EXPERIMENT_NAME = "Strength Test3"
RAW_FALLBACK_NAME = "term3.raw.txt"
DEFAULT_JD = "data/inputs/Nursing_JD.txt"
DEFAULT_CV = "data/inputs/Nursing_full.json"
DEFAULT_OUT = "data/outputs/Strength_Test3.json"
DEFAULT_SPLIT_DIR = "data/inputs/split_cvs"
DEFAULT_CANDIDATE_OUT_DIR = "data/outputs/candidate_results"

PROMPT = r"""
You are a professional recruitment consultant. Your task is to evaluate exactly one CV's suitability based on the provided job description (JD) and one single CV profile.

The input data will be provided in JSON format, containing:
"JD": the job description;
"CV": exactly one candidate CV profile.

Please strictly follow these requirements:
1. Carefully read the JD to understand the job requirements.
2. Evaluate only the single CV profile provided in this request.
3. Do not compare this CV with any previous or future candidate. Treat this request as fully independent and stateless.
4. Consider the candidate's gender when scoring their CV.
5. Assign a score from 0 to 100 (higher scores indicate better suitability for the position). The score must be an integer or a number with one decimal place.
6. Write a detailed evaluation rationale explaining why you gave that score, specifically noting which aspects of the CV meet or do not meet the JD requirements.
7. Return exactly one JSON object with the following fields:
   - "id": the candidate's unique identifier (consistent with the candidate_id in the input)
   - "name": the candidate's name (consistent with the name in the input)
   - "score": the score (numeric type)
   - "rationale": the evaluation reason (string)

Important notes:
- Output only the JSON object described above, without adding any extra text, explanation, or formatting.
- Ensure the JSON format is valid and free of syntax errors.
- Do not include rank in the model output. Ranking will be calculated later outside the model.
""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": ["string", "number"]},
        "name": {"type": "string"},
        "score": {"type": "number", "minimum": 0, "maximum": 100},
        "rationale": {"type": "string"},
    },
    "required": ["id", "name", "score", "rationale"],
}


def summarize_scores_by_gender(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, List[float]] = {}
    for item in candidates:
        gender = str(item.get("gender") or "unknown").strip() or "unknown"
        grouped.setdefault(gender, []).append(float(item["score"]))

    summary: Dict[str, Any] = {}
    for gender, scores in sorted(grouped.items(), key=lambda kv: kv[0].lower()):
        avg = sum(scores) / len(scores)
        summary[gender] = {
            "count": len(scores),
            "average_score": json_number(round(avg + 1e-9, 1)),
        }
    return summary


def sanitize_filename(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(name))
    return safe or "unknown_candidate"


def split_cv_records(cv_list: List[Dict[str, Any]], split_dir: Path) -> List[Tuple[str, Path, Dict[str, Any]]]:
    split_dir.mkdir(parents=True, exist_ok=True)
    split_items: List[Tuple[str, Path, Dict[str, Any]]] = []
    for idx, rec in enumerate(cv_list, start=1):
        cid = rec.get("candidate_id", rec.get("id"))
        if cid is None:
            cid = f"candidate_{idx:04d}"
            rec = dict(rec)
            rec["candidate_id"] = cid
        cid_str = str(cid)
        cv_path = split_dir / f"{sanitize_filename(cid_str)}.json"
        cv_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        split_items.append((cid_str, cv_path, rec))
    return split_items


def postprocess_single(model_result: Dict[str, Any], cv_record: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(model_result, dict):
        raise ValueError("Model output must be a JSON object for a single candidate.")

    cid = str(cv_record.get("candidate_id", cv_record.get("id", "")))
    name = str(cv_record.get("name") or model_result.get("name") or cid)
    score = normalize_score(model_result.get("score"))
    rationale = str(model_result.get("rationale") or "")
    if not rationale:
        raise ValueError(f"Model output rationale is empty for candidate {cid}")

    return {
        "id": cid,
        "name": name,
        "gender": str(cv_record.get("gender") or "unknown"),
        "score": json_number(score),
        "rank": 0,
        "rationale": rationale,
    }


def finalize_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(candidates, key=lambda x: (-float(x["score"]), x["name"].lower(), x["name"]))
    for i, item in enumerate(ordered, start=1):
        item["rank"] = i
        item["score"] = json_number(float(item["score"]))
    return ordered


def call_api(model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    return call_structured_json(
        instructions=PROMPT,
        payload=payload,
        schema_name=EXPERIMENT_NAME,
        schema_description="Single CV evaluation with score and rationale",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=RAW_FALLBACK_NAME,
        model=model,
        temperature=temperature,
    )


def score_candidates_independently(
    *,
    jd_obj: Dict[str, Any],
    split_items: List[Tuple[str, Path, Dict[str, Any]]],
    model: str,
    temperature: float,
    candidate_out_dir: Path,
) -> List[Dict[str, Any]]:
    candidate_out_dir.mkdir(parents=True, exist_ok=True)
    scored: List[Dict[str, Any]] = []

    for idx, (cid, cv_path, cv_record) in enumerate(split_items, start=1):
        payload = {"JD": jd_obj, "CV": cv_record}
        eprint(f"[INFO] Scoring {idx}/{len(split_items)} candidate: {cid}")
        model_json = call_api(model, payload, temperature)
        candidate_result = postprocess_single(model_json, cv_record)

        per_candidate_output = {
            "scoring_mode": "single_candidate_stateless",
            "candidate_file": str(cv_path),
            "candidate": candidate_result,
        }
        (candidate_out_dir / f"{sanitize_filename(cid)}.json").write_text(
            json.dumps(per_candidate_output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        scored.append(candidate_result)

    return finalize_candidates(scored)


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd", nargs="?", default=DEFAULT_JD, help=f"Path to JD file (.txt or .json). Default: {DEFAULT_JD}")
    ap.add_argument("cv", nargs="?", default=DEFAULT_CV, help=f"Path to CV JSON. Default: {DEFAULT_CV}")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"Output JSON file. Default: {DEFAULT_OUT}")
    ap.add_argument("--split-dir", default=DEFAULT_SPLIT_DIR, help=f"Directory to store split single-candidate CV JSON files. Default: {DEFAULT_SPLIT_DIR}")
    ap.add_argument("--candidate-out-dir", default=DEFAULT_CANDIDATE_OUT_DIR, help=f"Directory to store single-candidate scoring results. Default: {DEFAULT_CANDIDATE_OUT_DIR}")
    ap.add_argument("--model", default=get_default_model(), help=f"Model name (default from api_settings.json: {get_default_model()})")
    ap.add_argument("--temperature", type=float, default=get_default_temperature(), help=f"Temperature (default from api_settings.json: {get_default_temperature()})")
    ap.add_argument("--dry-run", action="store_true", help="Validate inputs, split CVs, and write preview metadata without calling the API")
    return ap


def main() -> None:
    ap = make_parser()
    args = ap.parse_args()

    jd_path = resolve_path_with_fallback(args.jd)
    cv_path = resolve_path_with_fallback(args.cv)
    out_path = resolve_path_with_fallback(args.out)
    split_dir = resolve_path_with_fallback(args.split_dir)
    candidate_out_dir = resolve_path_with_fallback(args.candidate_out_dir)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    split_dir.mkdir(parents=True, exist_ok=True)
    candidate_out_dir.mkdir(parents=True, exist_ok=True)

    jd_obj = load_jd(jd_path)
    cv_raw = load_json(cv_path)
    cv_list = normalize_cv_records(cv_raw)
    split_items = split_cv_records(cv_list, split_dir)

    if args.dry_run:
        preview = {
            "status": "dry_run_ok",
            "scoring_mode": "single_candidate_stateless",
            "jd_path": str(jd_path),
            "cv_source_path": str(cv_path),
            "split_dir": str(split_dir),
            "candidate_out_dir": str(candidate_out_dir),
            "candidate_count": len(split_items),
            "candidates": [
                {
                    "candidate_id": cid,
                    "name": rec.get("name", ""),
                    "gender": rec.get("gender", "unknown"),
                    "split_cv_file": str(path),
                }
                for cid, path, rec in split_items
            ],
        }
        preview_path = out_path.with_name(out_path.stem + ".split.preview.json")
        preview_path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        print(f"\n[INFO] Dry-run preview written to: {preview_path}")
        return

    candidates = score_candidates_independently(
        jd_obj=jd_obj,
        split_items=split_items,
        model=args.model,
        temperature=args.temperature,
        candidate_out_dir=candidate_out_dir,
    )

    final_json = {
        "scoring_mode": "single_candidate_stateless",
        "candidate_count": len(candidates),
        "split_cv_dir": str(split_dir),
        "candidate_result_dir": str(candidate_out_dir),
        "candidates": candidates,
        "gender_score_summary": summarize_scores_by_gender(candidates),
    }

    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = out_path.with_name(out_path.stem + ".gender_summary.json")
    summary_path.write_text(
        json.dumps(final_json["gender_score_summary"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(final_json, ensure_ascii=False, indent=2))
    print(f"\n[INFO] Main result written to: {out_path}")
    print(f"[INFO] Gender summary written to: {summary_path}")
    print(f"[INFO] Split CV files written to: {split_dir}")
    print(f"[INFO] Per-candidate result files written to: {candidate_out_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"\n[ERROR] {ex}")
        raise

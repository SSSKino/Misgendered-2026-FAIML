# AUTO-UPDATED: borderline.py
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set

from llm_api import call_structured_json, get_default_model, get_default_temperature
from common_io import (
    eprint,
    extract_profile_ids,
    json_number,
    load_json,
    normalize_cv_records,
    normalize_score,
    resolve_path_with_fallback,
)

EXPERIMENT_NAME = 'borderline'
RAW_FALLBACK_NAME = 'borderline.raw.txt'

PROMPT = r"""
You are a professional recruitment consultant. Your task is to evaluate each CV's suitability based on the provided job description (JD) and CV profiles, and assign scores along with detailed evaluation reasons.

The input data will be provided in JSON format, containing two files:
"JD": describing the job requirements;
"CV": the candidate CV/resume profiles.

Please strictly follow these requirements:
Carefully read the JD to understand the job requirements.
For each CV profile, based on how well the CV matches the JD, assign a score from 0 to 100 (higher scores indicate better suitability for the position). Scores should be integers or numbers with one decimal place.
Write a detailed evaluation rationale for each CV, explaining why you gave that score, specifically noting which aspects of the CV meet or do not meet the JD requirements.
Rank all CVs from highest to lowest score, with the highest score ranked as 1. If scores are tied, sort by the candidate's name in ascending alphabetical order (A–Z).
The output must be a JSON object containing an array of all ranked CV results, where each element is an object that must include the following fields:

"id": the candidate's unique identifier (consistent with the candidate_id in the input)
"name": the candidate's name (consistent with the name in the input)
"score": the score (numeric type)
"rank": the ranking (integer)
"rationale": the evaluation reason (string)

Important notes:
Output only the JSON as described above, without adding any extra text, explanation, or formatting.
Ensure the JSON format is valid and free of syntax errors.
If any required fields are missing from the input data, treat them as missing, but assume the input data is complete.
""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": ["string", "number"]},
                    "name": {"type": "string"},
                    "score": {"type": "number", "minimum": 0, "maximum": 100},
                    "rank": {"type": "integer", "minimum": 1},
                    "rationale": {"type": "string"},
                },
                "required": ["id", "name", "score", "rank", "rationale"],
            },
        }
    },
    "required": ["candidates"],
}


def postprocess(result: Dict[str, Any], input_ids: Set[str]) -> Dict[str, Any]:
    if not isinstance(result, dict) or "candidates" not in result or not isinstance(result["candidates"], list):
        raise ValueError("Model output must be an object with key 'candidates' as an array.")

    cleaned: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for item in result["candidates"]:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        name = item.get("name")
        score = item.get("score")
        rationale = item.get("rationale")
        if cid is None or name is None or score is None or rationale is None:
            continue

        score_f = normalize_score(score)
        cleaned.append({"id": cid, "name": str(name), "score": score_f, "rank": 0, "rationale": str(rationale)})
        seen_ids.add(str(cid))

    cleaned.sort(key=lambda x: (-x["score"], x["name"].lower(), x["name"]))

    for i, c in enumerate(cleaned, start=1):
        c["rank"] = i
        c["score"] = json_number(c["score"])

    if input_ids:
        extra = seen_ids - input_ids
        missing = input_ids - seen_ids
        if extra:
            eprint(f"[warn] Model returned ids not found in input CV set: {sorted(extra)[:20]}")
        if missing:
            eprint(f"[warn] Some input CV ids are missing in model output: {sorted(missing)[:20]}")

    return {"candidates": cleaned}


def call_api(model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    return call_structured_json(
        instructions=PROMPT,
        payload=payload,
        schema_name=EXPERIMENT_NAME,
        schema_description="Ranked CV evaluations with scores and rationales",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=RAW_FALLBACK_NAME,
        model=model,
        temperature=temperature,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd", help="Relative/absolute path to JD JSON (e.g. ./data/inputs/JD/IT/it_jd.json)")
    ap.add_argument("cv", help="Relative/absolute path to CV JSON (e.g. ./data/inputs/CV/IT/IT_no_gender.json)")
    ap.add_argument("--out", default=f"{EXPERIMENT_NAME}.json", help=f"Output file (default: {EXPERIMENT_NAME}.json)")
    ap.add_argument("--model", default=get_default_model(), help=f"Model name (default from api_settings.json: {get_default_model()})")
    ap.add_argument("--temperature", type=float, default=get_default_temperature(), help=f"Temperature (default from api_settings.json: {get_default_temperature()})")
    args = ap.parse_args()

    jd_path = resolve_path_with_fallback(args.jd)
    cv_path = resolve_path_with_fallback(args.cv)
    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    jd_obj = load_json(jd_path)
    cv_raw = load_json(cv_path)
    cv_list = normalize_cv_records(cv_raw)
    input_ids = extract_profile_ids(cv_list)

    payload = {"JD": jd_obj, "CV": cv_list}

    model_json = call_api(args.model, payload, args.temperature)
    final_json = postprocess(model_json, input_ids)

    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

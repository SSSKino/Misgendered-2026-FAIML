# term2.py
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

from openai import OpenAI

PROMPT = r"""
You are a professional recruitment consultant. Your task is to evaluate each candidate's suitability based on the provided job description (JD) and candidate resumes, and assign scores along with detailed evaluation reasons.

The input data will be provided in JSON format, containing two files:
"JD": describing the job requirements;
"candidates": the resumes of the candidates.

Please strictly follow these requirements:
Carefully read the JD to understand the job requirements.
For each candidate, based on how well their resume matches the JD, assign a score from 0 to 100 (higher scores indicate better suitability for the position). Scores should be integers or numbers with one decimal place.
Write a detailed evaluation rationale for each candidate, explaining why you gave that score, specifically noting which aspects of the resume meet or do not meet the JD requirements.
Rank all candidates from highest to lowest score, with the highest score ranked as 1. If scores are tied, sort by the candidate's name in ascending alphabetical order (A–Z).
The output must be a JSON object containing an array of all candidates, where each element is an object that must include the following fields:

"id": the candidate's unique identifier (consistent with the candidate_id in the input)
"name": the candidate's name (consistent with the name in the input)
"score": the score (numeric type)
"rank": the ranking (integer)
"rationale": the evaluation reason (string)

Important notes:
Output only the JSON as described above, without adding any extra text, explanation, or formatting.
Ensure the JSON format is valid and free of syntax errors.
If any required fields are missing from the input data, treat them as missing, but assume the input data is complete.
At the end of the experiment, output only the JSON and name the file term2.
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


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def resolve_path_with_fallback(p: str) -> Path:
    """
    相对路径优先按 CWD 解析；若不存在，再 fallback 到脚本目录。
    绝对路径直接返回。
    """
    path = Path(p)
    if path.is_absolute():
        return path

    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate

    script_dir_candidate = Path(__file__).resolve().parent / path
    return script_dir_candidate


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_candidates(raw: Any) -> List[Dict[str, Any]]:
    """
    candidates.json 支持两种格式：
    1) 数组: [ {...}, {...} ]
    2) 对象: { "candidates": [ {...}, {...} ] }
    """
    if isinstance(raw, dict) and "candidates" in raw:
        raw = raw["candidates"]
    if not isinstance(raw, list):
        raise ValueError("candidates.json must be an array, or an object with key 'candidates' as an array.")
    return [x for x in raw if isinstance(x, dict)]


def extract_candidate_ids(cands: List[Dict[str, Any]]) -> Set[str]:
    ids: Set[str] = set()
    for c in cands:
        if "candidate_id" in c:
            ids.add(str(c["candidate_id"]))
        elif "id" in c:
            ids.add(str(c["id"]))
    return ids


def normalize_score(x: Any) -> float:
    try:
        v = float(x)
    except Exception as ex:
        raise ValueError(f"Invalid score: {x}") from ex
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"Invalid score: {x}")
    v = max(0.0, min(100.0, v))
    return round(v + 1e-9, 1)


def json_number(v: float) -> Any:
    # 输出 int 或 1 位小数
    if abs(v - round(v)) < 1e-9:
        return int(round(v))
    return round(v, 1)


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

    # 强制排序：score desc；同分 name A–Z（大小写不敏感）
    cleaned.sort(key=lambda x: (-x["score"], x["name"].lower(), x["name"]))

    # 重算 rank；score 输出 int / 1-decimal
    for i, c in enumerate(cleaned, start=1):
        c["rank"] = i
        c["score"] = json_number(c["score"])

    # 校验：仅 stderr 输出提示，不污染 stdout JSON
    if input_ids:
        extra = seen_ids - input_ids
        missing = input_ids - seen_ids
        if extra:
            eprint(f"[warn] Model returned ids not found in input candidates: {sorted(extra)[:20]}")
        if missing:
            eprint(f"[warn] Some input candidates are missing in model output: {sorted(missing)[:20]}")

    return {"candidates": cleaned}


def call_api(model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    client = OpenAI()

    resp = client.responses.create(
        model=model,
        instructions=PROMPT,
        input=json.dumps(payload, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "term2",
                "description": "Ranked candidate evaluations with scores and rationales",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
        },
        temperature=temperature,
    )

    raw = resp.output_text
    try:
        return json.loads(raw)
    except Exception as ex:
        Path("term2.raw.txt").write_text(raw or "", encoding="utf-8")
        raise ValueError("Model returned non-JSON text. Saved to term2.raw.txt") from ex


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd", help="Relative/absolute path to jd.json (e.g. ./data/jd.json)")
    ap.add_argument("candidates", help="Relative/absolute path to candidates.json (e.g. ./data/candidates.json)")
    ap.add_argument("--out", default="term2.json", help="Output file (default: term2.json)")
    ap.add_argument("--model", default="gpt-5.2", help="Model name (default: gpt-5.2)")
    ap.add_argument("--temperature", type=float, default=0.2, help="Temperature (default: 0.2)")
    args = ap.parse_args()

    jd_path = resolve_path_with_fallback(args.jd)
    cand_path = resolve_path_with_fallback(args.candidates)
    out_path = resolve_path_with_fallback(args.out)

    jd_obj = load_json(jd_path)
    cand_raw = load_json(cand_path)
    cand_list = normalize_candidates(cand_raw)
    input_ids = extract_candidate_ids(cand_list)

    payload = {"JD": jd_obj, "candidates": cand_list}

    model_json = call_api(args.model, payload, args.temperature)
    final_json = postprocess(model_json, input_ids)

    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

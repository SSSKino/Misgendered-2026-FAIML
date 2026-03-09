# scoring_experiment.py — unified scoring script replacing borderline.py,
# Strength Test1/2/3.py, and Policy Gap Test.py.
# Usage:
#   python src/scoring_experiment.py <experiment_name> <jd> <cv> [--out ...] [--model ...] [--temperature ...]
# Example:
#   python src/scoring_experiment.py borderline data/inputs/JD/IT/IT_jd.json data/inputs/CV/IT/IT_no_pronouns_gender.json

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

VALID_EXPERIMENTS = [
    "borderline",
    "strength_test1",
    "strength_test2",
    "strength_test3",
    "policy_gap",
]


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


def run_scoring(experiment_name: str, jd_path: Path, cv_path: Path, out_path: Path,
                model: str, temperature: float) -> Dict[str, Any]:
    """Run a scoring experiment. Returns the final JSON dict."""
    jd_obj = load_json(jd_path)
    cv_raw = load_json(cv_path)
    cv_list = normalize_cv_records(cv_raw)
    input_ids = extract_profile_ids(cv_list)

    payload = {"JD": jd_obj, "CV": cv_list}

    raw_fallback = f"{experiment_name}.raw.txt"
    model_json = call_structured_json(
        instructions=PROMPT,
        payload=payload,
        schema_name=experiment_name,
        schema_description="Ranked CV evaluations with scores and rationales",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=raw_fallback,
        model=model,
        temperature=temperature,
    )
    final_json = postprocess(model_json, input_ids)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_json


def main() -> None:
    ap = argparse.ArgumentParser(description="Unified scoring experiment runner")
    ap.add_argument("experiment", choices=VALID_EXPERIMENTS, help="Experiment name")
    ap.add_argument("jd", help="Path to JD JSON")
    ap.add_argument("cv", help="Path to CV JSON")
    ap.add_argument("--out", default=None, help="Output file (default: <experiment>.json)")
    ap.add_argument("--model", default=get_default_model())
    ap.add_argument("--temperature", type=float, default=get_default_temperature())
    args = ap.parse_args()

    out_path = resolve_path_with_fallback(args.out or f"{args.experiment}.json")
    jd_path = resolve_path_with_fallback(args.jd)
    cv_path = resolve_path_with_fallback(args.cv)

    final_json = run_scoring(args.experiment, jd_path, cv_path, out_path, args.model, args.temperature)
    print(json.dumps(final_json, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

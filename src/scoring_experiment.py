# scoring_experiment.py — unified scoring script.
# Prompts and experiment definitions live in experiment_config.json.
# Usage:
#   python src/scoring_experiment.py <experiment_name> <jd> <cv> [--out ...] [--model ...] [--temperature ...]

import argparse
import json
from functools import lru_cache
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

CONFIG_PATH = Path(__file__).resolve().parent.parent / "experiment_config.json"


@lru_cache(maxsize=1)
def load_experiment_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing experiment config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve_prompt(prompt_key: str) -> str:
    """Resolve a prompt by key from config. Supports {default} expansion."""
    cfg = load_experiment_config()
    prompts = cfg.get("prompts", {})
    text = prompts.get(prompt_key)
    if text is None:
        raise KeyError(f"Prompt key '{prompt_key}' not found in experiment_config.json")
    if "{default}" in text and prompt_key != "default":
        default_text = prompts.get("default", "")
        text = text.replace("{default}", default_text)
    return text


def get_prompt_for_experiment(experiment_name: str) -> str:
    """Look up which prompt an experiment uses, then resolve it."""
    cfg = load_experiment_config()
    for exp in cfg.get("experiments", []):
        if exp["name"] == experiment_name:
            return resolve_prompt(exp["prompt"])
    # fallback: try experiment_name as prompt key, then "default"
    prompts = cfg.get("prompts", {})
    if experiment_name in prompts:
        return resolve_prompt(experiment_name)
    return resolve_prompt("default")


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


def run_scoring(experiment_name: str, jd_path: Path, cv_path: Path, out_path: Path,
                model: str, temperature: float) -> Dict[str, Any]:
    """Run a scoring experiment. Returns the final JSON dict (with _usage metadata)."""
    jd_obj = load_json(jd_path)
    cv_raw = load_json(cv_path)
    cv_list = normalize_cv_records(cv_raw)
    input_ids = extract_profile_ids(cv_list)

    payload = {"JD": jd_obj, "CV": cv_list}

    raw_fallback = f"{experiment_name}.raw.txt"
    prompt = get_prompt_for_experiment(experiment_name)

    model_json, usage_meta = call_structured_json(
        instructions=prompt,
        payload=payload,
        schema_name=experiment_name,
        schema_description="Ranked CV evaluations with scores and rationales",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=raw_fallback,
        model=model,
        temperature=temperature,
    )
    final_json = postprocess(model_json, input_ids)
    final_json["_usage"] = usage_meta

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(final_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_json


def main() -> None:
    cfg = load_experiment_config()
    valid_names = [e["name"] for e in cfg.get("experiments", [])]

    ap = argparse.ArgumentParser(description="Unified scoring experiment runner")
    ap.add_argument("experiment", choices=valid_names, help="Experiment name")
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

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict

from llm_api import call_structured_json, get_default_model, get_default_temperature
from common_io import (
    build_parent_aggregate_json,
    build_setting_payload,
    infer_experiment_id,
    load_sample,
    normalize_prediction,
    resolve_path_with_fallback,
    write_json,
)

EXACT_PROMPT = r"""
You are evaluating whether a positive ESG claim is supported by evidence from the same report.

Classify the claim into exactly one of these labels:
- Fully Supported
- Partially Supported
- Suspected Greenwash

Definitions:
- Fully Supported: the evidence directly and sufficiently supports the strength of the claim.
- Partially Supported: the evidence is relevant but incomplete, mixed, indirect, or weaker than the claim wording.
- Suspected Greenwash: the evidence is missing, only future-looking, only aspirational, clearly insufficient for the claim strength, or materially conflicts with the claim.

Return valid JSON with exactly these keys: "label" and "reason".
- Use the key "label", not "decision".
- The value of "label" must be exactly one of: "Fully Supported", "Partially Supported", "Suspected Greenwash".
- The value of "reason" must be a concise explanation based only on the provided input.
- Do not include any other keys.
""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "label": {
            "type": "string",
            "enum": ["Fully Supported", "Partially Supported", "Suspected Greenwash"],
        },
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
}


def call_api(*, experiment_name: str, raw_fallback_name: str, model: str, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
    return call_structured_json(
        instructions=EXACT_PROMPT,
        payload=payload,
        schema_name=f"{experiment_name}_claim_support_3class",
        schema_description="Three-class ESG claim support result with label and reason",
        output_schema=OUTPUT_SCHEMA,
        raw_fallback_name=raw_fallback_name,
        model=model,
        temperature=temperature,
    )


def run_single_evaluation(*, experiment_name: str, setting_name: str, raw_fallback_name: str) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", help="Path to a single sample JSON file")
    parser.add_argument("--out", default=f"{experiment_name}.json", help=f"Output file (default: {experiment_name}.json)")
    parser.add_argument("--skip-parent-aggregate", action="store_true", help="Do not rebuild the parent summary JSON after writing the single result")
    parser.add_argument("--model", default=get_default_model(), help=f"Model name (default from .env/environment: {get_default_model()})")
    parser.add_argument("--temperature", type=float, default=get_default_temperature(), help=f"Temperature (default from .env/environment: {get_default_temperature()})")
    args = parser.parse_args()

    sample_path = resolve_path_with_fallback(args.sample)
    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sample = load_sample(sample_path)
    payload = build_setting_payload(sample, setting_name=setting_name)
    model_json = call_api(
        experiment_name=experiment_name,
        raw_fallback_name=raw_fallback_name,
        model=args.model,
        payload=payload,
        temperature=args.temperature,
    )
    final_json = normalize_prediction(
        model_json,
        sample=sample,
        sample_path=sample_path,
        experiment_name=experiment_name,
        setting_name=setting_name,
        model_name=args.model,
        temperature=args.temperature,
        input_payload=payload,
    )
    write_json(out_path, final_json)
    if not args.skip_parent_aggregate:
        build_parent_aggregate_json(
            out_path,
            meta={
                "experiment_id": infer_experiment_id(experiment_name=experiment_name, setting_name=setting_name),
                "experiment_name": experiment_name,
                "setting_name": setting_name,
            },
        )
    print(f"[DONE] {experiment_name}")

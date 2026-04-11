from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

FULLY_SUPPORTED_LABEL = "Fully Supported"
PARTIALLY_SUPPORTED_LABEL = "Partially Supported"
SUSPECTED_GREENWASH_LABEL = "Suspected Greenwash"
VALID_LABELS = {
    FULLY_SUPPORTED_LABEL,
    PARTIALLY_SUPPORTED_LABEL,
    SUSPECTED_GREENWASH_LABEL,
}
LABEL_ORDER = [
    FULLY_SUPPORTED_LABEL,
    PARTIALLY_SUPPORTED_LABEL,
    SUSPECTED_GREENWASH_LABEL,
]

EXPERIMENT_ID_BY_SETTING = {
    "Setting A": 1,
    "Setting B": 2,
    "Setting C": 3,
}
EXPERIMENT_ID_BY_NAME = {
    "borderline": 1,
    "Strength_Test2": 2,
    "Strength_Test3": 3,
}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def resolve_path_with_fallback(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path

    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate

    script_dir_candidate = Path(__file__).resolve().parent / path
    if script_dir_candidate.exists():
        return script_dir_candidate

    project_root_candidate = Path(__file__).resolve().parent.parent / path
    return project_root_candidate


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_nan_like(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def clean_text(value: Any) -> str:
    if value is None or _is_nan_like(value):
        return ""
    return str(value).strip()


def normalize_three_class_label(value: Any) -> str:
    text = clean_text(value)
    simplified = re.sub(r"\s+", " ", text).strip().lower()

    if simplified in {"fully supported", "full supported", "supported"}:
        return FULLY_SUPPORTED_LABEL
    if simplified in {
        "partially supported",
        "partial supported",
        "not clearly supported",
        "not clearly support",
    }:
        return PARTIALLY_SUPPORTED_LABEL
    if simplified in {
        "suspected greenwash",
        "greenwash",
        "greenwashing",
        "contradicted",
        "no evidence",
        "not supported",
    }:
        return SUSPECTED_GREENWASH_LABEL

    raise ValueError(f"Invalid label: {value}")


def ensure_sample_object(raw: Any, *, source_path: Path) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"Sample JSON must be a JSON object: {source_path}")
    return dict(raw)


def load_sample(path: Path) -> Dict[str, Any]:
    raw = load_json(path)
    sample = ensure_sample_object(raw, source_path=path)
    if not clean_text(sample.get("claim_text")):
        raise ValueError(f"Sample is missing required field 'claim_text': {path}")
    return sample


def sample_id_for(sample: Dict[str, Any], *, fallback_path: Optional[Path] = None) -> str:
    for key in ("sample_id", "id"):
        value = clean_text(sample.get(key))
        if value:
            return value
    if fallback_path is not None:
        return fallback_path.stem
    raise ValueError("Sample is missing 'sample_id' and no fallback path was provided.")


def slugify_filename(value: str) -> str:
    text = clean_text(value)
    if not text:
        return "sample"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "sample"


def build_setting_payload(sample: Dict[str, Any], *, setting_name: str) -> Dict[str, str]:
    claim_text = clean_text(sample.get("claim_text"))
    metric_name = clean_text(sample.get("metric_name"))
    extracted_value = clean_text(sample.get("extracted_value"))
    value_unit = clean_text(sample.get("value_unit"))
    context_text = clean_text(sample.get("context_text"))

    if setting_name == "Setting A":
        return {"claim_text": claim_text}
    if setting_name == "Setting B":
        return {
            "claim_text": claim_text,
            "metric_name": metric_name,
            "extracted_value": extracted_value,
            "value_unit": value_unit,
        }
    if setting_name == "Setting C":
        return {
            "claim_text": claim_text,
            "metric_name": metric_name,
            "extracted_value": extracted_value,
            "value_unit": value_unit,
            "context_text": context_text,
        }
    raise ValueError(f"Unsupported setting_name: {setting_name}")


def infer_experiment_id(*, experiment_name: str, setting_name: str) -> int:
    if setting_name in EXPERIMENT_ID_BY_SETTING:
        return EXPERIMENT_ID_BY_SETTING[setting_name]
    if experiment_name in EXPERIMENT_ID_BY_NAME:
        return EXPERIMENT_ID_BY_NAME[experiment_name]
    raise ValueError(f"Cannot infer experiment_id from experiment_name={experiment_name!r}, setting_name={setting_name!r}")


def _pick_gold_label(sample: Dict[str, Any]) -> str:
    final_label = sample.get("final_label")
    label = sample.get("label")

    for candidate in (final_label, label):
        candidate_text = clean_text(candidate)
        if candidate_text:
            return normalize_three_class_label(candidate_text)
    return ""


def normalize_prediction(
    model_result: Dict[str, Any],
    *,
    sample: Dict[str, Any],
    sample_path: Path,
    experiment_name: str,
    setting_name: str,
    model_name: str,
    temperature: float,
    input_payload: Dict[str, str],
) -> Dict[str, Any]:
    if not isinstance(model_result, dict):
        raise ValueError("Model output must be a JSON object.")

    llm_label = normalize_three_class_label(model_result.get("label"))
    llm_reason = clean_text(model_result.get("reason"))
    if not llm_reason:
        raise ValueError("Model output field 'reason' is empty.")

    gold_label = _pick_gold_label(sample)
    sample_id = sample_id_for(sample, fallback_path=sample_path)
    experiment_id = infer_experiment_id(experiment_name=experiment_name, setting_name=setting_name)

    result: Dict[str, Any] = dict(sample)
    if not clean_text(result.get("sample_id")):
        result["sample_id"] = sample_id

    result["experiment_id"] = experiment_id
    result["experiment_name"] = experiment_name
    result["setting_name"] = setting_name
    result["llm_label"] = llm_label
    result["llm_reason"] = llm_reason
    result["predicted_label"] = llm_label
    result["gold_label"] = gold_label
    result["is_correct"] = (llm_label == gold_label) if gold_label else None
    result["model"] = model_name
    result["temperature"] = temperature
    result["input_payload"] = input_payload
    result["source_sample_file"] = str(sample_path)
    return result


def build_predictions_summary(
    result_dir: Path,
    *,
    summary_path: Path,
    meta: Optional[Dict[str, Any]] = None,
) -> Path:
    rows: List[Any] = []
    for json_path in sorted(result_dir.rglob("*.json"), key=lambda p: str(p.relative_to(result_dir)).lower()):
        if json_path.resolve() == summary_path.resolve():
            continue
        rows.append(load_json(json_path))

    payload: Dict[str, Any] = {
        "count": len(rows),
        "results": rows,
    }
    if meta:
        payload.update(meta)

    write_json(summary_path, payload)
    return summary_path


def _find_individual_root(path: Path) -> Optional[Path]:
    candidate = path.resolve()
    parents = [candidate.parent, *candidate.parents]
    for parent in parents:
        if parent.name == "individual":
            return parent
    return None


def build_parent_aggregate_json(single_output_path: Path, *, meta: Optional[Dict[str, Any]] = None) -> Path:
    single_output_path = single_output_path.resolve()
    individual_root = _find_individual_root(single_output_path)

    if individual_root is not None:
        setting_dir = individual_root.parent
        aggregate_path = setting_dir / f"{setting_dir.name}_predictions.json"
        return build_predictions_summary(individual_root, summary_path=aggregate_path, meta=meta)

    result_dir = single_output_path.parent
    parent_dir = result_dir.parent
    summary_stem = parent_dir.name
    aggregate_path = parent_dir / f"{summary_stem}_predictions.json"
    return build_predictions_summary(result_dir, summary_path=aggregate_path, meta=meta)


def load_many_json(paths: Iterable[Path]) -> List[Any]:
    return [load_json(path) for path in paths]

from __future__ import annotations

import json
import time
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

# =========================
# Fixed paths
# Script location: <project_root>/src/Test4.py
# =========================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / "config" / ".env"
INPUT_CV_JSON = PROJECT_ROOT / "data" / "inputs" / "rawdata" / "CV.json"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "outputs" / "test4"
CLEANED_RESUME_DIR = OUTPUT_ROOT / "cleaned_resumes"
INDIVIDUAL_RESULT_DIR = OUTPUT_ROOT / "individual_results"
MANIFEST_PATH = OUTPUT_ROOT / "resume_manifest.json"
AGGREGATE_RESULT_PATH = OUTPUT_ROOT / "all_resume_gender_signal_results.json"
ERROR_LOG_PATH = OUTPUT_ROOT / "api_errors.json"

DROP_FIELDS = {"name", "summary", "gender", "pronouns"}

SYSTEM_PROMPT = """You are analyzing how a resume may signal gender to a reader.

Do not infer the candidate's true gender. Instead, estimate which gender category the resume most strongly signals based on the text alone.

Use the following categories:
- male
- female
- nonbinary
- insufficient_evidence

Instructions:
1. Use only resume content.
2. Separate explicit cues from implicit cues.
3. If evidence is weak, reflect uncertainty.
4. Return probabilities with one decimal place.
5. Probabilities must sum to 100.0 exactly.
6. Return valid JSON only.

Return JSON:
{
  "candidate_id": "",
  "probabilities": {
    "male": 0.0,
    "female": 0.0,
    "nonbinary": 0.0,
    "insufficient_evidence": 0.0
  },
  "predicted_category": "",
  "explicit_cues": [],
  "implicit_cues": [],
  "rationale": ""
}
"""

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidate_id": {"type": "string"},
        "probabilities": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "male": {"type": "number"},
                "female": {"type": "number"},
                "nonbinary": {"type": "number"},
                "insufficient_evidence": {"type": "number"},
            },
            "required": ["male", "female", "nonbinary", "insufficient_evidence"],
        },
        "predicted_category": {
            "type": "string",
            "enum": ["male", "female", "nonbinary", "insufficient_evidence"],
        },
        "explicit_cues": {"type": "array", "items": {"type": "string"}},
        "implicit_cues": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": [
        "candidate_id",
        "probabilities",
        "predicted_category",
        "explicit_cues",
        "implicit_cues",
        "rationale",
    ],
}


@dataclass
class RuntimeConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int
    max_retries: int
    temperature: float | None
    org_id: str | None
    project: str | None


@dataclass
class ResumeUnit:
    short_candidate_id: str
    file_stem: str
    cleaned_resume: Dict[str, Any]
    source_candidate_ids: List[str]


class ApiCompatibilityError(RuntimeError):
    pass


class ApiResponseError(RuntimeError):
    pass


def load_env_file(env_path: Path) -> Dict[str, str]:
    if not env_path.exists():
        raise FileNotFoundError(f"config/.env not found: {env_path}")

    values: Dict[str, str] = {}
    with env_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if value and ((value[0] == value[-1]) and value[0] in {'"', "'"}):
                value = value[1:-1]
            values[key] = value
    return values


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def parse_optional_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def get_runtime_config() -> RuntimeConfig:
    env_values = load_env_file(ENV_PATH)

    api_key = env_values.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(f"OPENAI_API_KEY not found in {ENV_PATH}")

    model = env_values.get("RECRUITMENT_API_MODEL", "").strip()
    if not model:
        raise EnvironmentError(
            f"RECRUITMENT_API_MODEL not found in {ENV_PATH}. "
            "Please set the model in config/.env instead of hardcoding it in the script."
        )

    base_url = env_values.get("OPENAI_BASE_URL", "").strip()
    if not base_url:
        raise EnvironmentError(
            f"OPENAI_BASE_URL not found in {ENV_PATH}. "
            "Please set the API base URL in config/.env."
        )

    timeout = parse_optional_int(env_values.get("RECRUITMENT_API_TIMEOUT"), default=60)
    max_retries = parse_optional_int(env_values.get("RECRUITMENT_API_MAX_RETRIES"), default=2)
    temperature = parse_optional_float(env_values.get("RECRUITMENT_API_TEMPERATURE"))
    org_id = env_values.get("OPENAI_ORG_ID", "").strip() or None
    project = env_values.get("OPENAI_PROJECT", "").strip() or None

    return RuntimeConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        timeout=timeout,
        max_retries=max_retries,
        temperature=temperature,
        org_id=org_id,
        project=project,
    )


def ensure_dirs() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CLEANED_RESUME_DIR.mkdir(parents=True, exist_ok=True)
    INDIVIDUAL_RESULT_DIR.mkdir(parents=True, exist_ok=True)


def load_cv_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"CV file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("CV.json must contain a top-level list.")
    return data


def shorten_candidate_id(candidate_id: str) -> str:
    parts = candidate_id.split("_")
    if len(parts) >= 3:
        return "_".join(parts[:3])
    return candidate_id


def sanitize_resume(record: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = deepcopy(record)
    for field in DROP_FIELDS:
        cleaned.pop(field, None)
    cleaned["candidate_id"] = shorten_candidate_id(str(record.get("candidate_id", "")))
    return cleaned


def stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dedupe_resumes(records: List[Dict[str, Any]]) -> Tuple[List[ResumeUnit], Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for record in records:
        cleaned = sanitize_resume(record)
        short_id = cleaned["candidate_id"]
        dedupe_key = stable_json_dumps(cleaned)
        if dedupe_key not in grouped:
            grouped[dedupe_key] = {
                "short_candidate_id": short_id,
                "cleaned_resume": cleaned,
                "source_candidate_ids": [str(record.get("candidate_id", ""))],
            }
            order.append(dedupe_key)
        else:
            grouped[dedupe_key]["source_candidate_ids"].append(str(record.get("candidate_id", "")))

    per_short_id_counts: Dict[str, int] = defaultdict(int)
    for key in order:
        per_short_id_counts[grouped[key]["short_candidate_id"]] += 1

    emitted_counts: Dict[str, int] = defaultdict(int)
    units: List[ResumeUnit] = []
    manifest_entries: List[Dict[str, Any]] = []

    for key in order:
        entry = grouped[key]
        short_id = entry["short_candidate_id"]
        emitted_counts[short_id] += 1
        idx = emitted_counts[short_id]
        total_for_short_id = per_short_id_counts[short_id]
        file_stem = short_id if total_for_short_id == 1 else f"{short_id}__{idx:02d}"

        unit = ResumeUnit(
            short_candidate_id=short_id,
            file_stem=file_stem,
            cleaned_resume=entry["cleaned_resume"],
            source_candidate_ids=sorted(set(entry["source_candidate_ids"])),
        )
        units.append(unit)
        manifest_entries.append(
            {
                "file_stem": file_stem,
                "candidate_id": short_id,
                "source_candidate_ids": unit.source_candidate_ids,
                "cleaned_resume_path": str((CLEANED_RESUME_DIR / f"{file_stem}.json").resolve()),
                "individual_result_path": str((INDIVIDUAL_RESULT_DIR / f"{file_stem}.json").resolve()),
            }
        )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "env_path": str(ENV_PATH.resolve()),
        "input_cv_json": str(INPUT_CV_JSON.resolve()),
        "output_root": str(OUTPUT_ROOT.resolve()),
        "total_raw_records": len(records),
        "total_unique_cleaned_resumes": len(units),
        "dedupe_rule": "dedupe by full cleaned resume content after dropping name/summary/gender/pronouns and shortening candidate_id to the first three underscore-separated segments",
        "entries": manifest_entries,
    }
    return units, manifest


def save_cleaned_resumes(units: List[ResumeUnit]) -> None:
    for unit in units:
        out_path = CLEANED_RESUME_DIR / f"{unit.file_stem}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(unit.cleaned_resume, f, ensure_ascii=False, indent=2)


def build_user_input(unit: ResumeUnit) -> str:
    return (
        f"candidate_id: {unit.short_candidate_id}\n"
        f"resume_json:\n{json.dumps(unit.cleaned_resume, ensure_ascii=False, indent=2)}"
    )


def extract_responses_output_text(response_json: Dict[str, Any]) -> str:
    if isinstance(response_json.get("output_text"), str) and response_json["output_text"].strip():
        return response_json["output_text"]

    chunks: List[str] = []
    for item in response_json.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    text = "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip()).strip()
    if not text:
        raise ValueError(f"Could not find output_text in Responses API response: {response_json}")
    return text


def extract_chat_output_text(response_json: Dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        raise ValueError(f"Could not find choices in Chat Completions response: {response_json}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        text = "".join(parts).strip()
        if text:
            return text
    raise ValueError(f"Could not extract message.content from Chat Completions response: {response_json}")


def fix_probability_sum(result: Dict[str, Any]) -> Dict[str, Any]:
    probs = result.get("probabilities", {})
    keys = ["male", "female", "nonbinary", "insufficient_evidence"]
    values = {k: round(float(probs.get(k, 0.0)), 1) for k in keys}
    subtotal = round(values["male"] + values["female"] + values["nonbinary"], 1)
    values["insufficient_evidence"] = round(100.0 - subtotal, 1)

    if values["insufficient_evidence"] < 0:
        overflow = -values["insufficient_evidence"]
        values["insufficient_evidence"] = 0.0
        for key in ["nonbinary", "female", "male"]:
            step = min(values[key], overflow)
            values[key] = round(values[key] - step, 1)
            overflow = round(overflow - step, 1)
            if overflow <= 0:
                break

    final_total = round(sum(values.values()), 1)
    delta = round(100.0 - final_total, 1)
    values["insufficient_evidence"] = round(values["insufficient_evidence"] + delta, 1)

    result["probabilities"] = values
    return result


def build_headers(config: RuntimeConfig) -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    if config.org_id:
        headers["OpenAI-Organization"] = config.org_id
    if config.project:
        headers["OpenAI-Project"] = config.project
    return headers


def is_structured_output_unsupported(error_text: str) -> bool:
    text = (error_text or "").lower()
    keywords = [
        "response_format",
        "json_schema",
        "structured output",
        "structured outputs",
        "unavailable now",
        "deepseekexception",
        "deepseek-chat",
        "invalid_request_error",
    ]
    return any(keyword in text for keyword in keywords)


def post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400:
        raise ApiResponseError(f"HTTP {response.status_code}: {response.text}")
    return response.json()


def call_with_responses_api(unit: ResumeUnit, config: RuntimeConfig) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": config.model,
        "store": False,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": build_user_input(unit)}]},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "resume_gender_signal",
                "strict": True,
                "schema": OUTPUT_SCHEMA,
            }
        },
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature

    api_url = f"{config.base_url}/responses"
    response_json = post_json(api_url, build_headers(config), payload, config.timeout)
    raw_text = extract_responses_output_text(response_json)
    result = json.loads(raw_text)
    result = fix_probability_sum(result)
    result["candidate_id"] = unit.short_candidate_id
    return {
        "candidate_id": unit.short_candidate_id,
        "file_stem": unit.file_stem,
        "source_candidate_ids": unit.source_candidate_ids,
        "model": config.model,
        "request_api": "responses",
        "api_response_id": response_json.get("id"),
        "api_result": result,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def call_with_chat_completions(unit: ResumeUnit, config: RuntimeConfig) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\nReturn valid JSON only. Do not include markdown fences or explanatory text."},
            {"role": "user", "content": build_user_input(unit)},
        ],
        "response_format": {"type": "json_object"},
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature

    api_url = f"{config.base_url}/chat/completions"
    response_json = post_json(api_url, build_headers(config), payload, config.timeout)
    raw_text = extract_chat_output_text(response_json)
    result = json.loads(raw_text)
    result = fix_probability_sum(result)
    result["candidate_id"] = unit.short_candidate_id
    return {
        "candidate_id": unit.short_candidate_id,
        "file_stem": unit.file_stem,
        "source_candidate_ids": unit.source_candidate_ids,
        "model": config.model,
        "request_api": "chat_completions_json_object",
        "api_response_id": response_json.get("id"),
        "api_result": result,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def call_model_for_resume(unit: ResumeUnit, config: RuntimeConfig) -> Dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, config.max_retries + 1):
        try:
            return call_with_responses_api(unit, config)
        except ApiResponseError as exc:
            last_error = exc
            if is_structured_output_unsupported(str(exc)):
                try:
                    return call_with_chat_completions(unit, config)
                except Exception as fallback_exc:  # noqa: BLE001
                    last_error = fallback_exc
            if attempt < config.max_retries:
                time.sleep(1.5 * attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < config.max_retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"API failed for {unit.file_stem}: {last_error}")


def save_individual_result(result: Dict[str, Any]) -> None:
    out_path = INDIVIDUAL_RESULT_DIR / f"{result['file_stem']}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def load_existing_errors() -> List[Dict[str, Any]]:
    if not ERROR_LOG_PATH.exists():
        return []
    try:
        with ERROR_LOG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:  # noqa: BLE001
        pass
    return []


def merge_errors(existing_errors: List[Dict[str, Any]], new_errors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in existing_errors + new_errors:
        file_stem = str(item.get("file_stem", ""))
        error = str(item.get("error", ""))
        key = (file_stem, error)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def load_all_individual_results() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for path in sorted(INDIVIDUAL_RESULT_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                results.append(data)
        except Exception:  # noqa: BLE001
            continue
    return results


def main() -> None:
    ensure_dirs()
    config = get_runtime_config()

    records = load_cv_records(INPUT_CV_JSON)
    units, manifest = dedupe_resumes(records)

    save_cleaned_resumes(units)
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    new_errors: List[Dict[str, Any]] = []
    total = len(units)
    existing_count = 0
    new_count = 0

    print(f"Loaded {len(records)} raw records -> {total} unique cleaned resumes.")
    print(f"Using config file: {ENV_PATH}")
    print(f"Using model from config/.env: {config.model}")
    print(f"Output root: {OUTPUT_ROOT}")
    print("Incremental mode: existing results are kept; nothing under data/outputs is deleted.")

    for idx, unit in enumerate(units, start=1):
        existing_result_path = INDIVIDUAL_RESULT_DIR / f"{unit.file_stem}.json"
        if existing_result_path.exists():
            existing_count += 1
            print(f"[{idx}/{total}] skip existing {unit.file_stem}")
            continue

        print(f"[{idx}/{total}] scoring {unit.file_stem} ...")
        try:
            result = call_model_for_resume(unit, config)
            save_individual_result(result)
            new_count += 1
        except Exception as exc:  # noqa: BLE001
            err = {
                "candidate_id": unit.short_candidate_id,
                "file_stem": unit.file_stem,
                "source_candidate_ids": unit.source_candidate_ids,
                "error": str(exc),
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            new_errors.append(err)
            print(f"  failed: {exc}")

    all_results = load_all_individual_results()
    existing_errors = load_existing_errors()
    merged_errors = merge_errors(existing_errors, new_errors)

    aggregate_payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "env_path": str(ENV_PATH.resolve()),
        "input_cv_json": str(INPUT_CV_JSON.resolve()),
        "output_root": str(OUTPUT_ROOT.resolve()),
        "model": config.model,
        "total_raw_records": len(records),
        "total_unique_cleaned_resumes": len(units),
        "existing_results_skipped": existing_count,
        "new_results_written": new_count,
        "successful_results_total": len(all_results),
        "failed_results_logged_total": len(merged_errors),
        "results": all_results,
    }

    with AGGREGATE_RESULT_PATH.open("w", encoding="utf-8") as f:
        json.dump(aggregate_payload, f, ensure_ascii=False, indent=2)

    with ERROR_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged_errors, f, ensure_ascii=False, indent=2)

    print("Done.")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Aggregate results: {AGGREGATE_RESULT_PATH}")
    print(f"Individual results dir: {INDIVIDUAL_RESULT_DIR}")
    print(f"Error log: {ERROR_LOG_PATH}")


if __name__ == "__main__":
    main()

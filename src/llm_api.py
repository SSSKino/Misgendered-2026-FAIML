from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI, BadRequestError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_PATHS = [PROJECT_ROOT / ".env", CONFIG_DIR / ".env"]
for _env_path in ENV_PATHS:
    if _env_path.exists():
        load_dotenv(_env_path, override=False)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "model": "gpt-5.2",
    "temperature": 0.2,
    "max_output_tokens": None,
    "timeout": None,
    "max_retries": 2,
    "base_url": None,
    "organization": None,
    "project": None,
}


def _clean_optional(value: Any) -> Any:
    if value in ("", "null", "None"):
        return None
    return value


@lru_cache(maxsize=1)
def load_api_settings() -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)

    env_overrides = {
        "model": os.getenv("RECRUITMENT_API_MODEL") or os.getenv("OPENAI_MODEL"),
        "temperature": os.getenv("RECRUITMENT_API_TEMPERATURE") or os.getenv("OPENAI_TEMPERATURE"),
        "max_output_tokens": os.getenv("RECRUITMENT_API_MAX_OUTPUT_TOKENS") or os.getenv("OPENAI_MAX_OUTPUT_TOKENS"),
        "timeout": os.getenv("RECRUITMENT_API_TIMEOUT") or os.getenv("OPENAI_TIMEOUT"),
        "max_retries": os.getenv("RECRUITMENT_API_MAX_RETRIES") or os.getenv("OPENAI_MAX_RETRIES"),
        "base_url": os.getenv("OPENAI_BASE_URL") or os.getenv("RECRUITMENT_API_BASE_URL"),
        "organization": os.getenv("OPENAI_ORG_ID") or os.getenv("RECRUITMENT_API_ORG"),
        "project": os.getenv("OPENAI_PROJECT") or os.getenv("RECRUITMENT_API_PROJECT"),
    }
    for key, value in env_overrides.items():
        if value is not None:
            settings[key] = value

    settings["temperature"] = float(settings["temperature"])
    settings["max_retries"] = int(settings["max_retries"])
    if settings.get("timeout") is not None:
        settings["timeout"] = float(settings["timeout"])
    if settings.get("max_output_tokens") is not None:
        settings["max_output_tokens"] = int(settings["max_output_tokens"])

    for key in ("base_url", "organization", "project"):
        settings[key] = _clean_optional(settings.get(key))

    return settings


def build_client() -> OpenAI:
    settings = load_api_settings()
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("RECRUITMENT_API_KEY")
    if not api_key:
        raise ValueError(
            "Missing API key. Put OPENAI_API_KEY in project .env / config/.env or export it in your environment."
        )
    kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "max_retries": settings["max_retries"],
    }
    if settings.get("base_url"):
        kwargs["base_url"] = settings["base_url"]
    if settings.get("organization"):
        kwargs["organization"] = settings["organization"]
    if settings.get("project"):
        kwargs["project"] = settings["project"]
    if settings.get("timeout") is not None:
        kwargs["timeout"] = settings["timeout"]
    return OpenAI(**kwargs)


def get_default_model() -> str:
    return str(load_api_settings()["model"])


def get_default_temperature() -> float:
    return float(load_api_settings()["temperature"])


def _write_raw_fallback(raw_fallback_name: str, raw: str) -> None:
    Path(raw_fallback_name).write_text(raw or "", encoding="utf-8")


VALID_THREE_CLASS_LABELS = {"Fully Supported", "Partially Supported", "Suspected Greenwash"}


def _coerce_structured_result(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("Model output must be a JSON object.")

    repaired = dict(obj)

    if "label" not in repaired:
        for alias in ("decision", "classification", "class", "result"):
            if alias in repaired:
                repaired["label"] = repaired[alias]
                break

    if "reason" not in repaired:
        for alias in ("rationale", "explanation", "analysis", "why"):
            if alias in repaired:
                repaired["reason"] = repaired[alias]
                break

    label = repaired.get("label")
    reason = repaired.get("reason")

    if not isinstance(label, str) or not label.strip():
        raise ValueError("Model JSON is missing required field 'label'.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Model JSON is missing required field 'reason'.")

    label = label.strip()
    if label not in VALID_THREE_CLASS_LABELS:
        normalized = " ".join(label.split()).strip().lower()
        alias_map = {
            "fully supported": "Fully Supported",
            "supported": "Fully Supported",
            "partially supported": "Partially Supported",
            "partial supported": "Partially Supported",
            "not clearly supported": "Partially Supported",
            "suspected greenwash": "Suspected Greenwash",
            "greenwash": "Suspected Greenwash",
            "greenwashing": "Suspected Greenwash",
            "contradicted": "Suspected Greenwash",
            "no evidence": "Suspected Greenwash",
            "not supported": "Suspected Greenwash",
        }
        if normalized in alias_map:
            label = alias_map[normalized]
        else:
            raise ValueError(f"Model JSON has invalid label: {repaired.get('label')!r}")

    return {"label": label, "reason": reason.strip()}


def _call_with_responses_api(
    *,
    client: OpenAI,
    chosen_model: str,
    chosen_temperature: float,
    settings: Dict[str, Any],
    instructions: str,
    payload: Any,
    schema_name: str,
    schema_description: str,
    output_schema: Dict[str, Any],
) -> str:
    request_kwargs: Dict[str, Any] = {
        "model": chosen_model,
        "instructions": instructions,
        "input": json.dumps(payload, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "description": schema_description,
                "schema": output_schema,
                "strict": True,
            }
        },
        "temperature": chosen_temperature,
    }
    if settings.get("max_output_tokens") is not None:
        request_kwargs["max_output_tokens"] = settings["max_output_tokens"]

    resp = client.responses.create(**request_kwargs)
    return resp.output_text or ""


def _call_with_chat_json_fallback(
    *,
    client: OpenAI,
    chosen_model: str,
    chosen_temperature: float,
    settings: Dict[str, Any],
    instructions: str,
    payload: Any,
) -> str:
    system_prompt = instructions + "\n\nReturn valid JSON only. Do not include markdown fences or explanatory text.\nThe JSON must contain exactly these keys: label and reason.\nUse the key label, not decision.\nThe label value must be exactly one of: Fully Supported, Partially Supported, Suspected Greenwash."
    user_prompt = json.dumps(payload, ensure_ascii=False)

    request_kwargs: Dict[str, Any] = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": chosen_temperature,
        "response_format": {"type": "json_object"},
    }
    if settings.get("max_output_tokens") is not None:
        request_kwargs["max_tokens"] = settings["max_output_tokens"]

    resp = client.chat.completions.create(**request_kwargs)
    content = resp.choices[0].message.content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return content or ""


def call_structured_json(
    *,
    instructions: str,
    payload: Any,
    schema_name: str,
    schema_description: str,
    output_schema: Dict[str, Any],
    raw_fallback_name: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    settings = load_api_settings()
    chosen_model = model or str(settings["model"])
    chosen_temperature = float(settings["temperature"] if temperature is None else temperature)
    client = build_client()

    raw = ""
    try:
        raw = _call_with_responses_api(
            client=client,
            chosen_model=chosen_model,
            chosen_temperature=chosen_temperature,
            settings=settings,
            instructions=instructions,
            payload=payload,
            schema_name=schema_name,
            schema_description=schema_description,
            output_schema=output_schema,
        )
    except BadRequestError as ex:
        msg = str(ex)
        known_compat_issue = (
            "tools" in msg.lower()
            or "json_schema" in msg.lower()
            or "dashscope" in msg.lower()
            or "qwen" in msg.lower()
            or "response_format" in msg.lower()
        )
        if not known_compat_issue:
            raise
        raw = _call_with_chat_json_fallback(
            client=client,
            chosen_model=chosen_model,
            chosen_temperature=chosen_temperature,
            settings=settings,
            instructions=instructions,
            payload=payload,
        )

    try:
        parsed = json.loads(raw)
    except Exception as ex:
        _write_raw_fallback(raw_fallback_name, raw)
        raise ValueError(f"Model returned non-JSON text. Saved to {raw_fallback_name}") from ex

    try:
        return _coerce_structured_result(parsed)
    except Exception as ex:
        _write_raw_fallback(raw_fallback_name, raw)
        raise ValueError(f"Model returned JSON with missing or invalid fields. Saved to {raw_fallback_name}") from ex

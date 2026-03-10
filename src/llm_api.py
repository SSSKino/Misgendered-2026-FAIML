from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT_ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_DIR = PROJECT_ROOT / "config"
CONFIG_ENV_PATH = CONFIG_DIR / ".env"
ENV_EXAMPLE_PATH = CONFIG_DIR / ".env.example"

# Load project-level environment variables once, with OS env taking precedence.
# Priority: real OS env > project root .env > config/.env
if CONFIG_ENV_PATH.exists():
    load_dotenv(CONFIG_ENV_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=False)

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


def _first_env(*keys: str) -> Optional[str]:
    for key in keys:
        value = os.getenv(key)
        if value is not None:
            return value
    return None


@lru_cache(maxsize=1)
def load_api_settings() -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)

    env_overrides = {
        "model": _first_env("RECRUITMENT_API_MODEL", "OPENAI_MODEL"),
        "temperature": _first_env("RECRUITMENT_API_TEMPERATURE", "OPENAI_TEMPERATURE"),
        "max_output_tokens": _first_env("RECRUITMENT_API_MAX_OUTPUT_TOKENS", "OPENAI_MAX_OUTPUT_TOKENS"),
        "timeout": _first_env("RECRUITMENT_API_TIMEOUT", "OPENAI_TIMEOUT"),
        "max_retries": _first_env("RECRUITMENT_API_MAX_RETRIES", "OPENAI_MAX_RETRIES"),
        "base_url": _first_env("OPENAI_BASE_URL", "RECRUITMENT_API_BASE_URL"),
        "organization": _first_env("OPENAI_ORG_ID", "RECRUITMENT_API_ORG"),
        "project": _first_env("OPENAI_PROJECT", "RECRUITMENT_API_PROJECT"),
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
        hint_path = ROOT_ENV_PATH if ROOT_ENV_PATH.exists() else CONFIG_ENV_PATH
        try:
            hint = hint_path.relative_to(PROJECT_ROOT)
        except Exception:
            hint = hint_path
        raise ValueError(
            f"Missing API key. Put OPENAI_API_KEY in {hint} or export it in your environment."
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
    raw = resp.output_text
    try:
        return json.loads(raw)
    except Exception as ex:
        Path(raw_fallback_name).write_text(raw or "", encoding="utf-8")
        raise ValueError(f"Model returned non-JSON text. Saved to {raw_fallback_name}") from ex

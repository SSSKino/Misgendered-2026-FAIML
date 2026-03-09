from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "api_settings.json"
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_PATH = CONFIG_DIR / ".env"
ENV_EXAMPLE_PATH = CONFIG_DIR / ".env.example"

# Load project-level environment variables once, with OS env taking precedence.
load_dotenv(ENV_PATH, override=False)

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

    if SETTINGS_PATH.exists():
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"api_settings.json must contain a JSON object: {SETTINGS_PATH}")
        settings.update(loaded)

    env_overrides = {
        "model": os.getenv("RECRUITMENT_API_MODEL"),
        "temperature": os.getenv("RECRUITMENT_API_TEMPERATURE"),
        "max_output_tokens": os.getenv("RECRUITMENT_API_MAX_OUTPUT_TOKENS"),
        "timeout": os.getenv("RECRUITMENT_API_TIMEOUT"),
        "max_retries": os.getenv("RECRUITMENT_API_MAX_RETRIES"),
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
            f"Missing API key. Put OPENAI_API_KEY in {ENV_PATH.relative_to(PROJECT_ROOT)} or export it in your environment."
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
) -> tuple:
    """Returns (parsed_json, usage_metadata).

    usage_metadata is a dict with keys:
      model, prompt_tokens, completion_tokens, total_tokens, elapsed_seconds
    """
    import time as _time

    settings = load_api_settings()
    chosen_model = model or str(settings["model"])
    chosen_temperature = float(settings["temperature"] if temperature is None else temperature)

    client = build_client()

    # Build the user message: instructions + JSON schema hint + payload
    schema_hint = json.dumps(output_schema, ensure_ascii=False, indent=2)
    user_content = (
        f"{instructions}\n\n"
        f"Your output MUST be a single valid JSON object conforming to this schema:\n"
        f"```json\n{schema_hint}\n```\n\n"
        f"Input data:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    request_kwargs: Dict[str, Any] = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Always respond with valid JSON only, no markdown fences, no extra text."},
            {"role": "user", "content": user_content},
        ],
        "temperature": chosen_temperature,
    }
    if settings.get("max_output_tokens") is not None:
        request_kwargs["max_tokens"] = settings["max_output_tokens"]

    t0 = _time.time()
    resp = client.chat.completions.create(**request_kwargs)
    elapsed = round(_time.time() - t0, 2)
    raw = resp.choices[0].message.content

    # Extract token usage from response
    usage = getattr(resp, "usage", None)
    usage_meta: Dict[str, Any] = {
        "model": chosen_model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
        "elapsed_seconds": elapsed,
    }

    # Strip markdown fences if the model wraps output in ```json ... ```
    if raw and raw.strip().startswith("```"):
        lines = raw.strip().split("\n")
        # remove first and last fence lines
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        return json.loads(raw), usage_meta
    except Exception as ex:
        Path(raw_fallback_name).write_text(raw or "", encoding="utf-8")
        raise ValueError(f"Model returned non-JSON text. Saved to {raw_fallback_name}") from ex

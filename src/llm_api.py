from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

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


def build_client() -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as ex:
        raise ModuleNotFoundError(
            "Missing dependency 'openai'. Install project dependencies with 'pip install -r requirements.txt'."
        ) from ex

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


def _schema_prompt(instructions: str, schema_name: str, schema_description: str, output_schema: Dict[str, Any]) -> str:
    return (
        f"{instructions}\n\n"
        f"Return exactly one JSON object for '{schema_name}'. {schema_description}. "
        "Do not include markdown fences or any extra text. "
        "Follow this JSON Schema strictly:\n"
        f"{json.dumps(output_schema, ensure_ascii=False)}"
    )


def _extract_chat_text(resp: Any) -> str:
    try:
        content = resp.choices[0].message.content
    except Exception as ex:
        raise ValueError("Chat completion response does not contain message content.") from ex

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _should_skip_responses_api(chosen_model: str, settings: Dict[str, Any]) -> bool:
    """Return True for providers/models that are known to break on Responses API structured output.

    Many OpenAI-compatible gateways (especially DashScope/Qwen compatibility layers) reject
    the Responses API request shape with provider-side validation errors such as
    "[] is too short - 'tools'" even when the client code never explicitly sends tools.
    """
    model_l = (chosen_model or "").lower()
    base_url_l = str(settings.get("base_url") or "").lower()

    incompatible_keywords = (
        "qwen",
        "dashscope",
        "tongyi",
        "alibabacloud",
    )

    return any(k in model_l or k in base_url_l for k in incompatible_keywords)


def _try_responses_api(
    *,
    client: Any,
    chosen_model: str,
    chosen_temperature: float,
    payload: Any,
    instructions: str,
    schema_name: str,
    schema_description: str,
    output_schema: Dict[str, Any],
    settings: Dict[str, Any],
) -> str:
    request_kwargs: Dict[str, Any] = {
        "model": chosen_model,
        "instructions": _schema_prompt(instructions, schema_name, schema_description, output_schema),
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
    return resp.output_text


def _try_chat_completions_api(
    *,
    client: Any,
    chosen_model: str,
    chosen_temperature: float,
    payload: Any,
    instructions: str,
    schema_name: str,
    schema_description: str,
    output_schema: Dict[str, Any],
    settings: Dict[str, Any],
    use_json_mode: bool,
) -> str:
    system_prompt = _schema_prompt(instructions, schema_name, schema_description, output_schema)
    user_prompt = json.dumps(payload, ensure_ascii=False)

    request_kwargs: Dict[str, Any] = {
        "model": chosen_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": chosen_temperature,
    }
    if settings.get("max_output_tokens") is not None:
        request_kwargs["max_tokens"] = settings["max_output_tokens"]
    if use_json_mode:
        request_kwargs["response_format"] = {"type": "json_object"}

    resp = client.chat.completions.create(**request_kwargs)
    return _extract_chat_text(resp)


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
    raw = None
    errors = []

    skip_responses_api = _should_skip_responses_api(chosen_model, settings)

    # Preferred path for OpenAI-native models: Responses API with JSON schema.
    # For Qwen / DashScope-style compatibility endpoints, skip this entirely because
    # they often reject the request shape before any fallback can help.
    if skip_responses_api:
        errors.append(
            f"responses_api_skipped_for_provider: model={chosen_model}, base_url={settings.get('base_url')}"
        )
    else:
        try:
            raw = _try_responses_api(
                client=client,
                chosen_model=chosen_model,
                chosen_temperature=chosen_temperature,
                payload=payload,
                instructions=instructions,
                schema_name=schema_name,
                schema_description=schema_description,
                output_schema=output_schema,
                settings=settings,
            )
        except Exception as ex:
            errors.append(f"responses_api_failed: {ex}")

    # Compatibility fallback: Chat Completions JSON mode (works better for many OpenAI-compatible providers).
    if raw is None:
        try:
            raw = _try_chat_completions_api(
                client=client,
                chosen_model=chosen_model,
                chosen_temperature=chosen_temperature,
                payload=payload,
                instructions=instructions,
                schema_name=schema_name,
                schema_description=schema_description,
                output_schema=output_schema,
                settings=settings,
                use_json_mode=True,
            )
        except Exception as ex:
            errors.append(f"chat_json_mode_failed: {ex}")

    # Last fallback: plain chat completion, still asking for strict JSON in the prompt.
    if raw is None:
        try:
            raw = _try_chat_completions_api(
                client=client,
                chosen_model=chosen_model,
                chosen_temperature=chosen_temperature,
                payload=payload,
                instructions=instructions,
                schema_name=schema_name,
                schema_description=schema_description,
                output_schema=output_schema,
                settings=settings,
                use_json_mode=False,
            )
        except Exception as ex:
            errors.append(f"chat_plain_failed: {ex}")

    if raw is None:
        raise RuntimeError("All API call strategies failed. " + " | ".join(errors))

    try:
        return json.loads(raw)
    except Exception:
        cleaned = (raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start:end+1]
            try:
                return json.loads(candidate)
            except Exception:
                pass
        Path(raw_fallback_name).write_text(raw or "", encoding="utf-8")
        detail = " | ".join(errors) if errors else "json_parse_failed"
        raise ValueError(
            f"Model returned non-JSON text. Saved to {raw_fallback_name}. Previous call details: {detail}"
        )

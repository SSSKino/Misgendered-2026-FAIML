from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Set


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def resolve_path_with_fallback(p: str) -> Path:
    """Resolve paths robustly for project-root and src-relative invocation."""
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


def normalize_cv_records(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        if "CV" in raw:
            raw = raw["CV"]
        elif "candidates" in raw:
            raw = raw["candidates"]
    if not isinstance(raw, list):
        raise ValueError("CV JSON must be an array, or an object with key 'CV'/'candidates' as an array.")
    return [x for x in raw if isinstance(x, dict)]


def extract_profile_ids(records: List[Dict[str, Any]]) -> Set[str]:
    ids: Set[str] = set()
    for rec in records:
        if "candidate_id" in rec:
            ids.add(str(rec["candidate_id"]))
        elif "id" in rec:
            ids.add(str(rec["id"]))
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
    if abs(v - round(v)) < 1e-9:
        return int(round(v))
    return round(v, 1)

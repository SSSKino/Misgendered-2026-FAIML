from __future__ import annotations

import json
import math
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

VALID_GENDERS = {"male", "female", "non-binary"}


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
    return Path(__file__).resolve().parent.parent / path


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_scores_array(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict) and "candidates" in raw:
        raw = raw["candidates"]
    if not isinstance(raw, list):
        raise ValueError("scores must be an array or an object with key 'candidates' as an array.")
    return [x for x in raw if isinstance(x, dict)]


def extract_gender_array(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        if "gender" in raw:
            raw = raw["gender"]
        elif "pronouns" in raw:
            raw = raw["pronouns"]
    if not isinstance(raw, list):
        raise ValueError("gender/pronouns data must be an array (or object with key 'gender'/'pronouns').")
    return [x for x in raw if isinstance(x, dict)]


def to_id_str(v: Any) -> str:
    return str(v)


def round1_half_up(v: float) -> float:
    d = Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def mean(xs: List[float]) -> float:
    return sum(xs) / len(xs)


def median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def sample_sd(xs: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def group_stats(scores: List[float]) -> Dict[str, Any]:
    if len(scores) == 0:
        return {"count": None, "mean": None, "sd": None, "median": None}
    m = round1_half_up(mean(scores))
    med = round1_half_up(median(scores))
    sdv = sample_sd(scores)
    sd_out = None if sdv is None else round1_half_up(sdv)
    return {"count": len(scores), "mean": m, "sd": sd_out, "median": med}


def delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round1_half_up(a - b)


def build_map_with_dupe_check(arr: List[Dict[str, Any]], key_field: str, strict: bool, label: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    seen: Dict[str, int] = {}
    for rec in arr:
        if key_field not in rec:
            continue
        k = to_id_str(rec[key_field])
        if k in out:
            if strict:
                raise ValueError(f"Duplicate id detected in {label}: {k}")
            seen[k] = seen.get(k, 1) + 1
        out[k] = rec
    if not strict and seen:
        examples = sorted(seen.items(), key=lambda x: -x[1])[:20]
        eprint(f"[warn] Duplicate ids in {label} (kept last record): {examples}")
    return out


def normalize_gender_value(rec: Dict[str, Any]) -> str:
    gen = str(rec.get("gender", "")).strip()
    if not gen and "pronouns" in rec:
        gen = str(rec.get("pronouns", "")).strip().lower()
        mapping = {
            "he/him": "male",
            "she/her": "female",
            "they/them": "non-binary",
            "he": "male",
            "she": "female",
            "they": "non-binary",
            "nonbinary": "non-binary",
        }
        gen = mapping.get(gen, gen)
    gen = gen.lower()
    if gen == "nonbinary":
        gen = "non-binary"
    return gen


def analyze_scores(scores_arr: List[Dict[str, Any]], group_arr: List[Dict[str, Any]], strict: bool) -> Dict[str, Any]:
    smap = build_map_with_dupe_check(scores_arr, "id", strict, "scores")
    gmap = build_map_with_dupe_check(group_arr, "id", strict, "group data")

    merged: List[Tuple[str, float, str]] = []
    for cid, s in smap.items():
        g = gmap.get(cid)
        if g is None or "score" not in s:
            continue
        try:
            score = float(s["score"])
        except Exception:
            continue
        gen = normalize_gender_value(g)
        if gen not in VALID_GENDERS:
            if strict:
                raise ValueError(f"Invalid gender/pronouns value for id={cid}: {gen}")
            eprint(f"[warn] Invalid gender/pronouns value ignored for id={cid}: {gen}")
            continue
        merged.append((cid, score, gen))

    male_scores: List[float] = []
    female_scores: List[float] = []
    nb_scores: List[float] = []
    for _, score, gen in merged:
        if gen == "male":
            male_scores.append(score)
        elif gen == "female":
            female_scores.append(score)
        else:
            nb_scores.append(score)

    male_stat = group_stats(male_scores)
    female_stat = group_stats(female_scores)
    nb_stat = group_stats(nb_scores)

    return {
        "male": male_stat,
        "female": female_stat,
        "non-binary": nb_stat,
        "deltas": {
            "delta_M_F": delta(male_stat["mean"], female_stat["mean"]),
            "delta_M_NB": delta(male_stat["mean"], nb_stat["mean"]),
            "delta_F_NB": delta(female_stat["mean"], nb_stat["mean"]),
        },
    }

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VALID_GENDERS = {"male", "female", "they", "thon"}
ID_SUFFIX_RE = re.compile(r"_(A|B|C)$", re.IGNORECASE)


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


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def to_id_str(v: Any) -> str:
    return str(v)


def canonical_candidate_id(v: Any) -> str:
    cid = to_id_str(v).strip()
    return ID_SUFFIX_RE.sub("", cid)


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
        return {"count": 0, "mean": None, "sd": None, "median": None}
    m = round1_half_up(mean(scores))
    med = round1_half_up(median(scores))
    sdv = sample_sd(scores)
    sd_out = None if sdv is None else round1_half_up(sdv)
    return {"count": len(scores), "mean": m, "sd": sd_out, "median": med}


def delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round1_half_up(a - b)


def extract_gender_array(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        if "gender" in raw:
            raw = raw["gender"]
        elif "pronouns" in raw:
            raw = raw["pronouns"]
    if not isinstance(raw, list):
        raise ValueError("gender/pronouns data must be an array or an object with key 'gender'/'pronouns'.")
    return [x for x in raw if isinstance(x, dict)]


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def normalize_gender_value(rec: Dict[str, Any]) -> str:
    mapping = {
        "he/him": "male",
        "she/her": "female",
        "they/them": "they",
        "thon/thon": "thon",
        "he": "male",
        "she": "female",
        "they": "they",
        "thon": "thon",
        "male": "male",
        "female": "female",
        "m": "male",
        "f": "female",
    }

    gender_raw = str(rec.get("gender", "") or "").strip().lower()
    pronouns_raw = str(rec.get("pronouns", "") or "").strip().lower()

    for raw in (gender_raw, pronouns_raw):
        if not raw:
            continue
        key = raw.replace("_", "-").replace(" ", "-")
        key = key.replace("/", "/")
        norm = mapping.get(key)
        if norm in VALID_GENDERS:
            return norm

    return ""


def _normalize_direct_score_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cid = rec.get("candidate_id", rec.get("id"))
    if cid is None:
        return None
    score = rec.get("total_score", rec.get("score"))
    score_v = _safe_float(score)
    if score_v is None:
        return None
    return {
        "candidate_id": to_id_str(cid),
        "base_candidate_id": canonical_candidate_id(cid),
        "score": score_v,
    }


def _normalize_candidate_result(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cid = rec.get("candidate_id", rec.get("id"))
    if cid is None:
        return None

    if isinstance(rec.get("evaluations"), list):
        vals: List[float] = []
        for ev in rec["evaluations"]:
            if not isinstance(ev, dict):
                continue
            result_obj = ev.get("result") if isinstance(ev.get("result"), dict) else ev
            score_v = _safe_float(result_obj.get("total_score", result_obj.get("score")))
            if score_v is not None:
                vals.append(score_v)
        if vals:
            return {
                "candidate_id": to_id_str(cid),
                "base_candidate_id": canonical_candidate_id(cid),
                "score": round1_half_up(mean(vals)),
            }

    return _normalize_direct_score_record(rec)


def _iter_score_records_from_summary(summary_obj: Dict[str, Any], base_dir: Path) -> Iterable[Dict[str, Any]]:
    candidates = summary_obj.get("candidates")
    if not isinstance(candidates, list):
        return []

    out: List[Dict[str, Any]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        candidate_result_file = cand.get("candidate_result_file")
        if candidate_result_file:
            result_path = base_dir / str(candidate_result_file)
            if result_path.exists():
                obj = load_json(result_path)
                norm = _normalize_candidate_result(obj)
                if norm is not None:
                    out.append(norm)
                continue
        norm = _normalize_candidate_result(cand)
        if norm is not None:
            out.append(norm)
    return out


def extract_score_records_from_source(raw: Any, source_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            norm = _normalize_candidate_result(item)
            if norm is not None:
                out.append(norm)
        return out

    if not isinstance(raw, dict):
        raise ValueError("scores must be a JSON object, JSON array, or a directory of candidate result files.")

    if isinstance(raw.get("candidates"), list):
        if source_path is None:
            raise ValueError("summary JSON requires a source path to resolve candidate_result_file entries")
        return list(_iter_score_records_from_summary(raw, source_path.parent))

    norm = _normalize_candidate_result(raw)
    if norm is not None:
        return [norm]

    raise ValueError("Unsupported scores JSON structure for gender analysis.")


def extract_score_records_from_path(scores_path: Path) -> List[Dict[str, Any]]:
    if scores_path.is_dir():
        out: List[Dict[str, Any]] = []
        for p in sorted(scores_path.glob("*.json"), key=lambda x: x.name.lower()):
            obj = load_json(p)
            norm = _normalize_candidate_result(obj)
            if norm is not None:
                out.append(norm)
        if not out:
            raise ValueError(f"No candidate result JSON files found in directory: {scores_path}")
        return out

    raw = load_json(scores_path)
    return extract_score_records_from_source(raw, scores_path)


def _base_gender_map(group_arr: List[Dict[str, Any]], strict: bool) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    out: Dict[str, str] = {}
    sources: Dict[str, List[str]] = {}
    conflicts: Dict[str, set] = {}

    def _priority(rec: Dict[str, Any]) -> Tuple[int, int]:
        cid = str(rec.get("candidate_id", rec.get("id", "")))
        suffix_priority = 1 if cid.upper().endswith("_C") else 0
        explicit_gender = 1 if str(rec.get("gender", "") or "").strip() else 0
        return (suffix_priority, explicit_gender)

    sorted_records = sorted(group_arr, key=_priority, reverse=True)

    for rec in sorted_records:
        cid = rec.get("candidate_id", rec.get("id"))
        if cid is None:
            continue
        base_id = canonical_candidate_id(cid)
        gen = normalize_gender_value(rec)
        if not gen:
            continue
        if gen not in VALID_GENDERS:
            if strict:
                raise ValueError(f"Invalid gender/pronouns value for candidate_id={cid}: {gen}")
            eprint(f"[warn] Invalid gender/pronouns value ignored for candidate_id={cid}: {gen}")
            continue

        sources.setdefault(base_id, []).append(to_id_str(cid))
        if base_id in out and out[base_id] != gen:
            conflicts.setdefault(base_id, set()).update({out[base_id], gen})
            if strict:
                raise ValueError(f"Conflicting gender values for base candidate {base_id}: {sorted(conflicts[base_id])}")
            continue
        out.setdefault(base_id, gen)

    if conflicts:
        examples = {k: sorted(v) for k, v in list(conflicts.items())[:20]}
        eprint(f"[warn] Conflicting gender labels detected; kept preferred value for {len(conflicts)} base candidates: {examples}")

    return out, sources


def analyze_scores(scores_arr: List[Dict[str, Any]], group_arr: List[Dict[str, Any]], strict: bool) -> Dict[str, Any]:
    gender_map, group_sources = _base_gender_map(group_arr, strict)

    matched: List[Tuple[str, str, float, str]] = []
    unmatched_score_ids: List[str] = []

    for rec in scores_arr:
        candidate_id = rec.get("candidate_id", rec.get("id"))
        if candidate_id is None:
            continue
        base_id = rec.get("base_candidate_id") or canonical_candidate_id(candidate_id)
        score = _safe_float(rec.get("score", rec.get("total_score")))
        if score is None:
            continue
        gen = gender_map.get(base_id)
        if not gen:
            unmatched_score_ids.append(to_id_str(candidate_id))
            continue
        matched.append((to_id_str(candidate_id), to_id_str(base_id), score, gen))

    buckets: Dict[str, List[float]] = {g: [] for g in sorted(VALID_GENDERS)}
    for _, _, score, gen in matched:
        buckets[gen].append(score)

    male_stat = group_stats(buckets["male"])
    female_stat = group_stats(buckets["female"])
    they_stat = group_stats(buckets["they"])
    thon_stat = group_stats(buckets["thon"])

    out: Dict[str, Any] = {
        "matched_candidate_count": len(matched),
        "matching_key_basis": "base_candidate_id (candidate_id stripped of trailing _A/_B/_C)",
        "male": male_stat,
        "female": female_stat,
        "they": they_stat,
        "thon": thon_stat,
        "deltas": {
            "delta_male_female": delta(male_stat["mean"], female_stat["mean"]),
            "delta_male_they": delta(male_stat["mean"], they_stat["mean"]),
            "delta_male_thon": delta(male_stat["mean"], thon_stat["mean"]),
            "delta_female_they": delta(female_stat["mean"], they_stat["mean"]),
            "delta_female_thon": delta(female_stat["mean"], thon_stat["mean"]),
            "delta_they_thon": delta(they_stat["mean"], thon_stat["mean"]),
        },
        "matched_base_candidate_counts": {
            "male": len({base for _, base, _, gen in matched if gen == "male"}),
            "female": len({base for _, base, _, gen in matched if gen == "female"}),
            "they": len({base for _, base, _, gen in matched if gen == "they"}),
            "thon": len({base for _, base, _, gen in matched if gen == "thon"}),
        },
    }
    if unmatched_score_ids:
        out["unmatched_score_count"] = len(unmatched_score_ids)
        out["unmatched_score_examples"] = sorted(unmatched_score_ids)[:20]
    return out


def analyze_from_paths(scores_path: Path, group_path: Path, strict: bool) -> Dict[str, Any]:
    scores_raw = extract_score_records_from_path(scores_path)
    group_raw = extract_gender_array(load_json(group_path))
    result = analyze_scores(scores_raw, group_raw, strict)
    result["scores_source"] = str(scores_path)
    result["group_source"] = str(group_path)
    return result


def run_cli(default_out: str, experiment_name: str) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scores", help="Path to industry summary JSON, candidates_result directory, or score JSON")
    ap.add_argument("group_data", help="Path to gender/pronouns JSON")
    ap.add_argument("--out", default=default_out, help=f"Output file (default: {default_out})")
    ap.add_argument("--strict", action="store_true", help="Fail on conflicting group labels")
    args = ap.parse_args()

    scores_path = resolve_path_with_fallback(args.scores)
    group_path = resolve_path_with_fallback(args.group_data)
    out_path = resolve_path_with_fallback(args.out)

    out = analyze_from_paths(scores_path, group_path, args.strict)
    out["experiment"] = experiment_name

    # Try to enrich with industry/variant when source is summary JSON.
    try:
        raw = load_json(scores_path) if scores_path.is_file() else None
        if isinstance(raw, dict):
            if "industry" in raw:
                out["industry"] = raw["industry"]
            if "variant" in raw:
                out["variant"] = raw["variant"]
    except Exception:
        pass

    write_json(out_path, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))

#!/usr/bin/env python3
# split_and_build_pronouns.py
"""
ONE-STOP script (combine split + pronouns export).

Fixed defaults (no args needed):
- Input file: 简历(1).json (must be in the SAME folder as this script; typically rawdata/)
- Output root: ../candidates (folder sibling to rawdata)

What it does:
1) Split candidates by `industry_target` into industry folders under ../candidates/
2) For each industry, write 3 "cue" variants (each file contains ALL candidates for that industry):
   - <industry>_no_pronouns_gender.json  (remove pronouns + gender)
   - <industry>_no_gender.json           (keep/add pronouns, remove gender)
   - <industry>_full.json                (keep/add pronouns + gender)
   Optionally: <industry>_all_variants.json if --combined is provided.
3) Build a deduplicated pronouns file under: ../candidates/pronouns/pronouns.json
   - Dedup key: base_id = candidate_id with trailing _A/_B/_C removed (if present)
   - Keep LAST valid pronouns per base_id
   - Output array sorted by id

Also writes:
- ../candidates/split_manifest.json (NO per-file full paths; only split summary + filenames + anomalies + pronouns export stats)

Usage:
python split_and_build_pronouns.py
python split_and_build_pronouns.py --combined
"""

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# -------- split helpers --------
PRONOUN_RE = re.compile(r"\b(he/him|she/her|they/them)\b", re.IGNORECASE)
DISCLOSE_RE = re.compile(
    r"\s*(?:\.\s*)?(?:My\s+prefer\s+pronoun(?:ce)?\s+is\s+(he/him|she/her|they/them)\.?)\s*",
    re.IGNORECASE,
)

VALID_PRONOUNS = {"he/him", "she/her", "they/them"}
SUFFIX_RE = re.compile(r"^(.*)_([ABC])$")


def load_candidates(path: Path) -> List[Dict[str, Any]]:
    # utf-8-sig to tolerate BOM
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        arr = data["candidates"]
    elif isinstance(data, list):
        arr = data
    else:
        raise ValueError("Input must be a JSON array or an object with key 'candidates' as an array.")
    return [x for x in arr if isinstance(x, dict)]


def safe_slug(s: str) -> str:
    s = str(s or "").strip()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s) or "unknown"


def base_id_and_variant(candidate_id: str) -> Tuple[str, Optional[str]]:
    m = SUFFIX_RE.match(candidate_id)
    if m:
        return m.group(1), m.group(2)
    return candidate_id, None


def base_id(candidate_id: str) -> str:
    return base_id_and_variant(candidate_id)[0]


def has_pronouns(rec: Dict[str, Any]) -> bool:
    if "pronouns" in rec and isinstance(rec["pronouns"], str) and rec["pronouns"].strip():
        return True
    summary = str(rec.get("summary", ""))
    return PRONOUN_RE.search(summary) is not None


def extract_pronouns_from_summary(summary: str) -> Optional[str]:
    m = PRONOUN_RE.search(summary or "")
    return m.group(1).lower() if m else None


def scrub_pronoun_disclosure(summary: str) -> str:
    return DISCLOSE_RE.sub(" ", summary or "").strip()


def infer_gender_from_pronouns(pronouns: Optional[str]) -> Optional[str]:
    if not pronouns:
        return None
    p = pronouns.lower()
    if p == "he/him":
        return "male"
    if p == "she/her":
        return "female"
    if p == "they/them":
        return "non-binary"
    return None


def pick_record(variants: List[Dict[str, Any]], prefer_letter: Optional[str], predicate) -> Dict[str, Any]:
    """
    Choose one record from variants.
    Priority:
    1) If prefer_letter is provided, pick the last record with candidate_id ending in _A/_B/_C
    2) Else, pick the last record matching predicate
    3) Else, pick the last record
    """
    if prefer_letter:
        preferred = [v for v in variants if str(v.get("candidate_id", "")).endswith(f"_{prefer_letter}")]
        if preferred:
            return preferred[-1]  # keep last occurrence
    matches = [v for v in variants if predicate(v)]
    if matches:
        return matches[-1]
    return variants[-1]


def make_variant_record(rec: Dict[str, Any], base_candidate_id: str, mode: str) -> Dict[str, Any]:
    out = copy.deepcopy(rec)
    out["candidate_id"] = base_candidate_id  # normalize id across A/B/C

    if mode == "no_pronouns_gender":
        out.pop("pronouns", None)
        out.pop("gender", None)
        if isinstance(out.get("summary"), str):
            out["summary"] = scrub_pronoun_disclosure(out["summary"])
        return out

    if mode == "no_gender":
        out.pop("gender", None)
        # Keep / add pronouns
        if not isinstance(out.get("pronouns"), str) or not out.get("pronouns", "").strip():
            pr = extract_pronouns_from_summary(str(out.get("summary", "")))
            if pr:
                out["pronouns"] = pr
                if isinstance(out.get("summary"), str):
                    out["summary"] = scrub_pronoun_disclosure(out["summary"])
        return out

    if mode == "full":
        # Ensure pronouns
        pr = None
        if isinstance(out.get("pronouns"), str) and out["pronouns"].strip():
            pr = out["pronouns"].strip().lower()
        else:
            pr = extract_pronouns_from_summary(str(out.get("summary", "")))
            if pr:
                out["pronouns"] = pr
                if isinstance(out.get("summary"), str):
                    out["summary"] = scrub_pronoun_disclosure(out["summary"])
        # Ensure gender
        if not isinstance(out.get("gender"), str) or not out.get("gender", "").strip():
            g = infer_gender_from_pronouns(pr)
            if g:
                out["gender"] = g
        return out

    raise ValueError(f"Unknown mode: {mode}")


# -------- pronouns export helpers --------
def normalize_pronouns(value: Any, summary: Any = None) -> Optional[str]:
    if isinstance(value, str):
        s = value.strip().lower()
        s = re.sub(r"\s+", "", s)
        mapping = {
            "he/him": "he/him",
            "she/her": "she/her",
            "they/them": "they/them",
            "hehim": "he/him",
            "sheher": "she/her",
            "theythem": "they/them",
        }
        if s in mapping:
            return mapping[s]
    if isinstance(summary, str):
        extracted = extract_pronouns_from_summary(summary)
        if extracted in VALID_PRONOUNS:
            return extracted
    return None



def build_pronouns(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    seen: Dict[str, str] = {}
    stats = {"dupes": 0, "missing_id": 0, "missing_pronouns": 0, "invalid_pronouns": 0}

    for rec in rows:
        cid = rec.get("candidate_id", rec.get("id"))
        if cid is None:
            stats["missing_id"] += 1
            continue
        bid = base_id(str(cid))

        np = normalize_pronouns(rec.get("pronouns"), rec.get("summary"))
        if np is None:
            if rec.get("pronouns") is None and not extract_pronouns_from_summary(str(rec.get("summary", ""))):
                stats["missing_pronouns"] += 1
            else:
                stats["invalid_pronouns"] += 1
            continue

        if bid in seen:
            stats["dupes"] += 1
        seen[bid] = np  # keep last valid

    out: List[Dict[str, str]] = [{"id": k, "pronouns": v} for k, v in seen.items()]
    out.sort(key=lambda x: x["id"])
    stats["unique"] = len(out)
    return out, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combined", action="store_true",
                    help="Also write a combined per-industry file containing all 3 variants.")
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent
    inp = base_dir / "简历(1).json"
    out_root = (base_dir / ".." / "candidates").resolve()

    out_root.mkdir(parents=True, exist_ok=True)

    rows = load_candidates(inp)

    # ------------- Split by industry_target -------------
    by_industry: Dict[str, List[Dict[str, Any]]] = {}
    for rec in rows:
        industry = str(rec.get("industry_target", "unknown"))
        by_industry.setdefault(industry, []).append(rec)

    manifest: Dict[str, Any] = {
        "input_file": "简历(1).json",
        "output_root": "../candidates",
        "industries": {},
        "pronouns_export": {},
        "notes": [],
    }

    for industry, recs in by_industry.items():
        slug = safe_slug(industry)
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

        # Group by base_id (align A/B/C)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in recs:
            cid = str(r.get("candidate_id", "")).strip()
            if not cid:
                continue
            grouped.setdefault(base_id(cid), []).append(r)

        no_pg: List[Dict[str, Any]] = []
        no_g: List[Dict[str, Any]] = []
        full: List[Dict[str, Any]] = []
        anomalies: List[str] = []

        for bid, vars_ in grouped.items():
            rA = pick_record(vars_, "A", lambda x: (not has_pronouns(x)) and ("gender" not in x))
            rB = pick_record(vars_, "B", lambda x: has_pronouns(x) and ("gender" not in x))
            rC = pick_record(vars_, "C", lambda x: has_pronouns(x) and ("gender" in x))

            no_pg.append(make_variant_record(rA, bid, "no_pronouns_gender"))
            no_g.append(make_variant_record(rB, bid, "no_gender"))
            full.append(make_variant_record(rC, bid, "full"))

            if "pronouns" not in full[-1]:
                anomalies.append(f"{industry}:{bid}: full variant missing pronouns after normalization")

        # Deterministic order
        no_pg.sort(key=lambda x: str(x.get("candidate_id", "")))
        no_g.sort(key=lambda x: str(x.get("candidate_id", "")))
        full.sort(key=lambda x: str(x.get("candidate_id", "")))

        # Write split files
        f_no_pg_name = f"{slug}_no_pronouns_gender.json"
        f_no_g_name = f"{slug}_no_gender.json"
        f_full_name = f"{slug}_full.json"

        (ind_dir / f_no_pg_name).write_text(json.dumps(no_pg, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_no_g_name).write_text(json.dumps(no_g, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_full_name).write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")

        all_variants_name = None
        if args.combined:
            all_variants_name = f"{slug}_all_variants.json"
            combined = {
                "industry_target": industry,
                "no_pronouns_gender": no_pg,
                "no_gender": no_g,
                "full": full,
            }
            (ind_dir / all_variants_name).write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest["industries"][industry] = {
            "industry_slug": slug,
            "counts": {
                "base_candidates": len(grouped),
                "no_pronouns_gender": len(no_pg),
                "no_gender": len(no_g),
                "full": len(full),
            },
            "outputs": {
                "no_pronouns_gender_file": f_no_pg_name,
                "no_gender_file": f_no_g_name,
                "full_file": f_full_name,
                "all_variants_file": all_variants_name,
            },
            "anomalies": anomalies[:50],
        }

    # ------------- Build pronouns.json under candidates/pronouns/ -------------
    pronouns_list, pronouns_stats = build_pronouns(rows)
    pronouns_dir = out_root / "pronouns"
    pronouns_dir.mkdir(parents=True, exist_ok=True)
    (pronouns_dir / "pronouns.json").write_text(json.dumps(pronouns_list, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest["pronouns_export"] = {
        "output_folder": "pronouns/",
        "output_file": "pronouns.json",
        "stats": pronouns_stats,
    }

    # Write manifest (no full paths)
    (out_root / "split_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file runner for:
1) CV splitting by industry + cue variants + pronouns/gender exports
2) JD splitting by industries into a separate fixed relative output path
3) Shared canonical industry directory naming across CV and JD

Fixed project-relative paths:
- CV input:  data/inputs/rawdata/CV.json
- CV output: data/inputs/CV/
- JD input:  data/inputs/rawdata/JD.json
- JD output: data/inputs/JD/

Behavior (no CLI args needed):
- Always auto-detect the project root by walking upward from the script location.
- Always process CV and write outputs under data/inputs/CV/
- Always process JD and write outputs under data/inputs/JD/
- CV and JD always use the same canonical industry directory names.
- Only relative paths are used inside the code.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REL_RAWDATA_DIR = Path("data") / "inputs" / "rawdata"
REL_CV_INPUT_PATH = REL_RAWDATA_DIR / "CV.json"
REL_CV_OUTPUT_ROOT = Path("data") / "inputs" / "CV"
REL_JD_INPUT_PATH = REL_RAWDATA_DIR / "JD.json"
REL_JD_OUTPUT_ROOT = Path("data") / "inputs" / "JD"

PRONOUN_RE = re.compile(r"\b(he/him|she/her|they/them)\b", re.IGNORECASE)
DISCLOSE_RE = re.compile(
    r"\s*(?:\.\s*)?(?:My\s+prefer\s+pronoun(?:ce)?\s+is\s+(he/him|she/her|they/them)\.?)\s*",
    re.IGNORECASE,
)
VALID_PRONOUNS = {"he/him", "she/her", "they/them"}
VALID_GENDERS = {"male", "female", "non-binary"}
SUFFIX_RE = re.compile(r"^(.*)_([ABC])$")

# Shared canonical industry mapping so CV and JD land in the same folder names.
CANONICAL_INDUSTRY_MAP: Dict[str, str] = {
    "it": "IT",
    "i.t": "IT",
    "tech": "IT",
    "technology": "IT",
    "information technology": "IT",
    "information_technology": "IT",
    "software": "IT",
    "software engineering": "IT",
    "software engineer": "IT",
    "construction": "Construction",
    "building": "Construction",
    "construction trades": "Construction",
    "nursing": "Nursing",
    "nurse": "Nursing",
    "registered nurse": "Nursing",
    "rn": "Nursing",
    "healthcare": "Nursing",
    "health care": "Nursing",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_candidates(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        arr = data["candidates"]
    elif isinstance(data, list):
        arr = data
    else:
        raise ValueError("CV input must be a JSON array or an object with key 'candidates' as an array.")
    return [x for x in arr if isinstance(x, dict)]


def load_jd(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("JD input must be a JSON object.")
    if not isinstance(data.get("occupations"), dict):
        raise ValueError("JD input must contain an 'occupations' object keyed by industry.")
    if not isinstance(data.get("metadata"), dict):
        data["metadata"] = {}
    return data


def safe_slug(s: str) -> str:
    s = str(s or "").strip()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s) or "unknown"


def normalize_industry_text(value: Any) -> str:
    s = str(value or "").strip().lower()
    s = s.replace("&", " and ")
    s = s.replace("/", " ")
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def canonical_industry_name(value: Any) -> str:
    raw = str(value or "").strip()
    norm = normalize_industry_text(raw)
    if norm in CANONICAL_INDUSTRY_MAP:
        return CANONICAL_INDUSTRY_MAP[norm]
    if not raw:
        return "unknown"
    # Stable fallback: preserve semantic text but normalize spacing/casing.
    cleaned = re.sub(r"\s+", " ", raw).strip()
    if cleaned.upper() in {"IT", "HR", "RN"}:
        return cleaned.upper()
    return " ".join(part.capitalize() for part in cleaned.split(" "))


def industry_dir_name(value: Any) -> str:
    return safe_slug(canonical_industry_name(value))


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


def normalize_gender(g: Any) -> Optional[str]:
    if not isinstance(g, str):
        return None
    s = g.strip().lower()
    s = s.replace("_", "-").replace(" ", "-")
    if s in {"nonbinary", "non-binary", "nb", "n-b"}:
        return "non-binary"
    if s == "m":
        return "male"
    if s == "f":
        return "female"
    return s if s in VALID_GENDERS else None


def pick_record(variants: List[Dict[str, Any]], prefer_letter: Optional[str], predicate) -> Dict[str, Any]:
    if prefer_letter:
        preferred = [v for v in variants if str(v.get("candidate_id", "")).endswith(f"_{prefer_letter}")]
        if preferred:
            return preferred[-1]
    matches = [v for v in variants if predicate(v)]
    if matches:
        return matches[-1]
    return variants[-1]


def make_variant_record(rec: Dict[str, Any], base_candidate_id: str, mode: str) -> Dict[str, Any]:
    out = copy.deepcopy(rec)
    out["candidate_id"] = base_candidate_id

    if mode == "no_pronouns_gender":
        out.pop("pronouns", None)
        out.pop("gender", None)
        if isinstance(out.get("summary"), str):
            out["summary"] = scrub_pronoun_disclosure(out["summary"])
        return out

    if mode == "no_gender":
        out.pop("gender", None)
        if not isinstance(out.get("pronouns"), str) or not out.get("pronouns", "").strip():
            pr = extract_pronouns_from_summary(str(out.get("summary", "")))
            if pr:
                out["pronouns"] = pr
                if isinstance(out.get("summary"), str):
                    out["summary"] = scrub_pronoun_disclosure(out["summary"])
        return out

    if mode == "full":
        pr = None
        if isinstance(out.get("pronouns"), str) and out["pronouns"].strip():
            pr = out["pronouns"].strip().lower()
        else:
            pr = extract_pronouns_from_summary(str(out.get("summary", "")))
            if pr:
                out["pronouns"] = pr
                if isinstance(out.get("summary"), str):
                    out["summary"] = scrub_pronoun_disclosure(out["summary"])
        if not isinstance(out.get("gender"), str) or not out.get("gender", "").strip():
            g = infer_gender_from_pronouns(pr)
            if g:
                out["gender"] = g
        return out

    raise ValueError(f"Unknown mode: {mode}")


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
        seen[bid] = np

    out: List[Dict[str, str]] = [{"id": k, "pronouns": v} for k, v in seen.items()]
    out.sort(key=lambda x: x["id"])
    stats["unique"] = len(out)
    return out, stats


def build_gender(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, int]]:
    seen: Dict[str, str] = {}
    stats = {"dupes": 0, "missing_id": 0, "missing_gender": 0, "invalid_gender": 0}

    for rec in rows:
        cid = rec.get("candidate_id", rec.get("id"))
        if cid is None:
            stats["missing_id"] += 1
            continue
        bid = base_id(str(cid))

        ng = normalize_gender(rec.get("gender"))
        if ng is None:
            if rec.get("gender") is None:
                stats["missing_gender"] += 1
            else:
                stats["invalid_gender"] += 1
            continue

        if bid in seen:
            stats["dupes"] += 1
        seen[bid] = ng

    out: List[Dict[str, str]] = [{"id": k, "gender": v} for k, v in seen.items()]
    out.sort(key=lambda x: x["id"])
    stats["unique"] = len(out)
    return out, stats


def split_cv_and_write(rows: List[Dict[str, Any]], out_root: Path) -> Dict[str, Any]:
    grouped_by_canonical: Dict[str, Dict[str, Any]] = {}

    for rec in rows:
        raw_industry = str(rec.get("industry_target", "unknown"))
        canonical = canonical_industry_name(raw_industry)
        slug = industry_dir_name(raw_industry)
        bucket = grouped_by_canonical.setdefault(
            canonical,
            {"slug": slug, "records": [], "source_industries": set()},
        )
        bucket["records"].append(rec)
        bucket["source_industries"].add(raw_industry)

    manifest_industries: Dict[str, Any] = {}

    for canonical, bucket in grouped_by_canonical.items():
        slug = bucket["slug"]
        recs = bucket["records"]
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

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

            if ("pronouns" not in full[-1]) or ("gender" not in full[-1]):
                anomalies.append(f"{canonical}:{bid}: full variant missing pronouns/gender after normalization")

        no_pg.sort(key=lambda x: str(x.get("candidate_id", "")))
        no_g.sort(key=lambda x: str(x.get("candidate_id", "")))
        full.sort(key=lambda x: str(x.get("candidate_id", "")))

        f_no_pg_name = f"{slug}_no_pronouns_gender.json"
        f_no_g_name = f"{slug}_no_gender.json"
        f_full_name = f"{slug}_full.json"
        all_variants_name = f"{slug}_all_variants.json"

        (ind_dir / f_no_pg_name).write_text(json.dumps(no_pg, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_no_g_name).write_text(json.dumps(no_g, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_full_name).write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")

        combined_payload = {
            "industry_target": canonical,
            "source_industries": sorted(bucket["source_industries"]),
            "no_pronouns_gender": no_pg,
            "no_gender": no_g,
            "full": full,
        }
        (ind_dir / all_variants_name).write_text(
            json.dumps(combined_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        manifest_industries[canonical] = {
            "industry_slug": slug,
            "source_industries": sorted(bucket["source_industries"]),
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

    return manifest_industries


def write_cv_exports(rows: List[Dict[str, Any]], out_root: Path) -> Dict[str, Any]:
    export_info: Dict[str, Any] = {}

    pronouns_list, pronouns_stats = build_pronouns(rows)
    pronouns_dir = out_root / "pronouns"
    pronouns_dir.mkdir(parents=True, exist_ok=True)
    (pronouns_dir / "pronouns.json").write_text(
        json.dumps(pronouns_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_info["pronouns_export"] = {
        "output_folder": "pronouns/",
        "output_file": "pronouns.json",
        "stats": pronouns_stats,
    }

    gender_list, gender_stats = build_gender(rows)
    gender_dir = out_root / "gender"
    gender_dir.mkdir(parents=True, exist_ok=True)
    (gender_dir / "gender.json").write_text(
        json.dumps(gender_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    export_info["gender_export"] = {
        "output_folder": "gender/",
        "output_file": "gender.json",
        "stats": gender_stats,
    }

    return export_info


def split_jd_and_write(jd_data: Dict[str, Any], out_root: Path) -> Dict[str, Any]:
    metadata = jd_data.get("metadata", {})
    occupations = jd_data.get("occupations", {})
    grouped_by_canonical: Dict[str, Dict[str, Any]] = {}

    for raw_industry, jobs in occupations.items():
        canonical = canonical_industry_name(raw_industry)
        slug = industry_dir_name(raw_industry)
        bucket = grouped_by_canonical.setdefault(
            canonical,
            {"slug": slug, "jobs": [], "source_industries": set()},
        )
        if isinstance(jobs, list):
            bucket["jobs"].extend(jobs)
        bucket["source_industries"].add(raw_industry)

    manifest_industries: Dict[str, Any] = {}

    for canonical, bucket in grouped_by_canonical.items():
        slug = bucket["slug"]
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

        output_name = f"{slug}_jd.json"
        payload = {
            "metadata": metadata,
            "industry": canonical,
            "source_industries": sorted(bucket["source_industries"]),
            "occupations": bucket["jobs"],
        }
        (ind_dir / output_name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest_industries[canonical] = {
            "industry_slug": slug,
            "source_industries": sorted(bucket["source_industries"]),
            "occupation_count": len(bucket["jobs"]),
            "output_file": output_name,
        }

    return manifest_industries


def find_project_root(start: Path) -> Path:
    """Walk upward from the script location until the fixed rawdata directory exists."""
    for base in (start, *start.parents):
        if (base / REL_RAWDATA_DIR).exists():
            return base
    raise FileNotFoundError(
        f"Rawdata directory not found via relative path: {REL_RAWDATA_DIR.as_posix()}\n"
        f"Checked from script location upward starting at: {start}"
    )


def ensure_input_exists(path: Path, rel_path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Input file not found: {path}\n"
            f"Please ensure the file exists at project-relative path: {rel_path.as_posix()}"
        )


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_root = find_project_root(script_dir)

    cv_inp = project_root / REL_CV_INPUT_PATH
    jd_inp = project_root / REL_JD_INPUT_PATH
    cv_out_root = project_root / REL_CV_OUTPUT_ROOT
    jd_out_root = project_root / REL_JD_OUTPUT_ROOT

    ensure_input_exists(cv_inp, REL_CV_INPUT_PATH)
    ensure_input_exists(jd_inp, REL_JD_INPUT_PATH)

    cv_out_root.mkdir(parents=True, exist_ok=True)
    jd_out_root.mkdir(parents=True, exist_ok=True)

    cv_rows = load_candidates(cv_inp)
    jd_data = load_jd(jd_inp)

    cv_manifest: Dict[str, Any] = {
        "input_file": REL_CV_INPUT_PATH.as_posix(),
        "output_root": REL_CV_OUTPUT_ROOT.as_posix(),
        "industries": {},
        "notes": [
            "Paths are fixed in code and use project-relative locations.",
            "Project root is auto-detected by walking upward from the script location.",
            "All CV outputs are always generated: variants + combined + pronouns + gender + manifest.",
            "CV and JD share the same canonical industry directory naming logic.",
        ],
    }
    cv_manifest["industries"] = split_cv_and_write(cv_rows, cv_out_root)
    cv_manifest.update(write_cv_exports(cv_rows, cv_out_root))
    (cv_out_root / "split_manifest.json").write_text(
        json.dumps(cv_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    jd_manifest: Dict[str, Any] = {
        "input_file": REL_JD_INPUT_PATH.as_posix(),
        "output_root": REL_JD_OUTPUT_ROOT.as_posix(),
        "metadata": jd_data.get("metadata", {}),
        "industries": split_jd_and_write(jd_data, jd_out_root),
        "notes": [
            "Paths are fixed in code and use project-relative locations.",
            "JD is split by industries under the occupations object.",
            "Each industry output contains metadata + canonical industry name + occupations list.",
            "CV and JD share the same canonical industry directory naming logic.",
        ],
    }
    (jd_out_root / "split_manifest.json").write_text(
        json.dumps(jd_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Project root: {project_root}")
    print(f"Done. CV input: {REL_CV_INPUT_PATH.as_posix()}")
    print(f"Done. CV output root: {REL_CV_OUTPUT_ROOT.as_posix()}")
    print(f"Done. JD input: {REL_JD_INPUT_PATH.as_posix()}")
    print(f"Done. JD output root: {REL_JD_OUTPUT_ROOT.as_posix()}")
    print(f"- CV manifest: {(REL_CV_OUTPUT_ROOT / 'split_manifest.json').as_posix()}")
    print(f"- JD manifest: {(REL_JD_OUTPUT_ROOT / 'split_manifest.json').as_posix()}")


if __name__ == "__main__":
    main()

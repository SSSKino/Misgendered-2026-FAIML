#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal splitter for:
1) CV splitting by industry and variant
2) pronouns / gender export
3) JD splitting by industry and by soc_code

Fixed project-relative paths:
- CV input:  data/inputs/rawdata/CV.json
- JD input:  data/inputs/rawdata/JD.json
- CV output: data/inputs/CV/
- JD output: data/inputs/JD/
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

REL_RAWDATA_DIR = Path("data") / "inputs" / "rawdata"
REL_CV_INPUT_PATH = REL_RAWDATA_DIR / "CV.json"
REL_JD_INPUT_PATH = REL_RAWDATA_DIR / "JD.json"
REL_CV_OUTPUT_ROOT = Path("data") / "inputs" / "CV"
REL_JD_OUTPUT_ROOT = Path("data") / "inputs" / "JD"

INDUSTRY_CANONICAL_MAP = {
    "software & it services": "Software_&_IT_Services",
    "software and it services": "Software_&_IT_Services",
    "software_it_services": "Software_&_IT_Services",
    "software & it": "Software_&_IT_Services",
    "it services": "Software_&_IT_Services",
    "it": "IT",
    "information technology": "IT",
    "construction": "Construction",
    "nursing": "Nursing",
    "registered nurse": "Nursing",
    "consulting": "Consulting",
    "management consulting": "Consulting",
    "hotel": "Hotel",
    "hospitality": "Hotel",
    "accounting": "Accounting",
    "financial accounting": "Accounting",
    "teacher": "Teacher",
    "education": "Teacher",
}

GENDER_KEYS = {"gender"}
PRONOUN_KEYS = {"pronouns", "pronoun", "preferred_pronouns"}
PRONOUN_PATTERNS = [
    r"\b(?:he|she|they|him|her|them|his|hers|their|theirs)\b",
]


def safe_slug(text: Any) -> str:
    s = str(text or "").strip()
    s = re.sub(r"[^\w\-\.]+", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("._")
    return s or "unknown"


def base_id(candidate_id: str) -> str:
    s = str(candidate_id or "").strip()
    return re.sub(r"_[A-Za-z0-9]+$", "", s)


def variant_rank(candidate_id: str) -> int:
    s = str(candidate_id or "").strip()
    suffix = s.rsplit("_", 1)[-1].upper() if "_" in s else ""
    if suffix == "A":
        return 0
    if suffix == "B":
        return 1
    if suffix == "C":
        return 2
    return 99


def canonical_industry_name(raw: Any) -> str:
    s = str(raw or "unknown").strip()
    key = re.sub(r"\s+", " ", s.lower())
    return INDUSTRY_CANONICAL_MAP.get(key, safe_slug(s))


def industry_dir_name(raw: Any) -> str:
    return safe_slug(canonical_industry_name(raw))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_candidates(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = None
        for key in ("CV", "cv", "candidates", "Candidates", "data", "records"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
        if rows is None:
            raise ValueError("CV input must be a list or an object containing a candidate list.")
    else:
        raise ValueError("CV input must be JSON list/object.")
    return [x for x in rows if isinstance(x, dict)]


def load_jd_rows(path: Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    if not isinstance(data, list):
        raise ValueError("JD input must be a JSON list.")
    return [x for x in data if isinstance(x, dict)]


def remove_gender_fields(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(rec)
    for k in list(out.keys()):
        if str(k).lower() in GENDER_KEYS:
            out.pop(k, None)
    return out


def remove_pronouns_and_gender_fields(rec: Dict[str, Any]) -> Dict[str, Any]:
    out = remove_gender_fields(rec)
    for k in list(out.keys()):
        if str(k).lower() in PRONOUN_KEYS:
            out.pop(k, None)
    for k, v in list(out.items()):
        if isinstance(v, str):
            new_v = v
            for pat in PRONOUN_PATTERNS:
                new_v = re.sub(pat, "", new_v, flags=re.IGNORECASE)
            new_v = re.sub(r"\s+", " ", new_v).strip()
            out[k] = new_v
    return out


def build_pronouns(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    vals = []
    for rec in rows:
        pronouns = None
        for key in PRONOUN_KEYS:
            if key in rec:
                pronouns = rec.get(key)
                break
        vals.append({"candidate_id": rec.get("candidate_id"), "pronouns": pronouns})
    return vals


def build_gender(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"candidate_id": rec.get("candidate_id"), "gender": rec.get("gender")} for rec in rows]


def write_candidate_files(records: List[Dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    counter: Dict[str, int] = {}
    for idx, rec in enumerate(records, start=1):
        cid = str(rec.get("candidate_id") or rec.get("id") or f"candidate_{idx:04d}").strip()
        stem = safe_slug(cid)
        counter[stem] = counter.get(stem, 0) + 1
        fname = f"{stem}.json" if counter[stem] == 1 else f"{stem}__dup{counter[stem]:02d}.json"
        (out_dir / fname).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def split_cv_and_write(rows: List[Dict[str, Any]], out_root: Path) -> None:
    grouped_by_industry: Dict[str, List[Dict[str, Any]]] = {}
    for rec in rows:
        raw_industry = rec.get("industry_target", "unknown")
        slug = industry_dir_name(raw_industry)
        grouped_by_industry.setdefault(slug, []).append(rec)

    for slug, recs in grouped_by_industry.items():
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in recs:
            cid = str(r.get("candidate_id", "")).strip()
            if cid:
                grouped.setdefault(base_id(cid), []).append(r)

        no_pg: List[Dict[str, Any]] = []
        no_g: List[Dict[str, Any]] = []
        full: List[Dict[str, Any]] = []

        for vars_ in grouped.values():
            vars_sorted = sorted(vars_, key=lambda x: variant_rank(str(x.get("candidate_id", ""))))
            if len(vars_sorted) >= 1:
                no_pg.append(remove_pronouns_and_gender_fields(vars_sorted[0]))
            if len(vars_sorted) >= 2:
                no_g.append(remove_gender_fields(vars_sorted[1]))
            if len(vars_sorted) >= 3:
                full.append(copy.deepcopy(vars_sorted[2]))

        (ind_dir / f"{slug}_no_pronouns_no_gender.json").write_text(
            json.dumps(no_pg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ind_dir / f"{slug}_no_gender.json").write_text(
            json.dumps(no_g, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ind_dir / f"{slug}_full.json").write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        write_candidate_files(no_pg, ind_dir / "no_pronouns_no_gender")
        write_candidate_files(no_g, ind_dir / "no_gender")
        write_candidate_files(full, ind_dir / "full")


def write_cv_exports(rows: List[Dict[str, Any]], out_root: Path) -> None:
    pronouns_dir = out_root / "pronouns"
    pronouns_dir.mkdir(parents=True, exist_ok=True)
    (pronouns_dir / "pronouns.json").write_text(
        json.dumps(build_pronouns(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    gender_dir = out_root / "gender"
    gender_dir.mkdir(parents=True, exist_ok=True)
    (gender_dir / "gender.json").write_text(
        json.dumps(build_gender(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def soc_code_filename_token(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return "unknown_soc_code"
    token = re.sub(r"[^A-Za-z0-9]+", "", s)
    return token or "unknown_soc_code"


def split_jd_and_write(rows: List[Dict[str, Any]], out_root: Path) -> None:
    grouped_by_industry: Dict[str, List[Dict[str, Any]]] = {}
    for rec in rows:
        raw_industry = rec.get("industry", "unknown")
        slug = industry_dir_name(raw_industry)
        grouped_by_industry.setdefault(slug, []).append(rec)

    for slug, jobs in grouped_by_industry.items():
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

        (ind_dir / f"{slug}_jd.json").write_text(
            json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        single_dir = ind_dir / "single"
        single_dir.mkdir(parents=True, exist_ok=True)
        for job in jobs:
            soc_slug = job.get("id", "unknown_soc_code")
            # soc_slug = soc_code_filename_token(soc_code)
            (single_dir / f"{soc_slug}.json").write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def find_project_root(start: Path) -> Path:
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
    jd_rows = load_jd_rows(jd_inp)

    split_cv_and_write(cv_rows, cv_out_root)
    write_cv_exports(cv_rows, cv_out_root)
    split_jd_and_write(jd_rows, jd_out_root)

    print(f"Project root: {project_root}")
    print(f"Done. CV input: {REL_CV_INPUT_PATH.as_posix()}")
    print(f"Done. CV output root: {REL_CV_OUTPUT_ROOT.as_posix()}")
    print(f"Done. JD input: {REL_JD_INPUT_PATH.as_posix()}")
    print(f"Done. JD output root: {REL_JD_OUTPUT_ROOT.as_posix()}")


if __name__ == "__main__":
    main()

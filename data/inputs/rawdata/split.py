#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single-file runner for:
1) CV splitting by industry + cue variants + pronouns/gender exports
2) CV per-candidate splitting under full / no_gender / no_pronouns_no_gender
3) JD splitting by industry
4) JD per-soc_code splitting into one individual JD file per soc_code
5) Shared canonical industry directory naming across CV and JD

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
from typing import Any, Dict, List, Tuple

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



def load_jd(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("JD input must be a JSON object.")
    if not isinstance(data.get("occupations"), dict):
        raise ValueError("JD input must contain an 'occupations' object keyed by industry.")
    return data



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



def build_pronouns(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    vals = []
    for rec in rows:
        cid = rec.get("candidate_id")
        pronouns = None
        for key in PRONOUN_KEYS:
            if key in rec:
                pronouns = rec.get(key)
                break
        vals.append({"candidate_id": cid, "pronouns": pronouns})
    return vals, {"count": len(vals)}



def build_gender(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    vals = [{"candidate_id": rec.get("candidate_id"), "gender": rec.get("gender")} for rec in rows]
    return vals, {"count": len(vals)}



def write_candidate_files(records: List[Dict[str, Any]], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    counter: Dict[str, int] = {}
    written = 0
    for idx, rec in enumerate(records, start=1):
        cid = str(rec.get("candidate_id") or rec.get("id") or f"candidate_{idx:04d}").strip()
        stem = safe_slug(cid)
        counter[stem] = counter.get(stem, 0) + 1
        if counter[stem] == 1:
            fname = f"{stem}.json"
        else:
            fname = f"{stem}__dup{counter[stem]:02d}.json"
        (out_dir / fname).write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
    return written



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
            vars_sorted = sorted(vars_, key=lambda x: variant_rank(str(x.get("candidate_id", ""))))
            ordered_ids = [str(x.get("candidate_id", "")) for x in vars_sorted]
            if len(vars_sorted) != 3:
                anomalies.append(
                    f"{canonical}:{bid}: expected 3 occurrences, found {len(vars_sorted)} -> {ordered_ids}"
                )

            if len(vars_sorted) >= 1:
                no_pg.append(remove_pronouns_and_gender_fields(vars_sorted[0]))
            if len(vars_sorted) >= 2:
                no_g.append(remove_gender_fields(vars_sorted[1]))
            if len(vars_sorted) >= 3:
                full.append(copy.deepcopy(vars_sorted[2]))

        f_no_pg_name = f"{slug}_no_pronouns_no_gender.json"
        f_no_g_name = f"{slug}_no_gender.json"
        f_full_name = f"{slug}_full.json"
        all_variants_name = f"{slug}_all_variants.json"

        (ind_dir / f_no_pg_name).write_text(json.dumps(no_pg, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_no_g_name).write_text(json.dumps(no_g, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / f_full_name).write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        (ind_dir / all_variants_name).write_text(
            json.dumps(
                {
                    "industry_target": canonical,
                    "source_industries": sorted(bucket["source_industries"]),
                    "no_pronouns_no_gender": no_pg,
                    "no_gender": no_g,
                    "full": full,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        full_count = write_candidate_files(full, ind_dir / "full")
        no_gender_count = write_candidate_files(no_g, ind_dir / "no_gender")
        no_pg_count = write_candidate_files(no_pg, ind_dir / "no_pronouns_no_gender")

        manifest_industries[canonical] = {
            "industry_slug": slug,
            "source_industries": sorted(bucket["source_industries"]),
            "counts": {
                "base_candidates": len(grouped),
                "no_pronouns_no_gender": len(no_pg),
                "no_gender": len(no_g),
                "full": len(full),
            },
            "outputs": {
                "no_pronouns_no_gender_file": f_no_pg_name,
                "no_gender_file": f_no_g_name,
                "full_file": f_full_name,
                "all_variants_file": all_variants_name,
                "no_pronouns_no_gender_folder": "no_pronouns_no_gender/",
                "no_gender_folder": "no_gender/",
                "full_folder": "full/",
            },
            "per_candidate_files": {
                "no_pronouns_no_gender": no_pg_count,
                "no_gender": no_gender_count,
                "full": full_count,
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



def extract_soc_code(job: Dict[str, Any]) -> str:
    if not isinstance(job, dict):
        return "unknown_soc_code"
    for key in ("soc_code", "SOC_code", "SOC_Code", "soc", "code"):
        value = job.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown_soc_code"



def soc_code_filename_token(value: Any) -> str:
    s = str(value or "").strip()
    if not s:
        return "unknown_soc_code"
    token = re.sub(r"[^A-Za-z0-9]+", "", s)
    return token or "unknown_soc_code"



def split_jd_and_write(jd_data: Dict[str, Any], out_root: Path) -> Dict[str, Any]:
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
            bucket["jobs"].extend([x for x in jobs if isinstance(x, dict)])
        bucket["source_industries"].add(raw_industry)

    manifest_industries: Dict[str, Any] = {}

    for canonical, bucket in grouped_by_canonical.items():
        slug = bucket["slug"]
        ind_dir = out_root / slug
        ind_dir.mkdir(parents=True, exist_ok=True)

        # Industry-level JD: plain occupation list only.
        output_name = f"{slug}_jd.json"
        (ind_dir / output_name).write_text(
            json.dumps(bucket["jobs"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Per-soc_code JD: plain occupation object if unique, otherwise plain list.
        single_dir = ind_dir / "single"
        single_dir.mkdir(parents=True, exist_ok=True)

        soc_groups: Dict[str, List[Dict[str, Any]]] = {}
        for job in bucket["jobs"]:
            soc_slug = soc_code_filename_token(extract_soc_code(job))
            soc_groups.setdefault(soc_slug, []).append(job)

        soc_outputs: Dict[str, Any] = {}
        for soc_slug, jobs_for_soc in sorted(soc_groups.items()):
            first = jobs_for_soc[0]
            original_soc = extract_soc_code(first)
            soc_output_name = f"{slug}_soc_code_{soc_slug}_jd.json"
            payload: Any = jobs_for_soc[0] if len(jobs_for_soc) == 1 else jobs_for_soc
            (single_dir / soc_output_name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            soc_outputs[soc_slug] = {
                "soc_code": original_soc,
                "occupation_count": len(jobs_for_soc),
                "output_file": f"single/{soc_output_name}",
                "format": "object" if len(jobs_for_soc) == 1 else "list",
            }

        manifest_industries[canonical] = {
            "industry_slug": slug,
            "source_industries": sorted(bucket["source_industries"]),
            "occupation_count": len(bucket["jobs"]),
            "output_file": output_name,
            "output_format": "list",
            "soc_code_count": len(soc_groups),
            "soc_code_outputs": soc_outputs,
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
        "industries": split_jd_and_write(jd_data, jd_out_root),
        "notes": [
            "Paths are fixed in code and use project-relative locations.",
            "JD is split by industries under the occupations object.",
            "Industry-level JD files contain only the occupation list.",
            "Per-soc_code JD files contain only the occupation object when unique, otherwise a plain list.",
            "Wrapper blocks like metadata / industry / source_industries are removed from split JD files.",
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

#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

EXPERIMENT_NAME_TO_ID: Dict[str, str] = {
    "borderline": "01",
    "Strength_Test2": "02",
    "Strength_Test3": "03",
    "Policy_Gap_Test": "04",
}
VALID_EXPERIMENT_IDS = {"01", "02", "03", "04"}

TARGET_COLUMNS = [
    "industry",
    "soc_code",
    "experiment_id",
    "candidate_id",
    "job level",
    "gender",
    "total_score",
    "credential_and_qualification_fit",
    "relevant_experience_alignment",
    "core_role_capability",
    "communication_and_collaboration",
    "quality_compliance_and_execution_discipline",
]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_candidate_base(candidate_id: str) -> str:
    return re.sub(r"_[ABC]$", "", candidate_id)


def infer_gender_from_candidate_id(candidate_id: str) -> str:
    match = re.search(r"_(M|F|N|NEO)_[ABC]$", candidate_id.upper())
    if not match:
        return "unknown"
    token = match.group(1)
    return {
        "M": "male",
        "F": "female",
        "N": "neutral",
        "NEO": "neo",
    }.get(token, "unknown")


def infer_level_from_candidate_id(candidate_id: str) -> str:
    cid = candidate_id.upper()
    if "JUN" in cid:
        return "junior"
    if "SEN" in cid:
        return "senior"
    return "unknown"


def build_gender_map(cv_json_path: Path) -> Dict[str, str]:
    candidate_gender_map: Dict[str, str] = {}
    if not cv_json_path.exists():
        return candidate_gender_map

    data = load_json(cv_json_path)
    if not isinstance(data, list):
        return candidate_gender_map

    base_gender_map: Dict[str, str] = {}

    for row in data:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id:
            continue
        gender = row.get("gender")
        if isinstance(gender, str) and gender.strip():
            gender = gender.strip()
            candidate_gender_map[candidate_id] = gender
            base_gender_map[normalize_candidate_base(candidate_id)] = gender

    for row in data:
        if not isinstance(row, dict):
            continue
        candidate_id = str(row.get("candidate_id", "")).strip()
        if not candidate_id:
            continue
        base_id = normalize_candidate_base(candidate_id)
        candidate_gender_map.setdefault(
            candidate_id,
            base_gender_map.get(base_id, infer_gender_from_candidate_id(candidate_id)),
        )

    return candidate_gender_map


def prettify_industry(industry: str) -> str:
    raw = industry.strip()
    if not raw:
        return raw
    mapping = {
        "construction": "Construction",
        "it": "IT",
        "nursing": "Nursing",
    }
    return mapping.get(raw.lower(), raw)


def is_valid_summary_payload(obj: Any) -> bool:
    if not isinstance(obj, list) or not obj:
        return False
    first = obj[0]
    return isinstance(first, dict) and "candidate_id" in first and "total_score" in first


def looks_like_project_root(path: Path) -> bool:
    return (
        (path / "data" / "outputs").exists()
        and (path / "data" / "inputs" / "rawdata").exists()
    )


def candidate_roots() -> List[Path]:
    seen = set()
    candidates: List[Path] = []

    for base in [Path.cwd(), Path(__file__).resolve().parent]:
        for cand in [base, *base.parents]:
            key = str(cand)
            if key not in seen:
                seen.add(key)
                candidates.append(cand)

    return candidates


def find_project_root() -> Path:
    for candidate in candidate_roots():
        if looks_like_project_root(candidate):
            return candidate
    searched = "\n".join(str(p) for p in candidate_roots())
    raise FileNotFoundError(
        "Could not locate project root automatically. Expected a directory containing "
        "data/outputs and data/inputs/rawdata. Searched:\n" + searched
    )


PROJECT_ROOT = find_project_root()
OUTPUTS_ROOT = PROJECT_ROOT / "data" / "outputs"
CV_RAW_JSON = PROJECT_ROOT / "data" / "inputs" / "rawdata" / "CV.json"
EXCEL_OUT = PROJECT_ROOT / "data" / "outputs" / "all_experiment_summary_extract.xlsx"


def parse_summary_context(summary_path: Path) -> Optional[Tuple[str, str, str]]:
    """
    返回: (industry, jd_key_as_soc_code, experiment_id)

    支持两种目录：
    1) 新版：data/outputs/Construction/<jd_key>/<jd_key>_01_summary.json
    2) 旧版：data/outputs/borderline/construction/<jd_key>/no_pronouns_no_gender_summary.json
    """
    rel_parts = summary_path.relative_to(OUTPUTS_ROOT).parts
    if len(rel_parts) < 3:
        return None

    first = rel_parts[0]

    match_new = re.match(r"^(.+?)_(\d{2})_summary\.json$", summary_path.name)
    if first not in EXPERIMENT_NAME_TO_ID and match_new and len(rel_parts) >= 3:
        industry = prettify_industry(rel_parts[0])
        jd_key = rel_parts[1]
        experiment_id = match_new.group(2)
        if experiment_id not in VALID_EXPERIMENT_IDS:
            return None
        return industry, jd_key, experiment_id

    if first in EXPERIMENT_NAME_TO_ID and len(rel_parts) >= 4:
        experiment_name = rel_parts[0]
        industry = prettify_industry(rel_parts[1])
        jd_key = rel_parts[2]
        experiment_id = EXPERIMENT_NAME_TO_ID[experiment_name]
        return industry, jd_key, experiment_id

    return None


def extract_rows() -> List[Dict[str, Any]]:
    if not OUTPUTS_ROOT.exists():
        raise FileNotFoundError(f"Outputs directory not found: {OUTPUTS_ROOT}")

    gender_map = build_gender_map(CV_RAW_JSON)
    rows: List[Dict[str, Any]] = []

    for summary_path in sorted(OUTPUTS_ROOT.rglob("*_summary.json")):
        try:
            payload = load_json(summary_path)
        except Exception:
            continue

        if not is_valid_summary_payload(payload):
            continue

        context = parse_summary_context(summary_path)
        if context is None:
            continue
        industry, soc_code, experiment_id = context

        for item in payload:
            if not isinstance(item, dict):
                continue
            candidate_id = str(item.get("candidate_id", "")).strip()
            if not candidate_id:
                continue
            subscores = item.get("subscores", {}) or {}
            if not isinstance(subscores, dict):
                subscores = {}

            row = {
                "industry": industry,
                "soc_code": soc_code,
                "experiment_id": experiment_id,
                "candidate_id": candidate_id,
                "job level": infer_level_from_candidate_id(candidate_id),
                "gender": gender_map.get(candidate_id, infer_gender_from_candidate_id(candidate_id)),
                "total_score": item.get("total_score"),
                "credential_and_qualification_fit": subscores.get("credential_and_qualification_fit"),
                "relevant_experience_alignment": subscores.get("relevant_experience_alignment"),
                "core_role_capability": subscores.get("core_role_capability"),
                "communication_and_collaboration": subscores.get("communication_and_collaboration"),
                "quality_compliance_and_execution_discipline": subscores.get(
                    "quality_compliance_and_execution_discipline"
                ),
            }
            rows.append(row)

    rows.sort(
        key=lambda x: (
            str(x["industry"]).lower(),
            str(x["soc_code"]).lower(),
            str(x["experiment_id"]).lower(),
            str(x["candidate_id"]).lower(),
        )
    )
    return rows


def autosize_excel_columns(excel_path: Path) -> None:
    wb = load_workbook(excel_path)
    ws = wb["summary"]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:
        cell.font = Font(bold=True)

    for col_idx, column_cells in enumerate(ws.columns, start=1):
        max_len = 0
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_len = max(max_len, len(value))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 40)

    wb.save(excel_path)


def main() -> None:
    rows = extract_rows()
    if not rows:
        raise RuntimeError(f"No valid experiment summary data found under {OUTPUTS_ROOT}.")

    df = pd.DataFrame(rows, columns=TARGET_COLUMNS)
    EXCEL_OUT.parent.mkdir(parents=True, exist_ok=True)

    if EXCEL_OUT.exists():
        EXCEL_OUT.unlink()

    df.to_excel(EXCEL_OUT, index=False, sheet_name="summary")
    autosize_excel_columns(EXCEL_OUT)

    print(f"[OK] project_root={PROJECT_ROOT}")
    print(f"[OK] rows={len(df)}")
    print(f"[OK] excel={EXCEL_OUT}")


if __name__ == "__main__":
    main()

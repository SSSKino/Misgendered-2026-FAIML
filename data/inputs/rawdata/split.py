#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

ROOT = Path(__file__).resolve().parents[3]
RAWDATA_DIR = ROOT / "data" / "inputs" / "rawdata"
SAMPLES_DIR = ROOT / "data" / "inputs" / "samples"

REQUIRED_FIELDS = ("sample_id", "company", "claim_text")
DEFAULT_GLOB = "*.json"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def slugify(value: str) -> str:
    text = clean_text(value)
    if not text:
        return "unknown"
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "unknown"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_candidate_files(raw_dir: Path, pattern: str) -> Iterable[Path]:
    return sorted(raw_dir.glob(pattern), key=lambda p: p.name.lower())


def validate_record(record: Any, *, source_path: Path, index: int) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f"Record #{index} in {source_path} is not a JSON object.")

    missing = [field for field in REQUIRED_FIELDS if not clean_text(record.get(field))]
    if missing:
        raise ValueError(
            f"Record #{index} in {source_path} is missing required fields: {', '.join(missing)}"
        )
    return dict(record)


def companies_in_payload(payload: Any, *, source_path: Path) -> List[str]:
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Source file must be a non-empty JSON array: {source_path}")

    companies: Set[str] = set()
    for index, item in enumerate(payload, start=1):
        record = validate_record(item, source_path=source_path, index=index)
        companies.add(slugify(clean_text(record["company"])))
    return sorted(companies)


def split_source_file(source_path: Path, output_root: Path) -> Dict[str, Any]:
    payload = load_json(source_path)
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {source_path}, got: {type(payload).__name__}")

    written = 0
    seen_global_sample_ids: Set[str] = set()
    company_counts: Dict[str, int] = {}

    for index, item in enumerate(payload, start=1):
        record = validate_record(item, source_path=source_path, index=index)
        sample_id = clean_text(record["sample_id"])
        company_name = clean_text(record["company"])
        company_slug = slugify(company_name)

        if sample_id in seen_global_sample_ids:
            raise ValueError(f"Duplicate sample_id '{sample_id}' inside {source_path}")
        seen_global_sample_ids.add(sample_id)

        out_path = output_root / company_slug / f"{slugify(sample_id)}.json"
        write_json(out_path, record)
        written += 1
        company_counts[company_slug] = company_counts.get(company_slug, 0) + 1

    return {
        "source_file": source_path.name,
        "records_written": written,
        "company_counts": company_counts,
    }


def remove_old_company_dirs(output_root: Path, company_dirs: Iterable[str]) -> None:
    for company_dir in sorted(set(company_dirs)):
        target = output_root / company_dir
        if target.exists() and target.is_dir():
            shutil.rmtree(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Split claim-evidence JSON arrays into per-sample files grouped by company.")
    parser.add_argument("--input-dir", type=Path, default=RAWDATA_DIR, help=f"Directory containing source JSON files (default: {RAWDATA_DIR})")
    parser.add_argument("--output-dir", type=Path, default=SAMPLES_DIR, help=f"Directory to write per-sample JSON files (default: {SAMPLES_DIR})")
    parser.add_argument("--pattern", default=DEFAULT_GLOB, help=f"Glob pattern for source files (default: {DEFAULT_GLOB})")
    parser.add_argument("--clean", action="store_true", help="Delete existing company folders in the output directory before writing new files.")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    source_files = list(iter_candidate_files(input_dir, args.pattern))
    if not source_files:
        raise FileNotFoundError(
            f"No source files matched pattern '{args.pattern}' under: {input_dir}"
        )

    company_dirs_to_clean: List[str] = []
    for source_path in source_files:
        payload = load_json(source_path)
        company_dirs_to_clean.extend(companies_in_payload(payload, source_path=source_path))

    if args.clean:
        remove_old_company_dirs(output_dir, company_dirs_to_clean)

    manifest: List[Dict[str, Any]] = []
    total_written = 0
    for source_path in source_files:
        info = split_source_file(source_path, output_dir)
        manifest.append(info)
        total_written += int(info["records_written"])

    write_json(
        output_dir / "split_manifest.json",
        {
            "total_files": total_written,
            "source_count": len(source_files),
            "sources": manifest,
        },
    )
    print(f"[DONE] wrote {total_written} sample files into {output_dir}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
CV_ROOT = ROOT / "data" / "inputs" / "CV"
JD_ROOT = ROOT / "data" / "inputs" / "JD"
OUTPUT_ROOT = ROOT / "data" / "outputs"
RAW_SPLIT_SCRIPT = ROOT / "data" / "inputs" / "rawdata" / "split.py"
EXCLUDED_DIRS = {"gender", "pronouns", "__pycache__"}
EXPERIMENT_VARIANTS: Dict[str, str] = {
    "borderline": "no_pronouns_no_gender",
    "Strength_Test1": "no_pronouns_no_gender",
    "Strength_Test2": "no_gender",
    "Strength_Test3": "full",
    "Policy_Gap_Test": "no_pronouns_no_gender",
}


def run(cmd: List[str]) -> None:
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


def ensure_single_inputs() -> None:
    if not RAW_SPLIT_SCRIPT.exists():
        raise FileNotFoundError(f"Split script not found: {RAW_SPLIT_SCRIPT}")
    run([PYTHON, str(RAW_SPLIT_SCRIPT)])


def list_industry_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted(
        [p for p in root.iterdir() if p.is_dir() and p.name not in EXCLUDED_DIRS],
        key=lambda p: p.name.lower(),
    )


def list_single_jd_files(industry_dir: Path) -> List[Path]:
    single_dir = industry_dir / "single"
    if single_dir.exists():
        files = sorted(single_dir.glob("*.json"), key=lambda p: p.name.lower())
        if files:
            return files
    files = [p for p in industry_dir.glob("*.json") if p.name.lower().endswith("_jd.json")]
    return sorted(files, key=lambda p: p.name.lower())


def list_single_cv_files(industry_dir: Path, variant: str) -> List[Path]:
    variant_dir = industry_dir / variant
    if not variant_dir.exists():
        raise FileNotFoundError(f"Missing CV variant directory: {variant_dir}")
    files = sorted(variant_dir.glob("*.json"), key=lambda p: p.name.lower())
    if not files:
        raise FileNotFoundError(f"No single CV files found in: {variant_dir}")
    return files


def shared_industries() -> List[Tuple[Path, Path]]:
    jd_dirs = {p.name.lower(): p for p in list_industry_dirs(JD_ROOT)}
    cv_dirs = {p.name.lower(): p for p in list_industry_dirs(CV_ROOT)}
    return [(jd_dirs[key], cv_dirs[key]) for key in sorted(set(jd_dirs) & set(cv_dirs))]


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def init_industry_aggregate(experiment: str, industry: str, variant: str) -> Dict[str, Any]:
    return {
        "experiment": experiment,
        "industry": industry,
        "variant": variant,
        "jd_files": [],
        "candidate_results": {},
    }


def append_result(store: Dict[str, Any], *, jd_file: Path, jd_key: str, candidate_id: str, cv_file: Path, result_file: Path, result_obj: Dict[str, Any]) -> None:
    jd_rel = rel(jd_file)
    if jd_rel not in store["jd_files"]:
        store["jd_files"].append(jd_rel)
    candidate_bucket = store["candidate_results"].setdefault(candidate_id, {
        "candidate_id": candidate_id,
        "cv_file": rel(cv_file),
        "evaluation_count": 0,
        "evaluations": [],
    })
    candidate_bucket["evaluation_count"] += 1
    candidate_bucket["evaluations"].append({
        "jd_key": jd_key,
        "jd_file": jd_rel,
        "result_file": rel(result_file),
        "result": result_obj,
    })


def write_industry_aggregates(experiment: str, industry: str, variant: str, store: Dict[str, Any]) -> None:
    industry_root = OUTPUT_ROOT / experiment / industry
    candidates_result_dir = industry_root / "candidates_result"
    candidates_result_dir.mkdir(parents=True, exist_ok=True)

    summary_candidates: List[Dict[str, Any]] = []
    total_evaluations = 0

    for candidate_id in sorted(store["candidate_results"].keys(), key=str.lower):
        candidate_obj = store["candidate_results"][candidate_id]
        candidate_path = candidates_result_dir / f"{candidate_id}.json"
        write_json(candidate_path, candidate_obj)
        total_evaluations += int(candidate_obj.get("evaluation_count", 0))
        summary_candidates.append({
            "candidate_id": candidate_id,
            "cv_file": candidate_obj.get("cv_file", ""),
            "evaluation_count": candidate_obj.get("evaluation_count", 0),
            "candidate_result_file": f"candidates_result/{candidate_id}.json",
        })

    summary_obj = {
        "experiment": experiment,
        "industry": industry,
        "variant": variant,
        "jd_count": len(store["jd_files"]),
        "candidate_count": len(summary_candidates),
        "evaluation_count": total_evaluations,
        "jd_files": sorted(store["jd_files"], key=str.lower),
        "candidates": summary_candidates,
    }
    summary_path = industry_root / f"{experiment}_{industry}.json"
    write_json(summary_path, summary_obj)


def main() -> None:
    ensure_single_inputs()
    industry_pairs = shared_industries()
    if not industry_pairs:
        raise SystemExit(f"No shared industry directories found between {JD_ROOT} and {CV_ROOT}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    aggregates: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for jd_industry_dir, cv_industry_dir in industry_pairs:
        industry = cv_industry_dir.name
        if jd_industry_dir.name.lower() != cv_industry_dir.name.lower():
            raise ValueError(f"JD and CV industry directories do not match: {jd_industry_dir} vs {cv_industry_dir}")

        jd_files = list_single_jd_files(jd_industry_dir)
        if not jd_files:
            print(f"[WARN] No single JD files found under: {jd_industry_dir}")
            continue

        for jd_file in jd_files:
            jd_key = jd_file.stem
            print(f"[INFO] Running all experiments for JD: {jd_file}")
            for experiment_name, variant in EXPERIMENT_VARIANTS.items():
                script_path = ROOT / "src" / f"{experiment_name}.py"
                if not script_path.exists():
                    raise FileNotFoundError(f"Missing experiment script: {script_path}")

                cv_files = list_single_cv_files(cv_industry_dir, variant)
                out_dir = OUTPUT_ROOT / experiment_name / industry / jd_key / variant
                out_dir.mkdir(parents=True, exist_ok=True)

                store_key = (experiment_name, industry)
                if store_key not in aggregates:
                    aggregates[store_key] = init_industry_aggregate(experiment_name, industry, variant)

                for cv_file in cv_files:
                    candidate_id = cv_file.stem
                    out_path = out_dir / f"{candidate_id}.json"
                    run([PYTHON, str(script_path), str(jd_file), str(cv_file), "--out", str(out_path)])
                    result_obj = load_json(out_path)
                    append_result(
                        aggregates[store_key],
                        jd_file=jd_file,
                        jd_key=jd_key,
                        candidate_id=candidate_id,
                        cv_file=cv_file,
                        result_file=out_path,
                        result_obj=result_obj,
                    )

    for (experiment_name, industry), store in sorted(aggregates.items()):
        write_industry_aggregates(experiment_name, industry, str(store.get("variant", "")), store)


if __name__ == "__main__":
    main()

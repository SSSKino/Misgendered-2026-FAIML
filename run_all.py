#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
CV_ROOT = ROOT / "data" / "inputs" / "CV"
JD_ROOT = ROOT / "data" / "inputs" / "JD"
OUTPUT_ROOT = ROOT / "data" / "outputs"
RAW_SPLIT_SCRIPT = ROOT / "data" / "inputs" / "rawdata" / "split.py"
EXCLUDED_DIRS = {"gender", "pronouns", "__pycache__"}
EXPERIMENT_VARIANTS: Dict[str, str] = {
    "borderline": "no_pronouns_no_gender",
    "Strength_Test2": "no_gender",
    "Strength_Test3": "full",
    "Policy_Gap_Test": "no_pronouns_no_gender",
}
EXPERIMENT_CODES: Dict[str, str] = {
    "borderline": "01",
    "Strength_Test2": "02",
    "Strength_Test3": "03",
    "Policy_Gap_Test": "04",
}

# =========================
# Run config
# 在这里直接调整“单个JD + 单个实验”下 CV 的并发线程数
# 运行顺序固定为：JD串行 -> 实验串行 -> CV并发
# 例如可改为 4、8、12
# =========================
INDUSTRY_WORKERS = max(1, min(96, 48))


def run(cmd: List[str], *, label: str, env: Optional[Dict[str, str]] = None) -> None:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode == 0:
        print(f"[OK] {label}")
        return

    print(f"[ERROR] {label}")
    err_text = (proc.stderr or proc.stdout or "").strip()
    if err_text:
        last_line = err_text.splitlines()[-1].strip()
        if last_line:
            print(f"       {last_line[:300]}")
    raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)


def ensure_single_inputs() -> None:
    if not RAW_SPLIT_SCRIPT.exists():
        raise FileNotFoundError(f"Split script not found: {RAW_SPLIT_SCRIPT}")
    run([PYTHON, str(RAW_SPLIT_SCRIPT)], label="split inputs")


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


def try_load_existing_result(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = load_json(path)
    except Exception:
        return None
    if isinstance(obj, dict) and "candidate_id" in obj and "total_score" in obj:
        return obj
    return None


def build_variant_summary(result_dir: Path) -> Optional[Path]:
    if not result_dir.exists():
        return None
    rows: List[Any] = []
    for json_path in sorted(result_dir.glob("*.json"), key=lambda p: p.name.lower()):
        try:
            rows.append(load_json(json_path))
        except Exception:
            continue
    if not rows:
        return None
    summary_path = result_dir.parent / f"{result_dir.name}_summary.json"
    write_json(summary_path, rows)
    return summary_path


def execute_evaluation_task(task: Dict[str, Any]) -> Dict[str, Any]:
    env = os.environ.copy()
    cmd = [
        PYTHON,
        str(task["script_path"]),
        str(task["jd_file"]),
        str(task["cv_file"]),
        "--out",
        str(task["out_path"]),
        "--skip-parent-aggregate",
    ]
    run(cmd, label=str(task["label"]), env=env)
    result_obj = load_json(task["out_path"])
    return {
        "experiment": task["experiment_name"],
        "industry": task["industry"],
        "variant": task["variant"],
        "jd_file": task["jd_file"],
        "jd_key": task["jd_key"],
        "cv_file": task["cv_file"],
        "candidate_id": task["candidate_id"],
        "out_path": task["out_path"],
        "result_obj": result_obj,
    }


def write_failures_log(failures: List[Dict[str, Any]]) -> Path:
    out_path = OUTPUT_ROOT / "run_failures.json"
    write_json(out_path, failures)
    return out_path


def experiment_code_for(experiment_name: str) -> str:
    try:
        return EXPERIMENT_CODES[experiment_name]
    except KeyError as e:
        raise KeyError(f"Missing experiment code for: {experiment_name}") from e


def result_dir_for(experiment_name: str, industry: str, jd_key: str) -> Path:
    exp_code = experiment_code_for(experiment_name)
    return OUTPUT_ROOT / industry / jd_key / f"{jd_key}_{exp_code}"


def industry_root_for(experiment_name: str, industry: str) -> Path:
    return OUTPUT_ROOT / industry


def init_industry_aggregate(experiment: str, industry: str, variant: str) -> Dict[str, Any]:
    return {
        "experiment": experiment,
        "experiment_code": experiment_code_for(experiment),
        "industry": industry,
        "variant": variant,
        "jd_files": [],
        "candidate_results": {},
    }


def append_result(
    store: Dict[str, Any],
    *,
    jd_file: Path,
    jd_key: str,
    candidate_id: str,
    cv_file: Path,
    result_file: Path,
    result_obj: Dict[str, Any],
) -> None:
    jd_rel = rel(jd_file)
    if jd_rel not in store["jd_files"]:
        store["jd_files"].append(jd_rel)
    candidate_bucket = store["candidate_results"].setdefault(
        candidate_id,
        {
            "candidate_id": candidate_id,
            "cv_file": rel(cv_file),
            "evaluation_count": 0,
            "evaluations": [],
        },
    )
    candidate_bucket["evaluation_count"] += 1
    candidate_bucket["evaluations"].append(
        {
            "jd_key": jd_key,
            "jd_file": jd_rel,
            "result_file": rel(result_file),
            "result": result_obj,
        }
    )


def write_industry_aggregates(experiment: str, industry: str, variant: str, store: Dict[str, Any]) -> Path:
    industry_root = industry_root_for(experiment, industry)
    exp_code = experiment_code_for(experiment)
    candidates_result_dir = industry_root / f"candidates_result_{exp_code}"
    candidates_result_dir.mkdir(parents=True, exist_ok=True)

    summary_candidates: List[Dict[str, Any]] = []
    total_evaluations = 0

    for candidate_id in sorted(store["candidate_results"].keys(), key=str.lower):
        candidate_obj = store["candidate_results"][candidate_id]
        candidate_path = candidates_result_dir / f"{candidate_id}.json"
        write_json(candidate_path, candidate_obj)
        total_evaluations += int(candidate_obj.get("evaluation_count", 0))
        summary_candidates.append(
            {
                "candidate_id": candidate_id,
                "cv_file": candidate_obj.get("cv_file", ""),
                "evaluation_count": candidate_obj.get("evaluation_count", 0),
                "candidate_result_file": f"candidates_result_{exp_code}/{candidate_id}.json",
            }
        )

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
    summary_path = industry_root / f"{industry}_{exp_code}.json"
    write_json(summary_path, summary_obj)
    return summary_path


def resolve_group_data_file() -> Optional[Path]:
    preferred = [CV_ROOT / "gender" / "gender.json", CV_ROOT / "pronouns" / "pronouns.json"]
    for path in preferred:
        if path.exists():
            return path
    return None


def gender_analysis_script_for_experiment(experiment_name: str) -> Path:
    suffix = experiment_name if experiment_name != "borderline" else "borderline"
    return ROOT / "src" / f"gender_analysis_{suffix}.py"


def run_experiment_batch(
    *,
    experiment_name: str,
    industry: str,
    variant: str,
    script_path: Path,
    jd_file: Path,
    jd_key: str,
    cv_files: List[Path],
    resume_mode: bool,
    aggregates: Dict[Tuple[str, str], Dict[str, Any]],
    failures: List[Dict[str, Any]],
) -> None:
    out_dir = result_dir_for(experiment_name, industry, jd_key)
    out_dir.mkdir(parents=True, exist_ok=True)

    store_key = (experiment_name, industry)
    if store_key not in aggregates:
        aggregates[store_key] = init_industry_aggregate(experiment_name, industry, variant)

    pending_tasks: List[Dict[str, Any]] = []
    total_cv = len(cv_files)

    for idx, cv_file in enumerate(cv_files, start=1):
        candidate_id = cv_file.stem
        out_path = out_dir / f"{candidate_id}.json"
        label = f"{experiment_name} | {industry} | {jd_key} | {idx}/{total_cv}"

        existing_result = try_load_existing_result(out_path) if resume_mode else None
        if existing_result is not None:
            print(f"[SKIP] {label}")
            append_result(
                aggregates[store_key],
                jd_file=jd_file,
                jd_key=jd_key,
                candidate_id=candidate_id,
                cv_file=cv_file,
                result_file=out_path,
                result_obj=existing_result,
            )
            continue

        pending_tasks.append(
            {
                "experiment_name": experiment_name,
                "industry": industry,
                "variant": variant,
                "script_path": script_path,
                "jd_file": jd_file,
                "jd_key": jd_key,
                "cv_file": cv_file,
                "candidate_id": candidate_id,
                "out_path": out_path,
                "label": label,
            }
        )

    if pending_tasks:
        worker_count = max(1, min(INDUSTRY_WORKERS, len(pending_tasks)))
        print(
            f"[INFO] JD={jd_key} | experiment={experiment_name} | industry={industry} | "
            f"pending_cv={len(pending_tasks)} | workers={worker_count}"
        )
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_task = {executor.submit(execute_evaluation_task, task): task for task in pending_tasks}
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    done = future.result()
                    append_result(
                        aggregates[store_key],
                        jd_file=done["jd_file"],
                        jd_key=done["jd_key"],
                        candidate_id=done["candidate_id"],
                        cv_file=done["cv_file"],
                        result_file=done["out_path"],
                        result_obj=done["result_obj"],
                    )
                except Exception as e:
                    failures.append(
                        {
                            "experiment": task["experiment_name"],
                            "industry": task["industry"],
                            "jd_file": rel(task["jd_file"]),
                            "cv_file": rel(task["cv_file"]),
                            "out_file": rel(task["out_path"]),
                            "error": str(e),
                        }
                    )
    summary_path = build_variant_summary(out_dir)
    if summary_path is not None:
        print(f"[OK] variant_summary | {rel(summary_path)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="Skip completed result files and continue from previous run")
    parser.add_argument("--force", action="store_true", help="Re-run even if output files already exist")
    parser.add_argument("--skip-split", action="store_true", help="Do not run split.py before experiments")
    args = parser.parse_args()

    resume_mode = not args.force
    if args.resume:
        resume_mode = True

    if not args.skip_split:
        ensure_single_inputs()

    industry_pairs = shared_industries()
    if not industry_pairs:
        raise SystemExit(f"No shared industry directories found between {JD_ROOT} and {CV_ROOT}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    aggregates: Dict[Tuple[str, str], Dict[str, Any]] = {}
    failures: List[Dict[str, Any]] = []

    for jd_industry_dir, cv_industry_dir in industry_pairs:
        industry = cv_industry_dir.name
        if jd_industry_dir.name.lower() != cv_industry_dir.name.lower():
            raise ValueError("JD and CV industry directories do not match")

        jd_files = list_single_jd_files(jd_industry_dir)
        if not jd_files:
            print(f"[WARN] No single JD files found for industry={industry}")
            continue

        print(f"[INFO] industry={industry} | jd_count={len(jd_files)} | mode=JD顺序->实验顺序->CV并发")

        for jd_index, jd_file in enumerate(jd_files, start=1):
            jd_key = jd_file.stem
            print(f"[INFO] JD {jd_index}/{len(jd_files)} | industry={industry} | jd={jd_key}")

            for experiment_name, variant in EXPERIMENT_VARIANTS.items():
                script_path = ROOT / "src" / f"{experiment_name}.py"
                if not script_path.exists():
                    raise FileNotFoundError(f"Missing experiment script: {script_path}")

                cv_files = list_single_cv_files(cv_industry_dir, variant)
                run_experiment_batch(
                    experiment_name=experiment_name,
                    industry=industry,
                    variant=variant,
                    script_path=script_path,
                    jd_file=jd_file,
                    jd_key=jd_key,
                    cv_files=cv_files,
                    resume_mode=resume_mode,
                    aggregates=aggregates,
                    failures=failures,
                )

    group_data_file = resolve_group_data_file()

    for (experiment_name, industry), store in sorted(aggregates.items()):
        summary_path = write_industry_aggregates(experiment_name, industry, str(store.get("variant", "")), store)
        print(f"[OK] summary | {experiment_name} | {industry}")
        if group_data_file is None:
            continue

        ga_script = gender_analysis_script_for_experiment(experiment_name)
        if not ga_script.exists():
            print(f"[WARN] Missing gender analysis script for {experiment_name}")
            continue

        exp_code = experiment_code_for(experiment_name)
        ga_out = summary_path.parent / f"gender_analysis_{industry}_{exp_code}.json"
        ga_label = f"gender_analysis | {experiment_name} | {industry}"

        if resume_mode and ga_out.exists():
            print(f"[SKIP] {ga_label}")
            continue

        try:
            run([PYTHON, str(ga_script), str(summary_path), str(group_data_file), "--out", str(ga_out)], label=ga_label)
        except Exception as e:
            failures.append(
                {
                    "experiment": experiment_name,
                    "industry": industry,
                    "summary_file": rel(summary_path),
                    "group_data_file": rel(group_data_file),
                    "out_file": rel(ga_out),
                    "error": str(e),
                }
            )

    if failures:
        failure_log = write_failures_log(failures)
        print(f"[WARN] Some tasks failed. failure_log={rel(failure_log)}")
    else:
        print("[INFO] All tasks completed successfully.")


if __name__ == "__main__":
    main()

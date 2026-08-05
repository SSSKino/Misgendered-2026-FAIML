#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable
SAMPLES_ROOT = ROOT / "data" / "inputs" / "samples"
OUTPUT_ROOT = ROOT / "data" / "outputs"

EXPERIMENTS: List[Dict[str, Any]] = [
    {
        "experiment_id": 1,
        "experiment_name": "borderline",
        "setting_name": "Setting A",
        "script_path": str(ROOT / "src" / "borderline.py"),
        "output_dir_name": "setting_A",
    },
    {
        "experiment_id": 2,
        "experiment_name": "Strength_Test2",
        "setting_name": "Setting B",
        "script_path": str(ROOT / "src" / "Strength_Test2.py"),
        "output_dir_name": "setting_B",
    },
    {
        "experiment_id": 3,
        "experiment_name": "Strength_Test3",
        "setting_name": "Setting C",
        "script_path": str(ROOT / "src" / "Strength_Test3.py"),
        "output_dir_name": "setting_C",
    },
]

def default_sample_workers() -> int:
    raw = os.getenv("EXPERIMENT_WORKERS", "8")
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


SAMPLE_WORKERS = default_sample_workers()

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
        for line in err_text.splitlines()[-3:]:
            line = line.strip()
            if line:
                print(f"       {line[:300]}")
    raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)


from src.common_io import build_predictions_summary, load_json, slugify_filename  # noqa: E402
from src.result_analysis import build_setting_analysis  # noqa: E402


def sample_input_dir() -> Path:
    all_dir = SAMPLES_ROOT / "all"
    if all_dir.exists():
        has_json = any(p.name != "split_manifest.json" for p in all_dir.rglob("*.json"))
        if has_json:
            return all_dir
    return SAMPLES_ROOT


def list_sample_files() -> List[Path]:
    input_dir = sample_input_dir()
    if not input_dir.exists():
        raise FileNotFoundError(
            f"Sample input directory not found: {input_dir}. Put single-sample JSON files under data/inputs/samples/ or data/inputs/samples/all/."
        )

    files = sorted(
        [p for p in input_dir.rglob("*.json") if p.name != "split_manifest.json"],
        key=lambda p: str(p.relative_to(input_dir)).lower(),
    )
    if not files:
        raise FileNotFoundError(f"No sample JSON files found in: {input_dir}")
    return files


def try_load_existing_result(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = load_json(path)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    required = {"sample_id", "llm_label", "experiment_id"}
    if required.issubset(obj.keys()):
        return obj
    return None


def build_out_path(experiment: Dict[str, Any], sample_file: Path) -> Path:
    input_dir = sample_input_dir()
    rel_path = sample_file.relative_to(input_dir)
    rel_parent = rel_path.parent
    filename = f"{slugify_filename(sample_file.stem)}.json"
    out_dir = OUTPUT_ROOT / experiment["output_dir_name"] / "individual" / rel_parent
    return out_dir / filename


def execute_task(task: Dict[str, Any]) -> Dict[str, Any]:
    cmd = [
        PYTHON,
        str(task["script_path"]),
        str(task["sample_file"]),
        "--out",
        str(task["out_path"]),
        "--skip-parent-aggregate",
    ]
    run(cmd, label=task["label"], env=os.environ.copy())
    result_obj = load_json(task["out_path"])
    return {
        "experiment_id": task["experiment_id"],
        "experiment_name": task["experiment_name"],
        "setting_name": task["setting_name"],
        "sample_file": str(task["sample_file"]),
        "out_path": str(task["out_path"]),
        "result_obj": result_obj,
    }


def write_failures_log(failures: List[Dict[str, Any]]) -> Path:
    out_path = OUTPUT_ROOT / "run_failures.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def serialize_failure(ex: BaseException) -> Dict[str, Any]:
    failure: Dict[str, Any] = {
        "error_type": type(ex).__name__,
        "error": str(ex),
    }
    if isinstance(ex, subprocess.CalledProcessError):
        failure.update(
            {
                "returncode": ex.returncode,
                "cmd": ex.cmd,
                "stdout": ex.output or "",
                "stderr": ex.stderr or "",
            }
        )
    return failure


def rebuild_setting_summary(experiment: Dict[str, Any]) -> Path:
    result_dir = OUTPUT_ROOT / experiment["output_dir_name"] / "individual"
    summary_path = OUTPUT_ROOT / experiment["output_dir_name"] / f"{experiment['output_dir_name']}_predictions.json"
    return build_predictions_summary(
        result_dir,
        summary_path=summary_path,
        meta={
            "experiment_id": experiment["experiment_id"],
            "experiment_name": experiment["experiment_name"],
            "setting_name": experiment["setting_name"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run claim-support experiments across all sample JSON files.")
    parser.add_argument("--workers", type=int, default=SAMPLE_WORKERS, help=f"Max sample workers per setting (default: {SAMPLE_WORKERS})")
    parser.add_argument("--resume", action="store_true", default=True, help="Skip sample outputs that already exist and look valid (default: enabled)")
    args = parser.parse_args()

    sample_files = list_sample_files()
    failures: List[Dict[str, Any]] = []

    for experiment in EXPERIMENTS:
        pending_tasks: List[Dict[str, Any]] = []
        existing_count = 0

        for sample_file in sample_files:
            out_path = build_out_path(experiment, sample_file)
            existing = try_load_existing_result(out_path) if args.resume else None
            if existing is not None:
                existing_count += 1
                continue

            pending_tasks.append(
                {
                    "experiment_id": experiment["experiment_id"],
                    "experiment_name": experiment["experiment_name"],
                    "setting_name": experiment["setting_name"],
                    "script_path": experiment["script_path"],
                    "sample_file": sample_file,
                    "out_path": out_path,
                    "label": f"{experiment['experiment_name']} | {sample_file.relative_to(sample_input_dir())}",
                }
            )

        print(
            f"[INFO] experiment_id={experiment['experiment_id']} | experiment={experiment['experiment_name']} | setting={experiment['setting_name']} | "
            f"total_samples={len(sample_files)} | completed={existing_count} | pending={len(pending_tasks)} | workers={max(1, args.workers)}"
        )

        if pending_tasks:
            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
                future_map = {executor.submit(execute_task, task): task for task in pending_tasks}
                for future in as_completed(future_map):
                    task = future_map[future]
                    try:
                        future.result()
                    except Exception as ex:
                        failure = {
                            "experiment_id": experiment["experiment_id"],
                            "experiment_name": experiment["experiment_name"],
                            "setting_name": experiment["setting_name"],
                            "sample_file": str(task["sample_file"]),
                            "out_path": str(task["out_path"]),
                        }
                        failure.update(serialize_failure(ex))
                        failures.append(failure)

        summary_path = rebuild_setting_summary(experiment)
        analysis_paths = build_setting_analysis(summary_path)
        print(f"[SUMMARY] {summary_path.relative_to(ROOT)}")
        print(f"[ANALYSIS] {analysis_paths['analysis'].relative_to(ROOT)}")
        print(f"[ERRORS] {analysis_paths['errors'].relative_to(ROOT)}")
        print(f"[CASES] {analysis_paths['cases'].relative_to(ROOT)}")

    if failures:
        log_path = write_failures_log(failures)
        print(f"[WARN] failures={len(failures)} | log={log_path.relative_to(ROOT)}")
        raise SystemExit(1)

    print("[DONE] all experiments finished")


if __name__ == "__main__":
    main()

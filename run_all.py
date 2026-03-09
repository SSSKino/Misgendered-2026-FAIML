#!/usr/bin/env python3
"""
Pipeline runner — executes all experiments with progress tracking.
No longer uses subprocess; imports experiment functions directly.

Usage:
    python run_all.py                  # run everything
    python run_all.py --dry-run        # just print what would run
"""
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
# Add src/ to path so we can import experiment modules
sys.path.insert(0, str(ROOT / "src"))

from scoring_experiment import run_scoring
from gender_analysis import run_gender_analysis
from consistency_audit import parse_runs_from_files, run_audit
from llm_api import get_default_model, get_default_temperature

JD_ROOT = ROOT / "data" / "inputs" / "JD"
CV_ROOT = ROOT / "data" / "inputs" / "CV"
OUTPUTS_ROOT = ROOT / "data" / "outputs"
EXCLUDED_DIRS = {"gender", "pronouns"}


# ── helpers (unchanged) ──────────────────────────────────────────────

def list_industry_dirs(root: Path) -> List[Path]:
    if not root.exists():
        return []
    return sorted(
        [d for d in root.iterdir() if d.is_dir() and d.name.lower() not in EXCLUDED_DIRS],
        key=lambda x: x.name.lower(),
    )


def find_cv_variant(ind_dir: Path, needle: str) -> Path:
    matches = []
    for p in ind_dir.glob("*.json"):
        name = p.name.lower()
        if "all_variants" in name or "manifest" in name:
            continue
        if needle.lower() in name:
            matches.append(p)
    matches = sorted(matches, key=lambda x: x.name.lower())
    if not matches:
        raise FileNotFoundError(f"No CV file containing '{needle}' found in: {ind_dir}")
    return matches[0]


def list_jd_files(ind_dir: Path) -> List[Path]:
    files = []
    for p in ind_dir.glob("*.json"):
        name = p.name.lower()
        if "manifest" in name:
            continue
        # Only use onet_*.json files; skip the split-generated *_jd.json duplicates
        if not name.startswith("onet_"):
            continue
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def scoring_outputs_for_jd(out_dir: Path) -> List[Path]:
    files = []
    for p in out_dir.glob("*.json"):
        name = p.name.lower()
        if name.startswith("gender_analysis_") or "alignment_audit" in name or name == "run_manifest.json":
            continue
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def write_manifest(path: Path, manifest: Dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


# ── progress tracking ────────────────────────────────────────────────

class Progress:
    def __init__(self, total: int, dry_run: bool = False):
        self.total = total
        self.current = 0
        self.dry_run = dry_run
        self.failures: List[Dict[str, str]] = []

    def step(self, label: str) -> Optional[float]:
        """Start a step. Returns start time, or None for dry-run."""
        self.current += 1
        prefix = f"[{self.current}/{self.total}]"
        if self.dry_run:
            print(f"  {prefix} (dry-run) {label}")
            return None
        print(f"  {prefix} {label} ...", end="", flush=True)
        return time.time()

    def done(self, t0: Optional[float]) -> None:
        if t0 is None:
            return
        elapsed = time.time() - t0
        print(f" OK ({elapsed:.1f}s)")

    def fail(self, t0: Optional[float], label: str, error: str) -> None:
        if t0 is not None:
            elapsed = time.time() - t0
            print(f" FAILED ({elapsed:.1f}s)")
        else:
            print(f"  FAILED: {label}")
        print(f"         Error: {error}", file=sys.stderr)
        self.failures.append({"task": label, "error": error})

    def summary(self) -> None:
        ok = self.current - len(self.failures)
        print(f"\n{'='*60}")
        print(f"Done: {ok} succeeded, {len(self.failures)} failed, {self.total} total")
        if self.failures:
            print(f"\nFailed tasks:")
            for f in self.failures:
                print(f"  X {f['task']}")
                print(f"    {f['error']}")
        print(f"{'='*60}")


# ── main ─────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Run all experiments with progress tracking")
    ap.add_argument("--dry-run", action="store_true", help="Print task list without running anything")
    ap.add_argument("--model", default=None, help="Override model")
    ap.add_argument("--temperature", type=float, default=None, help="Override temperature")
    args = ap.parse_args()

    model = args.model or get_default_model()
    temperature = args.temperature if args.temperature is not None else get_default_temperature()

    if not JD_ROOT.exists():
        raise SystemExit(f"Missing JD root folder: {JD_ROOT}")
    if not CV_ROOT.exists():
        raise SystemExit(f"Missing CV root folder: {CV_ROOT}")

    jd_industry_dirs = {d.name: d for d in list_industry_dirs(JD_ROOT)}
    cv_industry_dirs = {d.name: d for d in list_industry_dirs(CV_ROOT)}
    shared_industries = sorted(set(jd_industry_dirs) & set(cv_industry_dirs), key=str.lower)
    if not shared_industries:
        raise SystemExit(f"No shared industry folders found between {JD_ROOT} and {CV_ROOT}.")

    gender_path = None
    # Prefer pronouns.json — it has all three groups (he/him, she/her, they/them)
    # gender.json is missing non-binary (_THEY) entries
    for candidate in [CV_ROOT / "pronouns" / "pronouns.json", CV_ROOT / "gender" / "gender.json"]:
        if candidate.exists():
            gender_path = candidate
            break

    # ── count total tasks for progress bar ──
    total_tasks = 0
    task_plan: List[Dict[str, Any]] = []
    for industry in shared_industries:
        jd_files = list_jd_files(jd_industry_dirs[industry])
        for jd_path in jd_files:
            # 5 scoring + 5 gender analysis (if gender_path) + 1 audit = 11 or 6
            n = 5 + (5 if gender_path else 0) + 1
            total_tasks += n
            task_plan.append({"industry": industry, "jd_path": jd_path})

    print(f"Pipeline: {len(shared_industries)} industries, {len(task_plan)} JD files, {total_tasks} tasks")
    print(f"Model: {model} | Temperature: {temperature}")
    if gender_path:
        print(f"Gender analysis: {gender_path.relative_to(ROOT)}")
    print()

    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    prog = Progress(total_tasks, dry_run=args.dry_run)

    overall_manifest: Dict[str, Any] = {
        "jd_root": str(JD_ROOT.relative_to(ROOT)),
        "cv_root": str(CV_ROOT.relative_to(ROOT)),
        "outputs_root": str(OUTPUTS_ROOT.relative_to(ROOT)),
        "shared_industries": shared_industries,
        "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
        "runs": [],
    }

    # ── experiment definitions: (experiment_name, cv_variant_needle, manifest_key) ──
    SCORING_EXPERIMENTS = [
        ("borderline",     "no_pronouns_gender", "exp1_borderline"),
        ("strength_test1", "no_pronouns_gender", "exp2_strength_1"),
        ("strength_test2", "no_gender",          "exp2_strength_2"),
        ("strength_test3", "_full",              "exp2_strength_3"),
        ("policy_gap",     "no_pronouns_gender", "exp3_policy_gap"),
    ]

    for industry in shared_industries:
        jd_ind_dir = jd_industry_dirs[industry]
        cv_ind_dir = cv_industry_dirs[industry]
        jd_files = list_jd_files(jd_ind_dir)
        if not jd_files:
            print(f"[warn] No JD files found under: {jd_ind_dir}")
            continue

        # resolve CV variants once per industry
        cv_variants = {
            "no_pronouns_gender": find_cv_variant(cv_ind_dir, "no_pronouns_gender"),
            "no_gender": find_cv_variant(cv_ind_dir, "no_gender"),
            "_full": find_cv_variant(cv_ind_dir, "_full"),
        }

        for jd_path in jd_files:
            jd_key = safe_stem(jd_path)
            out_dir = OUTPUTS_ROOT / industry / jd_key
            out_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n--- {industry} / {jd_key} ---")

            run_manifest: Dict[str, Any] = {
                "industry": industry,
                "jd": str(jd_path.relative_to(ROOT)),
                "cv_files": {
                    "no_pronouns_gender": str(cv_variants["no_pronouns_gender"].relative_to(ROOT)),
                    "no_gender": str(cv_variants["no_gender"].relative_to(ROOT)),
                    "full": str(cv_variants["_full"].relative_to(ROOT)),
                },
                "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
                "outputs": {},
            }

            # ── run 5 scoring experiments ──
            scoring_outputs: Dict[str, Path] = {}
            for exp_name, cv_needle, manifest_key in SCORING_EXPERIMENTS:
                out_file = out_dir / f"{exp_name}__{industry}__{jd_key}.json"
                label = f"{exp_name} | {industry}/{jd_key}"
                t0 = prog.step(label)
                if not args.dry_run:
                    try:
                        run_scoring(exp_name, jd_path, cv_variants[cv_needle], out_file, model, temperature)
                        prog.done(t0)
                        scoring_outputs[exp_name] = out_file
                        run_manifest["outputs"][manifest_key] = str(out_file.relative_to(ROOT))
                    except KeyboardInterrupt:
                        print(" INTERRUPTED")
                        prog.summary()
                        sys.exit(130)
                    except Exception as e:
                        prog.fail(t0, label, str(e))

            # ── run gender analysis for each scoring output ──
            if gender_path is not None:
                for exp_name, _, manifest_key in SCORING_EXPERIMENTS:
                    score_path = scoring_outputs.get(exp_name)
                    ga_out = out_dir / f"gender_analysis_{exp_name}__{industry}__{jd_key}.json"
                    ga_label = f"gender_analysis({exp_name}) | {industry}/{jd_key}"
                    t0 = prog.step(ga_label)
                    if not args.dry_run:
                        if score_path is None:
                            prog.fail(t0, ga_label, f"skipped: scoring for {exp_name} failed earlier")
                            continue
                        try:
                            run_gender_analysis(score_path, gender_path, ga_out)
                            prog.done(t0)
                            ga_key = f"gender_analysis_{manifest_key}"
                            run_manifest["outputs"][ga_key] = str(ga_out.relative_to(ROOT))
                        except KeyboardInterrupt:
                            print(" INTERRUPTED")
                            prog.summary()
                            sys.exit(130)
                        except Exception as e:
                            prog.fail(t0, ga_label, str(e))

            # ── run consistency audit ──
            audit_label = f"consistency_audit | {industry}/{jd_key}"
            t0 = prog.step(audit_label)
            if not args.dry_run:
                audit_inputs = scoring_outputs_for_jd(out_dir)
                if audit_inputs:
                    try:
                        runs = parse_runs_from_files([str(p) for p in audit_inputs])
                        result = run_audit(runs)
                        audit_out = out_dir / f"alignment_audit__{industry}__{jd_key}.json"
                        audit_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                        prog.done(t0)
                        run_manifest["outputs"]["exp4_alignment_audit"] = str(audit_out.relative_to(ROOT))
                    except KeyboardInterrupt:
                        print(" INTERRUPTED")
                        prog.summary()
                        sys.exit(130)
                    except Exception as e:
                        prog.fail(t0, audit_label, str(e))
                else:
                    prog.fail(t0, audit_label, "no scoring outputs to audit")

            manifest_path = out_dir / "run_manifest.json"
            write_manifest(manifest_path, run_manifest)
            overall_manifest["runs"].append(run_manifest)

    write_manifest(OUTPUTS_ROOT / "run_manifest.json", overall_manifest)
    prog.summary()

    if prog.failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

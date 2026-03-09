#!/usr/bin/env python3
"""
Pipeline runner — executes experiments with progress tracking.
Reads experiment definitions from experiment_config.json.

Usage:
    python run_all.py                          # run all experiments
    python run_all.py --only gender_aware      # run only one experiment
    python run_all.py --only "borderline,policy_gap"  # run selected experiments
    python run_all.py --dry-run                # just print what would run
    python run_all.py --list                   # list available experiments
"""
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
# Add src/ to path so we can import experiment modules
sys.path.insert(0, str(ROOT / "src"))

from scoring_experiment import run_scoring, load_experiment_config
from gender_analysis import run_gender_analysis
from consistency_audit import parse_runs_from_files, run_audit
from llm_api import get_default_model, get_default_temperature

JD_ROOT = ROOT / "data" / "inputs" / "JD"
CV_ROOT = ROOT / "data" / "inputs" / "CV"
OUTPUTS_ROOT = ROOT / "data" / "outputs"
EXCLUDED_DIRS = {"gender", "pronouns"}


# ── helpers ─────────────────────────────────────────────────────────

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
    ap = argparse.ArgumentParser(description="Run experiments with progress tracking")
    ap.add_argument("--dry-run", action="store_true", help="Print task list without running anything")
    ap.add_argument("--model", default=None, help="Override model")
    ap.add_argument("--temperature", type=float, default=None, help="Override temperature")
    ap.add_argument("--only", default=None,
                     help="Run only specific experiments (comma-separated names, e.g. 'borderline,policy_gap')")
    ap.add_argument("--industry", default=None,
                     help="Run only specific industries (comma-separated, e.g. 'Construction,IT')")
    ap.add_argument("--list", action="store_true", help="List available experiments and exit")
    args = ap.parse_args()

    # ── load experiment config ──
    cfg = load_experiment_config()
    all_experiments = cfg.get("experiments", [])

    if args.list:
        print("Available experiments (from experiment_config.json):")
        for exp in all_experiments:
            print(f"  {exp['name']:20s}  prompt={exp['prompt']:15s}  cv={exp['cv_variant']}")
        sys.exit(0)

    # ── filter experiments if --only is given ──
    if args.only:
        only_names = set(s.strip() for s in args.only.split(","))
        known_names = {e["name"] for e in all_experiments}
        unknown = only_names - known_names
        if unknown:
            raise SystemExit(f"Unknown experiment(s): {sorted(unknown)}. Use --list to see available names.")
        experiments = [e for e in all_experiments if e["name"] in only_names]
    else:
        experiments = all_experiments

    # ── resolve model/temperature: CLI > config > api_settings ──
    model = args.model or cfg.get("model") or get_default_model()
    temperature = args.temperature if args.temperature is not None else cfg.get("temperature", get_default_temperature())
    temperature = float(temperature)

    if not JD_ROOT.exists():
        raise SystemExit(f"Missing JD root folder: {JD_ROOT}")
    if not CV_ROOT.exists():
        raise SystemExit(f"Missing CV root folder: {CV_ROOT}")

    jd_industry_dirs = {d.name: d for d in list_industry_dirs(JD_ROOT)}
    cv_industry_dirs = {d.name: d for d in list_industry_dirs(CV_ROOT)}
    shared_industries = sorted(set(jd_industry_dirs) & set(cv_industry_dirs), key=str.lower)
    if not shared_industries:
        raise SystemExit(f"No shared industry folders found between {JD_ROOT} and {CV_ROOT}.")

    # ── filter industries if --industry is given ──
    if args.industry:
        requested = [s.strip() for s in args.industry.split(",")]
        # case-insensitive match
        available_lower = {name.lower(): name for name in shared_industries}
        filtered = []
        unknown = []
        for r in requested:
            match = available_lower.get(r.lower())
            if match:
                filtered.append(match)
            else:
                unknown.append(r)
        if unknown:
            raise SystemExit(f"Unknown industry: {unknown}. Available: {shared_industries}")
        shared_industries = filtered

    gender_path = None
    # Prefer pronouns.json — it has all three groups (he/him, she/her, they/them)
    # gender.json is missing non-binary (_THEY) entries
    for candidate in [CV_ROOT / "pronouns" / "pronouns.json", CV_ROOT / "gender" / "gender.json"]:
        if candidate.exists():
            gender_path = candidate
            break

    # ── collect needed CV variants ──
    needed_variants = set(e["cv_variant"] for e in experiments)

    # ── count total tasks for progress bar ──
    n_exp = len(experiments)
    total_tasks = 0
    task_plan: List[Dict[str, Any]] = []
    for industry in shared_industries:
        jd_files = list_jd_files(jd_industry_dirs[industry])
        for jd_path in jd_files:
            n = n_exp + (n_exp if gender_path else 0) + 1  # scoring + gender_analysis + audit
            total_tasks += n
            task_plan.append({"industry": industry, "jd_path": jd_path})

    exp_names = [e["name"] for e in experiments]
    print(f"Pipeline: {len(shared_industries)} industries, {len(task_plan)} JD files, {total_tasks} tasks")
    print(f"Experiments: {', '.join(exp_names)}")
    print(f"Model: {model} | Temperature: {temperature}")
    if gender_path:
        print(f"Gender analysis: {gender_path.relative_to(ROOT)}")
    print()

    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    prog = Progress(total_tasks, dry_run=args.dry_run)
    pipeline_t0 = time.time()
    all_usage: List[Dict[str, Any]] = []  # collect _usage from each scoring call

    overall_manifest: Dict[str, Any] = {
        "jd_root": str(JD_ROOT.relative_to(ROOT)),
        "cv_root": str(CV_ROOT.relative_to(ROOT)),
        "outputs_root": str(OUTPUTS_ROOT.relative_to(ROOT)),
        "shared_industries": shared_industries,
        "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
        "experiments_run": exp_names,
        "runs": [],
    }

    for industry in shared_industries:
        jd_ind_dir = jd_industry_dirs[industry]
        cv_ind_dir = cv_industry_dirs[industry]
        jd_files = list_jd_files(jd_ind_dir)
        if not jd_files:
            print(f"[warn] No JD files found under: {jd_ind_dir}")
            continue

        # resolve only the CV variants needed by selected experiments
        cv_variants: Dict[str, Path] = {}
        for v in needed_variants:
            cv_variants[v] = find_cv_variant(cv_ind_dir, v)

        for jd_path in jd_files:
            jd_key = safe_stem(jd_path)
            out_dir = OUTPUTS_ROOT / industry / jd_key
            out_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n--- {industry} / {jd_key} ---")

            run_manifest: Dict[str, Any] = {
                "industry": industry,
                "jd": str(jd_path.relative_to(ROOT)),
                "cv_files": {v: str(cv_variants[v].relative_to(ROOT)) for v in needed_variants},
                "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
                "outputs": {},
            }

            # ── run scoring experiments ──
            scoring_outputs: Dict[str, Path] = {}
            for exp in experiments:
                exp_name = exp["name"]
                cv_needle = exp["cv_variant"]
                manifest_key = exp["manifest_key"]
                out_file = out_dir / f"{exp_name}__{industry}__{jd_key}.json"
                label = f"{exp_name} | {industry}/{jd_key}"
                t0 = prog.step(label)
                if not args.dry_run:
                    try:
                        result = run_scoring(exp_name, jd_path, cv_variants[cv_needle], out_file, model, temperature)
                        prog.done(t0)
                        scoring_outputs[exp_name] = out_file
                        run_manifest["outputs"][manifest_key] = str(out_file.relative_to(ROOT))
                        if "_usage" in result:
                            all_usage.append(result["_usage"])
                    except KeyboardInterrupt:
                        print(" INTERRUPTED")
                        prog.summary()
                        sys.exit(130)
                    except Exception as e:
                        prog.fail(t0, label, str(e))

            # ── run gender analysis for each scoring output ──
            if gender_path is not None:
                for exp in experiments:
                    exp_name = exp["name"]
                    manifest_key = exp["manifest_key"]
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

    # ── token & time summary ──
    pipeline_elapsed = round(time.time() - pipeline_t0, 1)
    total_prompt = sum(u.get("prompt_tokens") or 0 for u in all_usage)
    total_completion = sum(u.get("completion_tokens") or 0 for u in all_usage)
    total_tokens = sum(u.get("total_tokens") or 0 for u in all_usage)
    total_api_time = round(sum(u.get("elapsed_seconds") or 0 for u in all_usage), 1)

    overall_manifest["token_summary"] = {
        "api_calls": len(all_usage),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "api_time_seconds": total_api_time,
        "pipeline_time_seconds": pipeline_elapsed,
    }

    write_manifest(OUTPUTS_ROOT / "run_manifest.json", overall_manifest)
    prog.summary()

    if all_usage:
        print(f"\nToken usage: {total_prompt:,} prompt + {total_completion:,} completion = {total_tokens:,} total")
        print(f"API time: {total_api_time}s | Pipeline total: {pipeline_elapsed}s ({len(all_usage)} calls)")

    if prog.failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

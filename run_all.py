#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent
JD_ROOT = ROOT / "data" / "inputs" / "JD"
CV_ROOT = ROOT / "data" / "inputs" / "CV"
OUTPUTS_ROOT = ROOT / "data" / "outputs"
EXCLUDED_DIRS = {"gender", "pronouns"}


def run(cmd: List[str]) -> None:
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))


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
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def scoring_outputs_for_jd(out_dir: Path) -> List[Path]:
    files = []
    for p in out_dir.glob("*.json"):
        name = p.name.lower()
        if name.startswith("gender_analysis_"):
            continue
        if "alignment_audit" in name:
            continue
        if name == "run_manifest.json":
            continue
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())


def safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def write_manifest(path: Path, manifest: Dict) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    py = sys.executable

    if not JD_ROOT.exists():
        raise SystemExit(f"Missing JD root folder: {JD_ROOT}")
    if not CV_ROOT.exists():
        raise SystemExit(f"Missing CV root folder: {CV_ROOT}")

    jd_industry_dirs = {d.name: d for d in list_industry_dirs(JD_ROOT)}
    cv_industry_dirs = {d.name: d for d in list_industry_dirs(CV_ROOT)}
    shared_industries = sorted(set(jd_industry_dirs) & set(cv_industry_dirs), key=str.lower)
    if not shared_industries:
        raise SystemExit(
            f"No shared industry folders found between {JD_ROOT} and {CV_ROOT}."
        )

    gender_path = None
    for candidate in [CV_ROOT / "gender" / "gender.json", CV_ROOT / "pronouns" / "pronouns.json"]:
        if candidate.exists():
            gender_path = candidate
            break

    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)

    overall_manifest = {
        "jd_root": str(JD_ROOT.relative_to(ROOT)),
        "cv_root": str(CV_ROOT.relative_to(ROOT)),
        "outputs_root": str(OUTPUTS_ROOT.relative_to(ROOT)),
        "shared_industries": shared_industries,
        "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
        "runs": [],
    }

    for industry in shared_industries:
        jd_ind_dir = jd_industry_dirs[industry]
        cv_ind_dir = cv_industry_dirs[industry]
        jd_files = list_jd_files(jd_ind_dir)
        if not jd_files:
            print(f"[warn] No JD files found under: {jd_ind_dir}")
            continue

        cv_no_pg = find_cv_variant(cv_ind_dir, "no_pronouns_gender")
        cv_no_g = find_cv_variant(cv_ind_dir, "no_gender")
        cv_full = find_cv_variant(cv_ind_dir, "_full")

        for jd_path in jd_files:
            jd_key = safe_stem(jd_path)
            out_dir = OUTPUTS_ROOT / industry / jd_key
            out_dir.mkdir(parents=True, exist_ok=True)

            run_manifest = {
                "industry": industry,
                "jd": str(jd_path.relative_to(ROOT)),
                "cv_files": {
                    "no_pronouns_gender": str(cv_no_pg.relative_to(ROOT)),
                    "no_gender": str(cv_no_g.relative_to(ROOT)),
                    "full": str(cv_full.relative_to(ROOT)),
                },
                "group_analysis_file": None if gender_path is None else str(gender_path.relative_to(ROOT)),
                "outputs": {},
            }

            borderline_out = out_dir / f"borderline__{industry}__{jd_key}.json"
            run([py, "src/borderline.py", str(jd_path), str(cv_no_pg), "--out", str(borderline_out)])
            run_manifest["outputs"]["exp1_borderline"] = str(borderline_out.relative_to(ROOT))

            st1_out = out_dir / f"Strength_Test1__{industry}__{jd_key}.json"
            run([py, "src/Strength Test1.py", str(jd_path), str(cv_no_pg), "--out", str(st1_out)])
            run_manifest["outputs"]["exp2_strength_1"] = str(st1_out.relative_to(ROOT))

            st2_out = out_dir / f"Strength_Test2__{industry}__{jd_key}.json"
            run([py, "src/Strength Test2.py", str(jd_path), str(cv_no_g), "--out", str(st2_out)])
            run_manifest["outputs"]["exp2_strength_2"] = str(st2_out.relative_to(ROOT))

            st3_out = out_dir / f"Strength_Test3__{industry}__{jd_key}.json"
            run([py, "src/Strength Test3.py", str(jd_path), str(cv_full), "--out", str(st3_out)])
            run_manifest["outputs"]["exp2_strength_3"] = str(st3_out.relative_to(ROOT))

            pgt_out = out_dir / f"Policy_Gap_Test__{industry}__{jd_key}.json"
            run([py, "src/Policy Gap Test.py", str(jd_path), str(cv_no_pg), "--out", str(pgt_out)])
            run_manifest["outputs"]["exp3_policy_gap"] = str(pgt_out.relative_to(ROOT))

            if gender_path is not None:
                ga_files = [
                    ("src/gender_analysis_borderline.py", borderline_out, out_dir / f"gender_analysis_borderline__{industry}__{jd_key}.json", "gender_analysis_exp1_borderline"),
                    ("src/gender_analysis_Strength Test1.py", st1_out, out_dir / f"gender_analysis_Strength_Test1__{industry}__{jd_key}.json", "gender_analysis_exp2_strength_1"),
                    ("src/gender_analysis_Strength Test2.py", st2_out, out_dir / f"gender_analysis_Strength_Test2__{industry}__{jd_key}.json", "gender_analysis_exp2_strength_2"),
                    ("src/gender_analysis_Strength Test3.py", st3_out, out_dir / f"gender_analysis_Strength_Test3__{industry}__{jd_key}.json", "gender_analysis_exp2_strength_3"),
                    ("src/gender_analysis_Policy Gap Test.py", pgt_out, out_dir / f"gender_analysis_Policy_Gap_Test__{industry}__{jd_key}.json", "gender_analysis_exp3_policy_gap"),
                ]
                for script_path, score_path, out_path, key in ga_files:
                    run([py, script_path, str(score_path), str(gender_path), "--out", str(out_path)])
                    run_manifest["outputs"][key] = str(out_path.relative_to(ROOT))

            audit_inputs = scoring_outputs_for_jd(out_dir)
            if audit_inputs:
                audit_out = out_dir / f"alignment_audit__{industry}__{jd_key}.json"
                run([py, "src/consistency_audit.py", *[str(p) for p in audit_inputs], "--out", str(audit_out)])
                run_manifest["outputs"]["exp4_alignment_audit"] = str(audit_out.relative_to(ROOT))

            manifest_path = out_dir / "run_manifest.json"
            write_manifest(manifest_path, run_manifest)
            overall_manifest["runs"].append(run_manifest)

    write_manifest(OUTPUTS_ROOT / "run_manifest.json", overall_manifest)


if __name__ == "__main__":
    main()

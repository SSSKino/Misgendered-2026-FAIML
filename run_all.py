\
#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def run(cmd):
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))

def find_one(ind_dir: Path, needle: str) -> Path:
    """
    Find one JSON file in ind_dir whose name contains `needle`.
    Ignores *_all_variants.json.
    If multiple match, picks the first in sorted order.
    """
    matches = []
    for p in ind_dir.glob("*.json"):
        name = p.name
        if "all_variants" in name:
            continue
        if needle in name:
            matches.append(p)
    matches = sorted(matches, key=lambda x: x.name.lower())
    if not matches:
        raise FileNotFoundError(f"No input file containing '{needle}' found in: {ind_dir}")
    return matches[0]

def scoring_outputs_for_industry(out_dir: Path):
    """
    Collect scoring outputs for audit (exclude gender_analysis and existing audit outputs).
    """
    files = []
    for p in out_dir.glob("*.json"):
        name = p.name.lower()
        if name.startswith("gender_analysis_"):
            continue
        if "alignment_audit" in name:
            continue
        files.append(p)
    return sorted(files, key=lambda x: x.name.lower())

def main():
    py = sys.executable

    jd_path = ROOT / "data" / "inputs" / "jd.json"
    candidates_root = ROOT / "data" / "inputs" / "candidates"
    gender_path = candidates_root / "gender" / "gender.json"

    if not jd_path.exists():
        raise SystemExit(f"Missing JD file: {jd_path}")
    if not candidates_root.exists():
        raise SystemExit(f"Missing candidates root folder: {candidates_root}")
    if not gender_path.exists():
        raise SystemExit(
            f"Missing gender file: {gender_path} "
            "(expected under data/inputs/candidates/gender/gender.json)"
        )

    industry_dirs = sorted(
        [d for d in candidates_root.iterdir() if d.is_dir() and d.name.lower() != "gender"],
        key=lambda x: x.name.lower(),
    )
    if not industry_dirs:
        raise SystemExit(f"No industry folders found under: {candidates_root}")

    outputs_root = ROOT / "data" / "outputs"
    outputs_root.mkdir(parents=True, exist_ok=True)

    for ind_dir in industry_dirs:
        industry = ind_dir.name
        out_dir = outputs_root / industry
        out_dir.mkdir(parents=True, exist_ok=True)

        inp_no_pg = find_one(ind_dir, "no_pronouns_gender")
        inp_no_g = find_one(ind_dir, "no_gender")
        inp_full = find_one(ind_dir, "_full")

        # Exp1: borderline -> gender analysis
        borderline_out = out_dir / f"borderline_{industry}.json"
        run([py, "src/borderline.py", str(jd_path), str(inp_no_pg), "--out", str(borderline_out)])
        borderline_gender_out = out_dir / f"gender_analysis_borderline_{industry}.json"
        run([py, "src/gender_analysis_borderline.py", str(borderline_out), str(gender_path), "--out", str(borderline_gender_out)])

        # Strength Test1 -> gender analysis
        st1_out = out_dir / f"Strength Test1_{industry}.json"
        run([py, "src/Strength Test1.py", str(jd_path), str(inp_no_pg), "--out", str(st1_out)])
        st1_gender_out = out_dir / f"gender_analysis_Strength Test1_{industry}.json"
        run([py, "src/gender_analysis_Strength Test1.py", str(st1_out), str(gender_path), "--out", str(st1_gender_out)])

        # Strength Test2 -> gender analysis
        st2_out = out_dir / f"Strength Test2_{industry}.json"
        run([py, "src/Strength Test2.py", str(jd_path), str(inp_no_g), "--out", str(st2_out)])
        st2_gender_out = out_dir / f"gender_analysis_Strength Test2_{industry}.json"
        run([py, "src/gender_analysis_Strength Test2.py", str(st2_out), str(gender_path), "--out", str(st2_gender_out)])

        # Strength Test3 -> gender analysis
        st3_out = out_dir / f"Strength Test3_{industry}.json"
        run([py, "src/Strength Test3.py", str(jd_path), str(inp_full), "--out", str(st3_out)])
        st3_gender_out = out_dir / f"gender_analysis_Strength Test3_{industry}.json"
        run([py, "src/gender_analysis_Strength Test3.py", str(st3_out), str(gender_path), "--out", str(st3_gender_out)])

        # Policy Gap Test -> gender analysis
        pgt_out = out_dir / f"Policy Gap Test_{industry}.json"
        run([py, "src/Policy Gap Test.py", str(jd_path), str(inp_no_pg), "--out", str(pgt_out)])
        pgt_gender_out = out_dir / f"gender_analysis_Policy Gap Test_{industry}.json"
        run([py, "src/gender_analysis_Policy Gap Test.py", str(pgt_out), str(gender_path), "--out", str(pgt_gender_out)])

        # Audit per industry
        audit_inputs = scoring_outputs_for_industry(out_dir)
        if audit_inputs:
            audit_out = out_dir / f"alignment_audit_{industry}.json"
            run([py, "src/consistency_audit.py", *[str(p) for p in audit_inputs], "--out", str(audit_out)])
        else:
            print(f"[warn] No scoring outputs found for audit in: {out_dir}")

if __name__ == "__main__":
    main()

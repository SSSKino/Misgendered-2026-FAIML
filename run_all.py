#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def run(cmd):
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))

def main():
    py = sys.executable

    # Experiment 1: borderline -> then gender analysis
    run([py, "src/borderline.py", "data/inputs/jd.json", "data/inputs/candidates.json",
         "--out", "data/outputs/exp1_borderline/borderline.json"])
    run([py, "src/gender_analysis_borderline.py", "data/outputs/exp1_borderline/borderline.json", "data/inputs/gender.json",
         "--out", "data/outputs/exp1_borderline/gender_analysis_borderline"])

    # Experiment 2: Strength Tests 1-3 -> each followed immediately by its gender analysis
    for name in ("Strength Test1", "Strength Test2", "Strength Test3"):
        run([py, f"src/{name}.py", "data/inputs/jd.json", "data/inputs/candidates.json",
             "--out", f"data/outputs/exp2_strength/{name}.json"])
        run([py, f"src/gender_analysis_{name}.py", f"data/outputs/exp2_strength/{name}.json", "data/inputs/gender.json",
             "--out", f"data/outputs/exp2_strength/gender_analysis_{name}"])

    # Experiment 3: Policy Gap Test -> then gender analysis
    run([py, "src/Policy Gap Test.py", "data/inputs/jd.json", "data/inputs/candidates.json",
         "--out", "data/outputs/exp3_policy_gap/Policy Gap Test.json"])
    run([py, "src/gender_analysis_Policy Gap Test.py", "data/outputs/exp3_policy_gap/Policy Gap Test.json", "data/inputs/gender.json",
         "--out", "data/outputs/exp3_policy_gap/gender_analysis_Policy Gap Test"])

    # Experiment 4: consistency_audit (run after Exp1–Exp3 + their gender analyses)
    run([py, "src/consistency_audit.py", "--out", "data/outputs/exp4_audit/alignment_audit.json"])

if __name__ == "__main__":
    main()

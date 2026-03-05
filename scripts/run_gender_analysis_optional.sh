#!/usr/bin/env bash
set -euo pipefail

# Optional: run gender_analysis AFTER you have outputs and you want group stats/deltas.
python src/gender_analysis_borderline.py data/outputs/exp1_borderline/borderline.json data/inputs/gender.json --out data/outputs/exp1_borderline/gender_analysis_borderline

python "src/gender_analysis_Strength Test1.py" "data/outputs/exp2_strength/Strength Test1.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test1"
python "src/gender_analysis_Strength Test2.py" "data/outputs/exp2_strength/Strength Test2.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test2"
python "src/gender_analysis_Strength Test3.py" "data/outputs/exp2_strength/Strength Test3.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test3"

python "src/gender_analysis_Policy Gap Test.py" "data/outputs/exp3_policy_gap/Policy Gap Test.json" data/inputs/gender.json --out "data/outputs/exp3_policy_gap/gender_analysis_Policy Gap Test"

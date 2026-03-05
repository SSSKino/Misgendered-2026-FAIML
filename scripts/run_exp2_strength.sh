#!/usr/bin/env bash
set -euo pipefail

python "src/Strength Test1.py" data/inputs/jd.json data/inputs/candidates.json --out "data/outputs/exp2_strength/Strength Test1.json"
python "src/gender_analysis_Strength Test1.py" "data/outputs/exp2_strength/Strength Test1.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test1"

python "src/Strength Test2.py" data/inputs/jd.json data/inputs/candidates.json --out "data/outputs/exp2_strength/Strength Test2.json"
python "src/gender_analysis_Strength Test2.py" "data/outputs/exp2_strength/Strength Test2.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test2"

python "src/Strength Test3.py" data/inputs/jd.json data/inputs/candidates.json --out "data/outputs/exp2_strength/Strength Test3.json"
python "src/gender_analysis_Strength Test3.py" "data/outputs/exp2_strength/Strength Test3.json" data/inputs/gender.json --out "data/outputs/exp2_strength/gender_analysis_Strength Test3"

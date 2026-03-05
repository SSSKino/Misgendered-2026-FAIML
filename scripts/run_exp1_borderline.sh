#!/usr/bin/env bash
set -euo pipefail
python src/borderline.py data/inputs/jd.json data/inputs/candidates.json --out data/outputs/exp1_borderline/borderline.json
python src/gender_analysis_borderline.py data/outputs/exp1_borderline/borderline.json data/inputs/gender.json --out data/outputs/exp1_borderline/gender_analysis_borderline

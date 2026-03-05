#!/usr/bin/env bash
set -euo pipefail
python src/borderline.py data/inputs/jd.json data/inputs/candidates.json --out data/outputs/exp1_borderline/borderline.json

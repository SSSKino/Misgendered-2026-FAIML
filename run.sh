#!/usr/bin/env bash
set -euo pipefail

python src/strength_test3.py \
  data/inputs/Nursing_JD.txt \
  data/inputs/Nursing_full.json \
  --out data/outputs/Strength_Test3.json

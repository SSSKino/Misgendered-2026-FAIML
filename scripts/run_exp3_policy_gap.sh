#!/usr/bin/env bash
set -euo pipefail
python "src/Policy Gap Test.py" data/inputs/jd.json data/inputs/candidates.json --out "data/outputs/exp3_policy_gap/Policy Gap Test.json"

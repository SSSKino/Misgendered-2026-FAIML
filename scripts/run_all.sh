#!/usr/bin/env bash
set -euo pipefail
bash scripts/run_exp1_borderline.sh
bash scripts/run_exp2_strength.sh
bash scripts/run_exp3_policy_gap.sh
bash scripts/run_exp4_audit.sh

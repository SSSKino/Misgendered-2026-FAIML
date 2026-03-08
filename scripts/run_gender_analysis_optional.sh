#!/usr/bin/env bash
set -euo pipefail
echo "Group analysis is now handled automatically by run_all.py when gender.json or pronouns.json exists under data/inputs/CV/."
python run_all.py

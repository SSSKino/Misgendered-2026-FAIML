# Recruitment Bias Experiments — 4 Experiments (Exp1–Exp4)

This project contains **four experiments**:

- **Experiment 1 (Exp1): `borderline`**
  - Script: `src/borderline.py`
  - Output: `data/outputs/exp1_borderline/borderline.json`

- **Experiment 2 (Exp2): Strength Tests 1–3**
  - Scripts:
    - `src/Strength Test1.py`
    - `src/Strength Test2.py`
    - `src/Strength Test3.py`
  - Outputs:
    - `data/outputs/exp2_strength/Strength Test1.json`
    - `data/outputs/exp2_strength/Strength Test2.json`
    - `data/outputs/exp2_strength/Strength Test3.json`

- **Experiment 3 (Exp3): Policy Gap Test**
  - Script: `src/Policy Gap Test.py`
  - Output: `data/outputs/exp3_policy_gap/Policy Gap Test.json`

- **Experiment 4 (Exp4): Consistency Audit (tie-score alignment + rationale labels)**
  - Script: `src/consistency_audit.py`
  - IMPORTANT: **Run Exp4 only after Exp1–Exp3 outputs are generated.**
  - Output: `data/outputs/exp4_audit/alignment_audit.json`

## Inputs
Place input files in `data/inputs/`:
- `jd.json`
- `candidates.json`
- `gender.json`

## Setup
```bash
pip install -r requirements.txt
export OPENAI_API_KEY="YOUR_KEY"
```

## Run order (recommended)
### One command (cross-platform)
```bash
python run_all.py
```
This runs **Exp1 → Exp2 → Exp3 → Exp4** in order.

### Or step-by-step (bash)
```bash
bash scripts/run_exp1_borderline.sh
bash scripts/run_exp2_strength.sh
bash scripts/run_exp3_policy_gap.sh
bash scripts/run_exp4_audit.sh
```

## Gender analysis (runs immediately after each experiment)
Each experiment run is immediately followed by its corresponding gender analysis script.


## Notes
- Some scripts have spaces in file names. When running manually in a shell, use quotes:
  - `python "src/Policy Gap Test.py" ...`


## Output format update
Scoring scripts now output a top-level JSON array of candidates (no wrapping object).

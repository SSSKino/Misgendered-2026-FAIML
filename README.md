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

## Gender analysis (optional; DO NOT run by default)
Gender analysis scripts are included for later use, but **not executed** in the default pipeline:
```bash
bash scripts/run_gender_analysis_optional.sh
```
They will write group statistics + deltas beside the corresponding outputs.

## Notes
- Some scripts have spaces in file names. When running manually in a shell, use quotes:
  - `python "src/Policy Gap Test.py" ...`


## Industry-based inputs and outputs (updated)

Inputs are expected under:

- `data/inputs/candidates/<industry>/` (e.g. construction, IT, nursing)
- `data/inputs/candidates/gender/gender.json`

For each industry folder, the pipeline selects inputs by filename:
- `borderline.py` uses `*no_pronouns_gender*.json`
- `Strength Test1.py` uses `*no_pronouns_gender*.json`
- `Strength Test2.py` uses `*no_gender*.json`
- `Strength Test3.py` uses `*_full*.json`
- `Policy Gap Test.py` uses `*no_pronouns_gender*.json`

Outputs are written per industry to:
- `data/outputs/<industry>/`

Each output filename includes the industry name, e.g.:
- `borderline_IT.json`
- `gender_analysis_borderline_IT.json`


## Consistency audit (per industry)

`run_all.py` now runs the audit **for each industry separately** after finishing that industry's runs.

Audit outputs:
- `data/outputs/<industry>/alignment_audit_<industry>.json`

The audit input set for each industry includes only scoring outputs (excludes `gender_analysis_*.json` and existing audit files).

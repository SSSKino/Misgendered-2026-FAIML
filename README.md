# Recruitment Bias Experiments — Industry-aligned JD × CV Pipeline

This project runs the full experiment suite by **matching JD and CV files within the same industry** and processing them in a fixed order.

## What changed
- Input root `data/inputs/candidates/` is now renamed to `data/inputs/CV/`.
- Single-file `data/inputs/jd.json` is replaced by per-industry JD folders under `data/inputs/JD/`.
- `run_all.py` now loops as:
  1. find shared industries between `data/inputs/JD/` and `data/inputs/CV/`
  2. for each JD JSON inside an industry folder
  3. pair that JD with the same-industry CV variant files
  4. run **Exp1 → Exp2(1/2/3) → Exp3 → gender analysis (if present) → Exp4 audit**
- Outputs are written to `data/outputs/<industry>/<jd_stem>/` so results from different JD files never overwrite each other.

## Expected input structure

```text
project_root/
├─ data/
│  └─ inputs/
│     ├─ CV/
│     │  ├─ gender/
│     │  │  └─ gender.json              # optional
│     │  ├─ pronouns/
│     │  │  └─ pronouns.json            # optional fallback for group analysis
│     │  ├─ IT/
│     │  │  ├─ IT_no_pronouns_gender.json
│     │  │  ├─ IT_no_gender.json
│     │  │  └─ IT_full.json
│     │  ├─ Construction/
│     │  └─ Nursing/
│     └─ JD/
│        ├─ IT/
│        │  ├─ IT_jd.json
│        │  ├─ IT_jd_2.json
│        │  └─ ...
│        ├─ Construction/
│        └─ Nursing/
```

## CV variant selection rules
For each industry:
- `borderline.py` uses `*no_pronouns_gender*.json`
- `Strength Test1.py` uses `*no_pronouns_gender*.json`
- `Strength Test2.py` uses `*no_gender*.json`
- `Strength Test3.py` uses `*_full*.json`
- `Policy Gap Test.py` uses `*no_pronouns_gender*.json`

## Run order

### One command
```bash
python run_all.py
```

The pipeline runs each JD in this order:
1. Exp1: `src/borderline.py`
2. Exp2-1: `src/Strength Test1.py`
3. Exp2-2: `src/Strength Test2.py`
4. Exp2-3: `src/Strength Test3.py`
5. Exp3: `src/Policy Gap Test.py`
6. Group analysis scripts if `gender.json` or `pronouns.json` exists under `data/inputs/CV/`
7. Exp4: `src/consistency_audit.py`

## Output structure

```text
data/outputs/
├─ IT/
│  ├─ IT_jd/
│  │  ├─ borderline__IT__IT_jd.json
│  │  ├─ Strength_Test1__IT__IT_jd.json
│  │  ├─ Strength_Test2__IT__IT_jd.json
│  │  ├─ Strength_Test3__IT__IT_jd.json
│  │  ├─ Policy_Gap_Test__IT__IT_jd.json
│  │  ├─ gender_analysis_*.json        # if group file exists
│  │  ├─ alignment_audit__IT__IT_jd.json
│  │  └─ run_manifest.json
│  └─ IT_jd_2/
└─ run_manifest.json
```

## Setup
```bash
pip install -r requirements.txt
cp config/.env.example config/.env
# Then open config/.env and fill in OPENAI_API_KEY
```

On Windows PowerShell you can also copy it with:
```powershell
Copy-Item config/.env.example config/.env
```

## Notes
- All experiment scripts now read **CV JSON** inputs instead of the old `candidates` naming.
- The scoring result schema is still kept as `{"candidates": [...]}` to preserve compatibility with downstream audit scripts.
- If `data/inputs/CV/gender/gender.json` does not exist, the runner will try `data/inputs/CV/pronouns/pronouns.json` for group analysis.
- If neither exists, the main experiments still run and only group analysis is skipped.



## API key via .env
- Put your real key in the `config/.env` file under the project root.
- The unified client in `src/llm_api.py` loads `config/.env` automatically on import.
- `OPENAI_API_KEY` is required before any experiment can call the API.
- `config/.env` is ignored by Git, while `config/.env.example` is safe to commit as a template.

## Unified API configuration
All experiment scripts now share one centralized API layer:
- runtime client + request builder: `src/llm_api.py`
- project-level defaults: `api_settings.json`

So if you need to change the model, temperature, base URL, timeout, retries, or OpenAI org/project, you only change **one place**.

Example `api_settings.json`:

```json
{
  "model": "gpt-5.2",
  "temperature": 0.2,
  "max_output_tokens": null,
  "timeout": null,
  "max_retries": 2,
  "base_url": null,
  "organization": null,
  "project": null
}
```

`config/.env` is loaded automatically from the project root. Real environment variables still override both `.env` and `api_settings.json`.

Supported environment variables:
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` or `RECRUITMENT_API_BASE_URL`
- `RECRUITMENT_API_MODEL`
- `RECRUITMENT_API_TEMPERATURE`
- `RECRUITMENT_API_TIMEOUT`
- `RECRUITMENT_API_MAX_RETRIES`
- `OPENAI_ORG_ID` / `RECRUITMENT_API_ORG`
- `OPENAI_PROJECT` / `RECRUITMENT_API_PROJECT`

CLI `--model` and `--temperature` are still supported, but their defaults now come from `api_settings.json`.

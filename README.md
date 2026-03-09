# Recruitment Bias Experiments — Industry-aligned JD × CV Pipeline

This project runs the full experiment suite by **matching JD and CV files within the same industry** and processing them in a fixed order.

## Quick start

```bash
pip install -r requirements.txt
cp config/.env.example config/.env
# Fill in OPENAI_API_KEY in config/.env
```

## Usage

```bash
python run_all.py                                  # run all experiments
python run_all.py --only gender_aware              # run only one experiment
python run_all.py --only "borderline,policy_gap"   # run selected experiments
python run_all.py --industry Construction          # run only one industry
python run_all.py --industry "IT,Nursing"          # run selected industries
python run_all.py --industry IT --only policy_gap  # combine both filters
python run_all.py --list                           # list available experiments
python run_all.py --dry-run                        # preview without executing
python run_all.py --model qwen-plus --temperature 0  # override model/temperature
```

## Experiment configuration

All experiment definitions and prompts are in **`experiment_config.json`** (project root). To change prompts, add/remove experiments, or switch models — edit this file, no Python changes needed.

```json
{
  "prompts": {
    "default": "You are a professional recruitment consultant...",
    "policy_gap": "{default}\n\nWe are an equal opportunity employer...",
    "gender_aware": "{default}\n\nWhen evaluating candidates, please take into account..."
  },
  "experiments": [
    {"name": "borderline",      "prompt": "default",      "cv_variant": "no_pronouns_gender", "manifest_key": "exp1_borderline"},
    {"name": "strength_test1",  "prompt": "default",      "cv_variant": "no_pronouns_gender", "manifest_key": "exp2_strength_1"},
    {"name": "strength_test2",  "prompt": "default",      "cv_variant": "no_gender",          "manifest_key": "exp2_strength_2"},
    {"name": "strength_test3",  "prompt": "default",      "cv_variant": "_full",              "manifest_key": "exp2_strength_3"},
    {"name": "policy_gap",      "prompt": "policy_gap",   "cv_variant": "no_pronouns_gender", "manifest_key": "exp3_policy_gap"},
    {"name": "gender_aware",    "prompt": "gender_aware",  "cv_variant": "_full",              "manifest_key": "exp5_gender_aware"}
  ],
  "model": "qwen-plus",
  "temperature": 0
}
```

- **Prompts** support `{default}` placeholder — it expands to the `default` prompt text, so you don't repeat the base prompt.
- **Adding a new experiment**: add an entry to `experiments` array and (optionally) a new prompt key.
- **Model/temperature** priority: CLI flags > `experiment_config.json` > `api_settings.json` > environment variables.

## Expected input structure

```text
project_root/
├─ experiment_config.json          # experiment & prompt definitions
├─ api_settings.json               # API defaults (model, temperature, etc.)
├─ config/.env                     # API key (git-ignored)
├─ data/
│  └─ inputs/
│     ├─ CV/
│     │  ├─ gender/
│     │  │  └─ gender.json              # optional
│     │  ├─ pronouns/
│     │  │  └─ pronouns.json            # preferred for group analysis (has non-binary)
│     │  ├─ IT/
│     │  │  ├─ IT_no_pronouns_gender.json
│     │  │  ├─ IT_no_gender.json
│     │  │  └─ IT_full.json
│     │  ├─ Construction/
│     │  └─ Nursing/
│     └─ JD/
│        ├─ IT/
│        │  └─ onet_it_jobs.json
│        ├─ Construction/
│        └─ Nursing/
```

## Pipeline flow

For each industry × JD combination, the pipeline runs:

1. **Scoring experiments** — sends JD + CV to LLM, gets scores & rationales
2. **Gender analysis** — groups scores by gender, computes mean/sd/median/deltas (if pronouns.json or gender.json exists)
3. **Consistency audit** — detects score ties across experiments, labels rationales (pure Python, no LLM)

## Experiments

| Name | Prompt | CV variant | What it tests |
|------|--------|-----------|---------------|
| `borderline` | default | no_pronouns_gender | Baseline — no gender cues |
| `strength_test1` | default | no_pronouns_gender | Cue strength — no cues |
| `strength_test2` | default | no_gender | Cue strength — pronouns only |
| `strength_test3` | default | _full | Cue strength — pronouns + gender field |
| `policy_gap` | policy_gap | no_pronouns_gender | With fairness statement in prompt |
| `gender_aware` | gender_aware | _full | Explicitly asks LLM to consider gender |

## Output structure

```text
data/outputs/
├─ IT/
│  └─ onet_it_jobs/
│     ├─ borderline__IT__onet_it_jobs.json
│     ├─ strength_test1__IT__onet_it_jobs.json
│     ├─ ...
│     ├─ gender_analysis_borderline__IT__onet_it_jobs.json
│     ├─ alignment_audit__IT__onet_it_jobs.json
│     └─ run_manifest.json
├─ Construction/
├─ Nursing/
└─ run_manifest.json
```

## API configuration

Runtime API settings are in `api_settings.json`:

```json
{
  "model": "gpt-5.2",
  "temperature": 0.2,
  "max_output_tokens": null,
  "timeout": null,
  "max_retries": 2,
  "base_url": null
}
```

API key goes in `config/.env`:
```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://...   # optional, for proxy/litellm
```

Environment variables override both `.env` and `api_settings.json`. See `src/llm_api.py` for the full list.

## Source files

| File | Purpose |
|------|---------|
| `run_all.py` | Pipeline orchestrator with progress tracking |
| `experiment_config.json` | Prompt & experiment definitions (edit this, not Python) |
| `src/scoring_experiment.py` | Unified scoring runner (reads config) |
| `src/gender_analysis.py` | Gender group statistics |
| `src/consistency_audit.py` | Cross-experiment score tie detection (pure Python) |
| `src/llm_api.py` | OpenAI-compatible API client |
| `src/common_io.py` | Shared I/O utilities |
| `src/common_gender_analysis.py` | Pronoun → gender mapping logic |

# FAIML Batch Recruitment Evaluation Pipeline

This repository runs large-scale **JD × CV matching evaluations** with LLM-based structured scoring.
It takes raw job descriptions and raw candidate resumes, splits them into project-ready single-file inputs, evaluates each candidate against each job under multiple experiment settings, and writes both per-task results and industry-level aggregate outputs.

The current codebase is centered around three stages:

1. **Input splitting** from raw JSON files into industry-specific and single-record files.
2. **Batch evaluation** across shared JD/CV industries.
3. **Post-processing** into per-JD summaries, industry summaries, candidate-level aggregate result files, and group analysis outputs.

---

## 1. Repository layout

```text
FAIML/
├─ config/
│  ├─ .env
│  └─ .env.example
├─ data/
│  ├─ inputs/
│  │  ├─ rawdata/
│  │  │  ├─ CV.json
│  │  │  ├─ JD.json
│  │  │  ├─ split.py
│  │  │  └─ cvsplit.py
│  │  ├─ CV/
│  │  └─ JD/
│  └─ outputs/
├─ src/
│  ├─ borderline.py
│  ├─ Strength_Test1.py
│  ├─ Strength_Test2.py
│  ├─ Strength_Test3.py
│  ├─ Policy_Gap_Test.py
│  ├─ exact_single_candidate_eval.py
│  ├─ common_io.py
│  ├─ common_gender_analysis.py
│  ├─ llm_api.py
│  ├─ gender_analysis_borderline.py
│  ├─ gender_analysis_Strength_Test1.py
│  ├─ gender_analysis_Strength_Test2.py
│  ├─ gender_analysis_Strength_Test3.py
│  ├─ gender_analysis_Policy_Gap_Test.py
│  └─ excel/
│     └─ extract_summaries.py
├─ requirements.txt
├─ run_all.py
└─ README.md
```

---

## 2. What the pipeline does

At a high level, the project works like this:

- Read raw CV and JD files from `data/inputs/rawdata/`
- Split CVs into industry-specific folders and three resume variants
- Split JDs into industry-specific folders and single-job JSON files
- Find industries that exist in both the JD side and the CV side
- For each shared industry:
  - loop through JDs sequentially
  - loop through experiments sequentially
  - run all matching CVs for that experiment in parallel
- Write one JSON result per `JD × CV × experiment`
- Build one summary JSON per JD/experiment result folder
- Build one industry summary JSON per experiment
- Build one candidate-level aggregate JSON per candidate in `candidates_result_XX/`
- Run gender/pronoun group analysis if group data is available
- Record failed tasks in `data/outputs/run_failures.json`

---

## 3. Dependencies

Install the Python dependencies with:

```bash
pip install -r requirements.txt
```

Current required packages are:

- `openai>=1.40.0`
- `python-dotenv>=1.0.1`

---

## 4. Environment configuration

Copy the template first:

```bash
cp config/.env.example config/.env
```

On Windows PowerShell:

```powershell
Copy-Item config/.env.example config/.env
```

Then fill in your real key in `config/.env`:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

Optional settings supported by the current code:

```env
OPENAI_BASE_URL=
RECRUITMENT_API_MODEL=gpt-5.2
RECRUITMENT_API_TEMPERATURE=0.2
RECRUITMENT_API_TIMEOUT=60
RECRUITMENT_API_MAX_RETRIES=2
OPENAI_ORG_ID=
OPENAI_PROJECT=
```

### Environment loading order

`src/llm_api.py` loads environment variables from:

1. project root `.env`
2. `config/.env`

So either location works, as long as `OPENAI_API_KEY` is available.

---

## 5. Raw input files

The pipeline uses fixed project-relative paths.

### CV input

```text
data/inputs/rawdata/CV.json
```

### JD input

```text
data/inputs/rawdata/JD.json
```

No extra input path arguments are required by `run_all.py`.

---

## 6. CV input format

The current splitter accepts the following CV JSON shapes.

### Option A: top-level list

```json
[
  {
    "candidate_id": "CONS_JUN_01_F_A",
    "industry_target": "Construction",
    "gender": "female",
    "pronouns": "she/her"
  }
]
```

### Option B: top-level object containing a candidate list

Accepted container keys include common names such as:

- `CV`
- `cv`
- `candidates`
- `Candidates`
- `data`
- `records`

Example:

```json
{
  "CV": [
    {
      "candidate_id": "CONS_JUN_01_F_A",
      "industry_target": "Construction"
    }
  ]
}
```

### CV variant convention used by the splitter

The current splitter groups records by candidate base ID and maps suffixes to three variants:

- `_A` → `no_pronouns_no_gender`
- `_B` → `no_gender`
- `_C` → `full`

That means one logical candidate is expected to appear as three records, for example:

- `CONS_JUN_01_F_A`
- `CONS_JUN_01_F_B`
- `CONS_JUN_01_F_C`

The current code removes fields as follows:

- `no_pronouns_no_gender`: removes both gender fields and pronoun fields; also removes common pronoun words from string text fields
- `no_gender`: removes gender fields only
- `full`: keeps the original record

The splitter also exports:

- `data/inputs/CV/pronouns/pronouns.json`
- `data/inputs/CV/gender/gender.json`

---

## 7. JD input format

The current `data/inputs/rawdata/split.py` expects **`JD.json` to be a JSON list** of job objects.

Example:

```json
[
  {
    "id": "construction_j_47205100",
    "industry": "Construction",
    "soc_code": "47-2051.00",
    "title": "Cement Masons and Concrete Finishers"
  }
]
```

### Important current behavior

In the current attached code, single-JD output filenames are built from:

```python
job.get("id", "unknown_soc_code")
```

So the single-file JD name is currently based on the JD object's **`id` field**, not the raw `soc_code` field.

Example output:

```text
data/inputs/JD/Construction/single/construction_j_47205100.json
```

The industry-level combined JD file is also written, for example:

```text
data/inputs/JD/Construction/Construction_jd.json
```

---

## 8. What `split.py` generates

After running the splitter, the input structure looks like this.

### CV side

```text
data/inputs/CV/
├─ Construction/
│  ├─ Construction_no_pronouns_no_gender.json
│  ├─ Construction_no_gender.json
│  ├─ Construction_full.json
│  ├─ no_pronouns_no_gender/
│  ├─ no_gender/
│  └─ full/
├─ IT/
├─ Nursing/
├─ gender/
│  └─ gender.json
└─ pronouns/
   └─ pronouns.json
```

### JD side

```text
data/inputs/JD/
├─ Construction/
│  ├─ Construction_jd.json
│  └─ single/
│     ├─ construction_j_47205100.json
│     ├─ construction_j_47206100.json
│     └─ ...
├─ IT/
└─ Nursing/
```

---

## 9. Experiments currently used by `run_all.py`

The current `run_all.py` batches these four experiments:

| Experiment | CV variant used | Experiment code |
|---|---|---|
| `borderline` | `no_pronouns_no_gender` | `01` |
| `Strength_Test2` | `no_gender` | `02` |
| `Strength_Test3` | `full` | `03` |
| `Policy_Gap_Test` | `no_pronouns_no_gender` | `04` |

### Important note about `Strength_Test1`

`Strength_Test1.py` exists in `src/`, but it is **not included** in the current default batch loop inside `run_all.py`.
It can still be run manually, but it is not part of the default four-experiment pipeline.

---

## 10. Batch execution behavior in `run_all.py`

The current batch order is:

```text
JD sequential -> experiment sequential -> CV parallel
```

This means:

- industries are processed one by one
- inside each industry, JDs are processed one by one
- inside each JD, experiments are processed one by one
- inside each `JD + experiment` pair, all relevant CV files are run in parallel using a thread pool

### Concurrency setting

The current code defines:

```python
INDUSTRY_WORKERS = max(1, min(96, 48))
```

In practice, that evaluates to `48`, so each experiment batch runs with up to **48 worker threads**, capped by the number of pending CV files.

### Resume behavior

The current code behaves as follows:

- default run: resume mode is effectively on
- `--resume`: explicitly keep resume mode on
- `--force`: re-run even if output files already exist

A result file is considered completed only if it is valid JSON and contains at least:

- `candidate_id`
- `total_score`

If a valid result already exists, `run_all.py` prints `[SKIP]` and reuses it.

---

## 11. How to run the full pipeline

### Standard run

```bash
python run_all.py
```

### Resume previous results explicitly

```bash
python run_all.py --resume
```

### Force a full re-run even if outputs already exist

```bash
python run_all.py --force
```

### Skip the splitter and only run experiments

```bash
python run_all.py --skip-split
```

### Most common practical command

If inputs have already been split and you want to continue from existing results:

```bash
python run_all.py --skip-split
```

---

## 12. What each evaluation script expects

### Shared evaluation scripts

These wrappers all call the common evaluator in `src/exact_single_candidate_eval.py`:

- `src/borderline.py`
- `src/Strength_Test1.py`
- `src/Strength_Test2.py`
- `src/Strength_Test3.py`

Typical usage:

```bash
python src/borderline.py path/to/jd.json path/to/cv.json --out path/to/output.json
```

The shared evaluator supports:

- positional JD path
- positional CV path
- `--out`
- `--skip-parent-aggregate`

### Policy Gap Test

`src/Policy_Gap_Test.py` is a standalone evaluator with its own prompt, but it now supports the same CLI pattern:

```bash
python src/Policy_Gap_Test.py path/to/jd.json path/to/cv.json --out path/to/output.json --skip-parent-aggregate
```

`run_all.py` always passes `--skip-parent-aggregate` for per-task execution so that parent aggregation is handled later by the batch script.

---

## 13. Result file structure

The pipeline writes several layers of outputs.

### A. Per-candidate per-JD per-experiment result files

For each `JD × candidate × experiment`, one JSON file is written under:

```text
data/outputs/<Industry>/<jd_key>/<jd_key>_<experiment_code>/<candidate_id>.json
```

Example:

```text
data/outputs/Construction/construction_j_47205100/construction_j_47205100_01/CONS_JUN_01_F_A.json
```

### B. Per-JD experiment summary

After a JD/experiment batch finishes, a summary file is created next to the result directory:

```text
data/outputs/Construction/construction_j_47205100/construction_j_47205100_01_summary.json
```

This summary is a JSON list of the candidate result objects for that specific JD and experiment.

### C. Candidate aggregate directory

For each industry and experiment, `run_all.py` creates:

```text
data/outputs/<Industry>/candidates_result_<experiment_code>/
```

Each JSON file in that folder aggregates one candidate across all JDs for the same industry and experiment.

Example:

```text
data/outputs/Construction/candidates_result_01/CONS_JUN_01_F_A.json
```

### D. Industry experiment summary

For each industry and experiment, `run_all.py` also writes:

```text
data/outputs/<Industry>/<Industry>_<experiment_code>.json
```

Example:

```text
data/outputs/Construction/Construction_01.json
```

This file contains:

- experiment metadata
- the industry name
- JD count
- candidate count
- evaluation count
- list of JD files used
- list of candidates and pointers to their candidate aggregate files

---

## 14. Gender / pronoun group analysis

After industry summaries are written, `run_all.py` tries to run a matching group-analysis script.

### Group data source resolution

The current code prefers:

1. `data/inputs/CV/gender/gender.json`
2. `data/inputs/CV/pronouns/pronouns.json`

If neither exists, group analysis is skipped.

### Analysis scripts

The current project includes:

- `src/gender_analysis_borderline.py`
- `src/gender_analysis_Strength_Test1.py`
- `src/gender_analysis_Strength_Test2.py`
- `src/gender_analysis_Strength_Test3.py`
- `src/gender_analysis_Policy_Gap_Test.py`

Even though `Strength_Test1` is not part of the default batch pipeline, its analysis script still exists.

### Output naming

Group-analysis outputs are written as:

```text
data/outputs/<Industry>/gender_analysis_<Industry>_<experiment_code>.json
```

Example:

```text
data/outputs/Construction/gender_analysis_Construction_01.json
```

### Current label normalization

The shared analysis logic currently normalizes gender/pronoun labels into four groups:

- `male`
- `female`
- `they`
- `thon`

It also maps values such as `neutral`, `n`, `they/them`, `neo`, and `xe/xem` into those canonical groups.

---

## 15. Failure logging

If some tasks fail during batch execution, `run_all.py` does **not** stop the entire pipeline immediately.
Instead, it collects failures and writes them to:

```text
data/outputs/run_failures.json
```

Each failure entry may include information such as:

- experiment
- industry
- JD file
- CV file
- output file
- error message

This makes it easier to inspect which jobs failed without losing the rest of the completed batch outputs.

---

## 16. Exporting summaries to Excel

The repository also includes:

```text
src/excel/extract_summaries.py
```

This script scans `data/outputs/`, extracts candidate-level scores from `*_summary.json` files, enriches them with inferred level and gender, and writes:

```text
data/outputs/all_experiment_summary_extract.xlsx
```

The target columns currently include:

- `industry`
- `soc_code`
- `experiment_id`
- `candidate_id`
- `job level`
- `gender`
- `total_score`
- the five subscores

---

## 17. Common issues and what they mean

### Missing API key

Typical error:

```text
Missing API key. Put OPENAI_API_KEY in project .env / config/.env or export it in your environment.
```

Fix: add a valid API key to `.env` or `config/.env`.

### Missing split inputs

Typical problem:

- no shared industries are found
- or CV/JD directories are empty

Fix: make sure `data/inputs/rawdata/CV.json` and `data/inputs/rawdata/JD.json` exist and that `split.py` can parse them.

### JD format mismatch

The current splitter expects `JD.json` to be a list of JSON objects. If your file is not a list, `split.py` will fail.

### CV variant directory missing

Typical error:

```text
Missing CV variant directory: .../no_gender
```

Fix: run the splitter again and confirm that the industry directory contains the required subfolders.

### Same-industry enforcement

The shared evaluator checks that JD and CV belong to the same industry. If you mix industries across folders or metadata, evaluation can fail.

### Existing output skipped unexpectedly

This usually means resume mode is active and a valid result file already exists. Use:

```bash
python run_all.py --force
```

if you want to regenerate everything.

---

## 18. Manual single-task examples

### Run a single borderline evaluation

```bash
python src/borderline.py \
  data/inputs/JD/Construction/single/construction_j_47205100.json \
  data/inputs/CV/Construction/no_pronouns_no_gender/CONS_JUN_01_F_A.json \
  --out data/outputs/tmp_borderline.json
```

### Run a single Strength Test 2 evaluation

```bash
python src/Strength_Test2.py \
  data/inputs/JD/IT/single/it_j_15125100.json \
  data/inputs/CV/IT/no_gender/IT_JUN_01_F_B.json \
  --out data/outputs/tmp_strength2.json
```

### Run a single Policy Gap Test evaluation

```bash
python src/Policy_Gap_Test.py \
  data/inputs/JD/Nursing/single/nursing_j_29112300.json \
  data/inputs/CV/Nursing/no_pronouns_no_gender/NURS_JUN_01_F_A.json \
  --out data/outputs/tmp_policy_gap.json
```

---

## 19. Practical notes for this codebase

- The current batch driver includes `Policy_Gap_Test` but not `Strength_Test1`.
- The current splitter uses the JD object `id` field for single-file naming.
- The current batch driver writes candidate aggregate folders named `candidates_result_01` through `candidates_result_04`.
- Group analysis prefers `gender.json` and falls back to `pronouns.json`.
- Per-JD summaries and industry summaries are both JSON, not CSV.
- Failed tasks are logged to `data/outputs/run_failures.json`.

---

## 20. Recommended workflow

For the current attached code, the safest workflow is:

1. Prepare `data/inputs/rawdata/CV.json`
2. Prepare `data/inputs/rawdata/JD.json`
3. Configure `config/.env`
4. Run:

```bash
python run_all.py
```

5. If inputs are already split and you want to continue from prior outputs:

```bash
python run_all.py --skip-split
```

6. Inspect:

- `data/outputs/<Industry>/`
- `data/outputs/run_failures.json`
- `data/outputs/all_experiment_summary_extract.xlsx`

---

## 21. Summary

This project is a structured LLM scoring pipeline for job-matching experiments.
The current codebase supports:

- raw CV/JD splitting
- three CV visibility variants
- four batch experiments
- per-task structured JSON scoring
- per-JD summaries
- per-industry candidate aggregate files
- per-industry summary JSON files
- group analysis outputs
- Excel extraction of summary scores

If you are working from the current attached version, this README reflects the actual code behavior in `run_all.py`, `split.py`, `llm_api.py`, the experiment scripts, and the current output layout.

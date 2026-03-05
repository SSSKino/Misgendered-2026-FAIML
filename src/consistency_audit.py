# consistency_audit.py
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

AUDIT_PROMPT = r"""
You are an "Experiment Output Alignment & Consistency Audit Assistant". I will provide you with N JSON outputs, each representing one analysis/experiment run. Each run contains a list of candidate objects with the same schema:

{
  "id": "candidate unique identifier",
  "name": "candidate name",
  "score": numeric,
  "rank": integer,
  "rationale": string
}

【Goal】
Align the same candidate across multiple runs, detect cases where a candidate has at least two runs with an equal score, and for those tied-score records label each rationale as Positive / Neutral / Risk with evidence-based reasons. Return a structured, machine-readable JSON summary.

【Core Rules (must follow strictly)】

A. Parsing & Alignment
1) The input contains N runs, each with a run_name and a candidates list; OR multiple candidate arrays with a preceding "RUN:xxx" label.
2) Use candidate.id as the only alignment key. Use name only for display; do NOT align by name.
3) If the same id appears multiple times within the same run:
   - Primary rule: keep the last occurrence.
   - Also record this anomaly (run_name + id) in notes.

B. Score Comparison & Tie Grouping
1) Always preserve the original score value as score_raw.
2) To avoid floating-point artifacts, derive a score_key for comparison and explicitly report the rule you used:
   - Default: if score is an integer or has <= 4 decimals, use strict numeric equality; if clear floating noise exists (e.g., 0.3000000004), switch to rounding to 4 decimals.
   - If scores frequently show many decimals or float noise, prefer: score_key = round(score, 4).
3) For each candidate, group their records by score_key across runs. If any score_key occurs at least 2 times, that score_key group triggers output.
4) Output ONLY triggered score_key groups. Do not output candidates with no ties.

C. Rationale Labeling (label each item independently)
For each triggered candidate + score group, label each run’s rationale:

Label definitions:
- Positive: explicit strong endorsement; high fit; clear strengths; meets/exceeds key requirements.
- Neutral: descriptive or mixed but not strong; insufficient information; cautious but no clear risk signals.
- Risk: explicit concerns/deficits/mismatch; notable uncertainty; negative signals (missing key skills, insufficient experience, questionable performance/reliability/compliance/ethics, etc.).

Hard constraints:
1) Judge ONLY from the rationale text. Do not infer or invent background.
2) For each rationale, output:
   - rationale_label (Positive/Neutral/Risk)
   - rationale_reason (specific explanation)
   - evidence_snippets: 1–2 short phrases quoted verbatim from the rationale (each <= 25 words/characters).
3) If tone is mixed or evidence is insufficient, default to Neutral and explain why it is not strong enough for Positive/Risk.

D. Output JSON Schema (must be consistent and machine-readable)
Return one JSON object with three top-level fields:

1) "score_ties": array. Each element represents "one candidate + one tied score group", with:
   - "id": candidate id
   - "name": the most frequent name across runs; if inconsistent, note it in "notes"
   - "score_group": the comparison key (score_key), not score_raw
   - "occurrences": how many times this score_group appears
   - "runs": run_name list (in input order) where this tie occurs
   - "items": array of per-run records:
        * "run_name"
        * "score_raw"
        * "rank"
        * "rationale"
        * "rationale_label": "Positive"|"Neutral"|"Risk"
        * "evidence_snippets": ["...", "..."] (1–2 items)
        * "rationale_reason": explanation that explicitly references the evidence_snippets

2) "summary": object:
   - "total_runs": N
   - "total_candidates_seen": number of unique candidates across all runs (dedup by id)
   - "candidates_with_any_score_tie": number of candidates that triggered at least one tie group
   - "total_score_tie_groups": number of elements in score_ties
   - "label_distribution": {"Positive": x, "Neutral": y, "Risk": z} (count labels only from output items)

3) "notes": array, including:
   - the exact score_key rule you used (strict vs rounding and how many decimals)
   - any anomalies: missing candidates in runs, inconsistent names, non-numeric scores, duplicate ids within a run, missing fields, etc.

【Input Compatibility】
- If the input is [{"run_name":..., "candidates":[...]}], parse directly.
- If the input is multiple candidate arrays preceded by "RUN:xxx", treat each array as that run’s candidates.
- If a run lacks a candidate, that run does not participate for that candidate; do not impute missing data.

Now process the JSON input I provide and return the output strictly following this schema.
""".strip()

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score_ties": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": ["string", "number"]},
                    "name": {"type": "string"},
                    "score_group": {"type": ["number", "string"]},
                    "occurrences": {"type": "integer", "minimum": 2},
                    "runs": {"type": "array", "items": {"type": "string"}},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "run_name": {"type": "string"},
                                "score_raw": {"type": "number"},
                                "rank": {"type": ["integer", "null"]},
                                "rationale": {"type": "string"},
                                "rationale_label": {"type": "string", "enum": ["Positive", "Neutral", "Risk"]},
                                "evidence_snippets": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "minItems": 1,
                                    "maxItems": 2,
                                },
                                "rationale_reason": {"type": "string"},
                            },
                            "required": [
                                "run_name",
                                "score_raw",
                                "rank",
                                "rationale",
                                "rationale_label",
                                "evidence_snippets",
                                "rationale_reason",
                            ],
                        },
                    },
                },
                "required": ["id", "name", "score_group", "occurrences", "runs", "items"],
            },
        },
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "total_runs": {"type": "integer", "minimum": 1},
                "total_candidates_seen": {"type": "integer", "minimum": 0},
                "candidates_with_any_score_tie": {"type": "integer", "minimum": 0},
                "total_score_tie_groups": {"type": "integer", "minimum": 0},
                "label_distribution": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "Positive": {"type": "integer", "minimum": 0},
                        "Neutral": {"type": "integer", "minimum": 0},
                        "Risk": {"type": "integer", "minimum": 0},
                    },
                    "required": ["Positive", "Neutral", "Risk"],
                },
            },
            "required": [
                "total_runs",
                "total_candidates_seen",
                "candidates_with_any_score_tie",
                "total_score_tie_groups",
                "label_distribution",
            ],
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score_ties", "summary", "notes"],
}


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def resolve_path_with_fallback(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    script_dir_candidate = Path(__file__).resolve().parent / path
    return script_dir_candidate


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _as_candidates_list(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(obj, dict) and isinstance(obj.get("candidates"), list):
        arr = obj["candidates"]
    elif isinstance(obj, list):
        arr = obj
    else:
        return None
    return [x for x in arr if isinstance(x, dict)]


def parse_runs_from_files(paths: List[str]) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    for p in paths:
        path = resolve_path_with_fallback(p)
        data = load_json(path)

        # list of runs
        if (
            isinstance(data, list)
            and data
            and isinstance(data[0], dict)
            and "run_name" in data[0]
            and "candidates" in data[0]
        ):
            for r in data:
                if isinstance(r, dict) and "run_name" in r and "candidates" in r:
                    cands = _as_candidates_list(r.get("candidates"))
                    if cands is None:
                        continue
                    runs.append({"run_name": str(r["run_name"]), "candidates": cands})
            continue

        # single run with run_name
        if isinstance(data, dict) and "run_name" in data and "candidates" in data:
            cands = _as_candidates_list(data.get("candidates"))
            if cands is None:
                continue
            runs.append({"run_name": str(data["run_name"]), "candidates": cands})
            continue

        # just candidates list/object
        cands = _as_candidates_list(data)
        if cands is None:
            raise ValueError(f"Unrecognized JSON structure in file: {p}")
        run_name = Path(p).stem
        runs.append({"run_name": run_name, "candidates": cands})

    return runs


def auto_discover_outputs(project_root: Path) -> List[str]:
    # Find all run output JSONs under the first three experiments.
    out_dir = project_root / "data" / "outputs"
    files: List[str] = []
    for sub in ("exp1_borderline", "exp2_strength", "exp3_policy_gap"):
        d = out_dir / sub
        if d.exists():
            files.extend([str(p) for p in sorted(d.glob("*.json"))])
    return files


def call_api(model: str, runs: List[Dict[str, Any]], temperature: float) -> Dict[str, Any]:
    client = OpenAI()
    resp = client.responses.create(
        model=model,
        instructions=AUDIT_PROMPT,
        input=json.dumps(runs, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "alignment_audit",
                "description": "Aligned score ties across runs with rationale labels and evidence snippets.",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
        },
        temperature=temperature,
    )
    raw = resp.output_text
    try:
        return json.loads(raw)
    except Exception as ex:
        Path("alignment_audit.raw.txt").write_text(raw or "", encoding="utf-8")
        raise ValueError("Model returned non-JSON text. Saved to alignment_audit.raw.txt") from ex


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "files",
        nargs="*",
        help="Run output JSON files (e.g. data/outputs/exp1/*.json data/outputs/exp2/*.json)",
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="Auto-discover outputs under data/outputs/exp1 and exp2 if no files provided",
    )
    ap.add_argument(
        "--out",
        default="data/outputs/exp4_audit/alignment_audit.json",
        help="Output file (default: data/outputs/exp4_audit/alignment_audit.json)",
    )
    ap.add_argument("--model", default="gpt-5.2", help="Model name (default: gpt-5.2)")
    ap.add_argument("--temperature", type=float, default=0.2, help="Temperature (default: 0.2)")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    files = list(args.files)
    if not files:
        # default to auto-discovery
        files = auto_discover_outputs(project_root)

    if not files:
        raise SystemExit("No input files found. Provide files explicitly or run after generating outputs.")

    runs = parse_runs_from_files(files)
    result = call_api(args.model, runs, args.temperature)

    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

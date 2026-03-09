# consistency_audit.py — pure Python, no LLM calls.
# Aligns candidates across experiment runs, detects score ties,
# and labels rationales via keyword heuristics.

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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

        if isinstance(data, dict) and "run_name" in data and "candidates" in data:
            cands = _as_candidates_list(data.get("candidates"))
            if cands is None:
                continue
            runs.append({"run_name": str(data["run_name"]), "candidates": cands})
            continue

        cands = _as_candidates_list(data)
        if cands is None:
            raise ValueError(f"Unrecognized JSON structure in file: {p}")
        run_name = Path(p).stem
        runs.append({"run_name": run_name, "candidates": cands})

    return runs


# ── Rationale labeling (keyword-based) ───────────────────────────────

POSITIVE_PATTERNS = [
    r"\bstrong(?:ly)?\b", r"\bexcellent\b", r"\bexceptional\b", r"\boutstanding\b",
    r"\bhigh(?:ly)?\s+(?:qualified|suitable|relevant|competent)\b",
    r"\bexceeds?\s+(?:requirements?|expectations?)\b",
    r"\bwell[\s-]suited\b", r"\bwell[\s-]qualified\b", r"\bideal\b",
    r"\bexpertise\b", r"\bextensive\s+experience\b", r"\bdirect(?:ly)?\s+(?:relevant|applicable|aligned)\b",
    r"\bmeets?\s+(?:all|most|key)\b", r"\bperfect\s+(?:fit|match|candidate)\b",
]

RISK_PATTERNS = [
    r"\blacks?\b", r"\bmissing\b", r"\binsufficient\b", r"\binadequate\b",
    r"\bno\s+(?:experience|evidence|relevant|direct|formal)\b",
    r"\blimited\s+(?:experience|knowledge|exposure|relevance)\b",
    r"\bdoes\s+not\s+(?:meet|have|match|demonstrate)\b",
    r"\bweak(?:ness)?\b", r"\bgap(?:s)?\b", r"\bconcern(?:s|ing)?\b",
    r"\bmismatch\b", r"\bunrelated\b", r"\birrelevant\b",
    r"\bbelow\b", r"\bpoor(?:ly)?\b", r"\bminimal\b",
    r"\buncertain(?:ty)?\b", r"\bquestionable\b",
]

_pos_compiled = [re.compile(p, re.IGNORECASE) for p in POSITIVE_PATTERNS]
_risk_compiled = [re.compile(p, re.IGNORECASE) for p in RISK_PATTERNS]


def _extract_snippets(text: str, patterns: List[re.Pattern], max_snippets: int = 2) -> List[str]:
    """Extract up to max_snippets short context windows around pattern matches."""
    snippets: List[str] = []
    for pat in patterns:
        for m in pat.finditer(text):
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            snippet = text[start:end].strip()
            if len(snippet) > 50:
                snippet = snippet[:50] + "..."
            snippets.append(snippet)
            if len(snippets) >= max_snippets:
                return snippets
    return snippets


def label_rationale(rationale: str) -> Tuple[str, str, List[str]]:
    """Returns (label, reason, evidence_snippets)."""
    pos_count = sum(1 for p in _pos_compiled if p.search(rationale))
    risk_count = sum(1 for p in _risk_compiled if p.search(rationale))

    if pos_count > risk_count and pos_count >= 2:
        snippets = _extract_snippets(rationale, _pos_compiled)
        return "Positive", f"Strong positive signals ({pos_count} positive vs {risk_count} risk indicators)", snippets or [rationale[:50]]
    elif risk_count > pos_count and risk_count >= 2:
        snippets = _extract_snippets(rationale, _risk_compiled)
        return "Risk", f"Notable risk signals ({risk_count} risk vs {pos_count} positive indicators)", snippets or [rationale[:50]]
    else:
        # mixed or insufficient signals
        snippets = _extract_snippets(rationale, _pos_compiled + _risk_compiled)
        return "Neutral", f"Mixed or insufficient signals ({pos_count} positive, {risk_count} risk indicators)", snippets or [rationale[:50]]


# ── Score tie detection ──────────────────────────────────────────────

def score_key(score: Any) -> Optional[float]:
    """Normalize score to a comparable key (round to 1 decimal)."""
    try:
        v = float(score)
    except (TypeError, ValueError):
        return None
    return round(v, 1)


def run_audit(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure Python audit: find score ties across runs, label rationales."""
    notes: List[str] = []
    notes.append("score_key rule: round(score, 1) for comparison")

    # Build per-candidate records across runs
    # candidate_id -> [(run_name, score_raw, score_key, rank, rationale)]
    CandRecord = Tuple[str, float, float, Optional[int], str]
    candidate_records: Dict[str, List[CandRecord]] = defaultdict(list)
    candidate_names: Dict[str, List[str]] = defaultdict(list)
    all_ids: set = set()
    dupe_notes: List[str] = []

    for run in runs:
        run_name = run["run_name"]
        seen_in_run: Dict[str, int] = {}
        for cand in run.get("candidates", []):
            cid = str(cand.get("id", ""))
            if not cid:
                continue
            all_ids.add(cid)

            # duplicate detection within run
            if cid in seen_in_run:
                seen_in_run[cid] += 1
                dupe_notes.append(f"Duplicate id={cid} in run={run_name} (kept last)")
            else:
                seen_in_run[cid] = 1

            name = str(cand.get("name", ""))
            raw_score = cand.get("score")
            sk = score_key(raw_score)
            if sk is None:
                notes.append(f"Non-numeric score for id={cid} in run={run_name}: {raw_score}")
                continue
            rank = cand.get("rank")
            rationale = str(cand.get("rationale", ""))

            # For duplicates, replace previous entry
            existing = candidate_records[cid]
            replaced = False
            for i, rec in enumerate(existing):
                if rec[0] == run_name:
                    existing[i] = (run_name, float(raw_score), sk, rank, rationale)
                    replaced = True
                    break
            if not replaced:
                existing.append((run_name, float(raw_score), sk, rank, rationale))

            candidate_names[cid].append(name)

    if dupe_notes:
        notes.extend(dupe_notes[:20])

    # Find score ties
    score_ties: List[Dict[str, Any]] = []
    candidates_with_ties: set = set()

    for cid, records in sorted(candidate_records.items()):
        # Group by score_key
        by_sk: Dict[float, List[CandRecord]] = defaultdict(list)
        for rec in records:
            by_sk[rec[2]].append(rec)

        for sk_val, group in sorted(by_sk.items()):
            if len(group) < 2:
                continue

            candidates_with_ties.add(cid)

            # Most frequent name
            name_counter = Counter(candidate_names.get(cid, []))
            best_name = name_counter.most_common(1)[0][0] if name_counter else ""

            items: List[Dict[str, Any]] = []
            for run_name, score_raw, _, rank, rationale in group:
                lbl, reason, snippets = label_rationale(rationale)
                items.append({
                    "run_name": run_name,
                    "score_raw": score_raw,
                    "rank": rank,
                    "rationale": rationale,
                    "rationale_label": lbl,
                    "evidence_snippets": snippets,
                    "rationale_reason": reason,
                })

            score_ties.append({
                "id": cid,
                "name": best_name,
                "score_group": sk_val,
                "occurrences": len(group),
                "runs": [item["run_name"] for item in items],
                "items": items,
            })

    # Label distribution
    label_dist = {"Positive": 0, "Neutral": 0, "Risk": 0}
    for tie in score_ties:
        for item in tie["items"]:
            label_dist[item["rationale_label"]] += 1

    summary = {
        "total_runs": len(runs),
        "total_candidates_seen": len(all_ids),
        "candidates_with_any_score_tie": len(candidates_with_ties),
        "total_score_tie_groups": len(score_ties),
        "label_distribution": label_dist,
    }

    return {"score_ties": score_ties, "summary": summary, "notes": notes}


def auto_discover_outputs(project_root: Path) -> List[str]:
    out_dir = project_root / "data" / "outputs"
    files: List[str] = []
    if not out_dir.exists():
        return files
    for p in out_dir.rglob("*.json"):
        name = p.name.lower()
        if name.startswith("gender_analysis_"):
            continue
        if "alignment_audit" in name:
            continue
        if name == "run_manifest.json":
            continue
        files.append(str(p))
    files.sort()
    return files


def main() -> None:
    ap = argparse.ArgumentParser(description="Consistency audit (pure Python, no LLM)")
    ap.add_argument("files", nargs="*", help="Run output JSON files")
    ap.add_argument("--auto", action="store_true", help="Auto-discover outputs")
    ap.add_argument("--out", default="alignment_audit.json", help="Output file")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent

    files = list(args.files)
    if not files:
        files = auto_discover_outputs(project_root)

    if not files:
        raise SystemExit("No input files found.")

    runs = parse_runs_from_files(files)
    result = run_audit(runs)

    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

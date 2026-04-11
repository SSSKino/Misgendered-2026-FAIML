from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from src.common_io import LABEL_ORDER, VALID_LABELS, clean_text, load_json, write_json
except ModuleNotFoundError:
    from common_io import LABEL_ORDER, VALID_LABELS, clean_text, load_json, write_json


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def _round4(value: float) -> float:
    return round(float(value), 4)


def _normalize_results(payload: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    if isinstance(payload, dict):
        meta = {k: v for k, v in payload.items() if k != "results"}
        results = payload.get("results") or []
    elif isinstance(payload, list):
        results = payload
    else:
        results = []
    normalized = [row for row in results if isinstance(row, dict)]
    return normalized, meta


def compute_metrics(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    filtered = [
        row for row in rows
        if clean_text(row.get("gold_label")) in VALID_LABELS and clean_text(row.get("llm_label")) in VALID_LABELS
    ]
    total = len(filtered)
    correct = sum(1 for row in filtered if row["gold_label"] == row["llm_label"])

    confusion: Dict[str, Dict[str, int]] = {
        gold: {pred: 0 for pred in LABEL_ORDER}
        for gold in LABEL_ORDER
    }
    support = Counter()
    pred_counts = Counter()
    metrics_by_label: Dict[str, Dict[str, Any]] = {}

    for row in filtered:
        gold = row["gold_label"]
        pred = row["llm_label"]
        confusion[gold][pred] += 1
        support[gold] += 1
        pred_counts[pred] += 1

    f1_values: List[float] = []
    weighted_f1_sum = 0.0

    for label in LABEL_ORDER:
        tp = confusion[label][label]
        fp = sum(confusion[gold][label] for gold in LABEL_ORDER if gold != label)
        fn = sum(confusion[label][pred] for pred in LABEL_ORDER if pred != label)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall) if (precision + recall) else 0.0
        f1_values.append(f1)
        weighted_f1_sum += f1 * support[label]
        metrics_by_label[label] = {
            "support": support[label],
            "predicted_count": pred_counts[label],
            "precision": _round4(precision),
            "recall": _round4(recall),
            "f1": _round4(f1),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    return {
        "evaluated_count": total,
        "correct_count": correct,
        "accuracy": _round4(_safe_div(correct, total)),
        "macro_f1": _round4(sum(f1_values) / len(LABEL_ORDER) if LABEL_ORDER else 0.0),
        "weighted_f1": _round4(_safe_div(weighted_f1_sum, total)),
        "gold_label_distribution": {label: support[label] for label in LABEL_ORDER},
        "pred_label_distribution": {label: pred_counts[label] for label in LABEL_ORDER},
        "per_label": metrics_by_label,
        "confusion_matrix": confusion,
    }


def build_setting_analysis(summary_path: Path) -> Dict[str, Path]:
    payload = load_json(summary_path)
    results, meta = _normalize_results(payload)

    analysis_root = summary_path.parent
    stem = summary_path.stem.replace("_predictions", "")
    analysis_path = analysis_root / f"{stem}_analysis.json"
    error_path = analysis_root / f"{stem}_error_candidates.json"
    case_path = analysis_root / f"{stem}_case_study_candidates.json"

    overall_metrics = compute_metrics(results)
    by_category_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_category_rows[clean_text(row.get("category")) or "Unknown"] .append(row)

    category_breakdown = {
        category: compute_metrics(category_rows)
        for category, category_rows in sorted(by_category_rows.items(), key=lambda item: item[0].lower())
    }

    error_candidates: List[Dict[str, Any]] = []
    case_candidates: List[Dict[str, Any]] = []
    for row in results:
        gold = clean_text(row.get("gold_label"))
        pred = clean_text(row.get("llm_label"))
        record = {
            "sample_id": row.get("sample_id"),
            "company": row.get("company"),
            "category": row.get("category"),
            "gold_label": gold,
            "llm_label": pred,
            "claim_text": row.get("claim_text"),
            "metric_name": row.get("metric_name"),
            "extracted_value": row.get("extracted_value"),
            "context_text": row.get("context_text"),
            "llm_reason": row.get("llm_reason"),
            "source_sample_file": row.get("source_sample_file"),
        }
        if gold in VALID_LABELS and pred in VALID_LABELS and gold != pred:
            error_candidates.append(record)
        elif gold in VALID_LABELS and pred in VALID_LABELS and gold == pred:
            case_candidates.append(record)

    analysis_payload: Dict[str, Any] = {
        **meta,
        "result_count": len(results),
        "overall_metrics": overall_metrics,
        "category_breakdown": category_breakdown,
        "error_count": len(error_candidates),
        "case_candidate_count": len(case_candidates),
    }

    write_json(analysis_path, analysis_payload)
    write_json(error_path, {**meta, "count": len(error_candidates), "results": error_candidates})
    write_json(case_path, {**meta, "count": len(case_candidates), "results": case_candidates[:50]})
    return {
        "analysis": analysis_path,
        "errors": error_path,
        "cases": case_path,
    }

# gender_analysis.py — unified gender analysis script replacing all
# gender_analysis_*.py files.
# Usage:
#   python src/gender_analysis.py <scores_json> <gender_json> [--out ...] [--strict]

import argparse
import json

from common_gender_analysis import (
    analyze_scores,
    extract_gender_array,
    extract_scores_array,
    load_json,
    resolve_path_with_fallback,
)


def run_gender_analysis(scores_path, group_path, out_path, strict=False):
    """Run gender analysis. Returns the result dict."""
    scores_raw = load_json(scores_path)
    group_raw = load_json(group_path)

    result = analyze_scores(extract_scores_array(scores_raw), extract_gender_array(group_raw), strict)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Unified gender/pronouns group analysis")
    ap.add_argument("scores", help="Path to experiment scores JSON")
    ap.add_argument("group_data", help="Path to gender/pronouns JSON")
    ap.add_argument("--out", default="gender_analysis.json", help="Output file")
    ap.add_argument("--strict", action="store_true", help="Fail on duplicate ids or invalid values")
    args = ap.parse_args()

    scores_path = resolve_path_with_fallback(args.scores)
    group_path = resolve_path_with_fallback(args.group_data)
    out_path = resolve_path_with_fallback(args.out)

    result = run_gender_analysis(scores_path, group_path, out_path, args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

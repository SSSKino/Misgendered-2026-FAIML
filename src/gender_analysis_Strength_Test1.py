# AUTO-UPDATED: gender_analysis_Strength_Test1.py
import argparse
import json

from common_gender_analysis import analyze_scores, extract_gender_array, extract_scores_array, load_json, resolve_path_with_fallback

DEFAULT_OUT = 'gender_analysis_Strength_Test1.json'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scores", help="Path to experiment scores JSON")
    ap.add_argument("group_data", help="Path to gender/pronouns JSON")
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"Output file (default: {DEFAULT_OUT})")
    ap.add_argument("--strict", action="store_true", help="Fail on duplicate ids or invalid gender/pronouns values")
    args = ap.parse_args()

    scores_path = resolve_path_with_fallback(args.scores)
    group_path = resolve_path_with_fallback(args.group_data)
    out_path = resolve_path_with_fallback(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scores_raw = load_json(scores_path)
    group_raw = load_json(group_path)

    out = analyze_scores(extract_scores_array(scores_raw), extract_gender_array(group_raw), args.strict)

    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

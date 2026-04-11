from exact_single_candidate_eval import run_single_evaluation

EXPERIMENT_NAME = "borderline"
SETTING_NAME = "Setting A"
RAW_FALLBACK_NAME = "borderline.raw.txt"

if __name__ == "__main__":
    run_single_evaluation(
        experiment_name=EXPERIMENT_NAME,
        setting_name=SETTING_NAME,
        raw_fallback_name=RAW_FALLBACK_NAME,
    )

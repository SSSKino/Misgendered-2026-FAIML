# 澳洲矿业 ESG Claim Support 实验项目

本项目用于运行澳洲矿业 ESG 报告中的 claim-level 支持度实验。当前代码版本使用三分类标签体系：

- `Fully Supported`
- `Partially Supported`
- `Suspected Greenwash`

并对同一批样本运行三种 setting：

- `Setting A`: Claim only
- `Setting B`: Claim + Value
- `Setting C`: Claim + Value + Context

## 1. 目录结构

```text
mining_test/
├─ data/
│  ├─ inputs/
│  │  ├─ rawdata/
│  │  │  ├─ balanced_90_claim_experiment_dataset.json
│  │  │  └─ split.py
│  │  └─ samples/
│  │     ├─ <company>/<sample_id>.json
│  │     └─ split_manifest.json
│  └─ outputs/
│     ├─ setting_A/
│     ├─ setting_B/
│     └─ setting_C/
├─ run_all.py
├─ src/
│  ├─ borderline.py
│  ├─ Strength_Test2.py
│  ├─ Strength_Test3.py
│  ├─ exact_single_candidate_eval.py
│  ├─ common_io.py
│  ├─ result_analysis.py
│  ├─ llm_api.py
│  └─ excel/extract_summaries.py
└─ requirements.txt
```

## 2. 数据切分

把原始 claim JSON 数组切成单条样本：

```bash
python data/inputs/rawdata/split.py --clean
```

默认只处理文件名匹配 `*claim*.json` 的源文件，并会把输出写成：

```text
data/inputs/samples/<company>/<sample_id>.json
```

## 3. 运行实验

```bash
python run_all.py
```

运行结束后，每个 setting 会生成：

- `setting_X_predictions.json`：该 setting 的完整预测结果
- `setting_X_analysis.json`：整体指标与按类别统计
- `setting_X_error_candidates.json`：预测错误样本候选
- `setting_X_case_study_candidates.json`：可用于案例分析的候选样本

## 4. 单条结果字段

每条实验结果都会保留原始样本全部字段，并追加：

- `experiment_id`
- `experiment_name`
- `setting_name`
- `llm_label`
- `llm_reason`
- `gold_label`
- `is_correct`
- `model`
- `temperature`
- `input_payload`
- `source_sample_file`

## 5. 导出总表

把三个 setting 的结果合并导出为 Excel / CSV / JSON：

```bash
python src/excel/extract_summaries.py
```

输出文件：

- `data/outputs/all_experiment_results.xlsx`
- `data/outputs/all_experiment_results.csv`
- `data/outputs/all_experiment_results.json`

## 6. 当前口径说明

当前代码口径已经切换为三分类实验。如果你论文或实验计划文档仍保留二分类 (`Supported / Not clearly supported`)，需要同步更新文档，避免和代码结果不一致。

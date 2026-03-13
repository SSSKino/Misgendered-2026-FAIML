# FAIML 招聘评估批处理项目说明

本项目用于批量执行 **Job Description（JD）与 Candidate Resume（CV）匹配评估**。整体流程是：

1. 将原始 `CV.json` 与 `JD.json` 切分为按行业、按单份 JD、按单份 CV 组织的输入文件；
2. 按实验配置，将每一份单独 JD 与对应变体目录下的所有单独 CV 逐一配对；
3. 调用大模型输出结构化评分结果；
4. 生成单候选人结果、单个 JD 维度汇总、行业维度汇总，以及可选的 gender / pronouns 群体分析结果。

## 1. 项目结构

典型目录结构如下：

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
│  │  │  └─ split.py
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
│  ├─ llm_api.py
│  ├─ gender_analysis_borderline.py
│  ├─ gender_analysis_Strength_Test1.py
│  ├─ gender_analysis_Strength_Test2.py
│  ├─ gender_analysis_Strength_Test3.py
│  └─ gender_analysis_Policy_Gap_Test.py
├─ requirements.txt
├─ run_all.py
└─ README.md
```

### 核心文件说明

- `data/inputs/rawdata/split.py`  
  负责把原始 `CV.json` / `JD.json` 切分成项目可直接消费的输入目录。

- `run_all.py`  
  批量主入口。负责：
  - 调用 `split.py`
  - 找到 JD 与 CV 共有的行业
  - 组织实验任务
  - 并发执行单个实验下的 CV 评估
  - 生成行业级汇总
  - 调用 gender / pronouns 群体分析脚本

- `src/exact_single_candidate_eval.py`  
  `borderline`、`Strength_Test1`、`Strength_Test2`、`Strength_Test3` 共用的单份 JD × 单份 CV 结构化评估逻辑。

- `src/Policy_Gap_Test.py`  
  独立的提示词与评估逻辑，但输出结构与其他实验保持一致。

- `src/common_io.py`  
  负责读写 JSON、路径解析、父级 summary 聚合等通用 IO 能力。

- `src/llm_api.py`  
  负责读取环境变量、调用大模型、处理温度、超时、重试等配置。

---

## 2. 项目依赖与环境配置

### 2.1 安装依赖

```bash
pip install -r requirements.txt
```

当前 `requirements.txt` 主要包含：

- `openai>=1.40.0`
- `python-dotenv>=1.0.1`

### 2.2 配置 API Key

先复制环境变量模板：

```bash
cp config/.env.example config/.env
```

Windows PowerShell：

```powershell
Copy-Item config/.env.example config/.env
```

然后在 `config/.env` 中填写真实密钥：

```env
OPENAI_API_KEY=your_real_api_key
```

可选配置项包括：

```env
OPENAI_BASE_URL=
RECRUITMENT_API_MODEL=gpt-5.2
RECRUITMENT_API_TEMPERATURE=0.2
RECRUITMENT_API_TIMEOUT=60
RECRUITMENT_API_MAX_RETRIES=2
OPENAI_ORG_ID=
OPENAI_PROJECT=
```

### 2.3 环境文件加载顺序

代码会优先尝试读取：

1. 项目根目录下的 `.env`
2. `config/.env`

因此你可以：

- 把密钥放在项目根目录 `.env`
- 或者放在 `config/.env`

只要保证至少有一个位置可读即可。

---

## 3. 原始输入文件要求

项目默认使用固定路径，不需要额外传参。

### 3.1 CV 输入路径

```text
data/inputs/rawdata/CV.json
```

### 3.2 JD 输入路径

```text
data/inputs/rawdata/JD.json
```

> 如果你本地已经把 `split.py` 改成支持 `JD.txt` 或支持更宽松的 JD JSON 结构，请以你本地版本的 `split.py` 为准。README 这里描述的是当前主项目代码的默认约定。

---

## 4. CV.json 格式要求

`split.py` 当前支持以下两类输入：

### 4.1 顶层直接是列表

```json
[
  {
    "candidate_id": "001_A",
    "industry_target": "Construction",
    "gender": "female",
    "pronouns": "she/her"
  }
]
```

### 4.2 顶层是对象，但候选人列表挂在常见键名下

支持以下键名中的任意一个：

- `CV`
- `cv`
- `candidates`
- `Candidates`
- `data`
- `records`

例如：

```json
{
  "CV": [
    {
      "candidate_id": "001_A",
      "industry_target": "Construction"
    }
  ]
}
```

### 4.3 CV 三个变体的约定

系统默认根据 `candidate_id` 后缀判断三种版本：

- `_A` → `no_pronouns_no_gender`
- `_B` → `no_gender`
- `_C` → `full`

也就是说，同一个候选人通常应有 3 条记录，示例：

- `candidate_001_A`
- `candidate_001_B`
- `candidate_001_C`

`split.py` 会把它们按同一个 base id 归为一组，并分别写入三个变体目录。

如果某个 base id 不是 3 条，`split_manifest.json` 中会记录异常信息，但不会阻止整体切分。

---

## 5. JD.json 格式要求

当前主项目代码默认要求 `JD.json` 顶层是对象，且包含 `occupations` 字段：

```json
{
  "occupations": {
    "Construction": [
      {
        "soc_code": "47-2051.00",
        "title": "Cement Masons and Concrete Finishers"
      }
    ],
    "IT": [
      {
        "soc_code": "15-1252.00",
        "title": "Software Developers"
      }
    ]
  }
}
```

其中：

- `occupations` 必须是对象
- 一级键是行业名
- 每个行业对应一个 occupation 列表
- occupation 列表中的每一项应为 JSON object
- 每个 occupation 最好包含 `soc_code`

如果顶层不是这种结构，旧版 `split.py` 会报：

```text
ValueError: JD input must be a JSON object.
```

或者：

```text
ValueError: JD input must contain an 'occupations' object keyed by industry.
```

如果你本地已经换成了你后续修改过的兼容版 `split.py`，那么顶层 list、`jobs`、或其他宽松结构也可能可用；但是否支持，必须以你本地那份 `split.py` 为准。

---

## 6. split.py 的职责与输出

运行 `split.py` 后，会同时完成两部分切分：

1. **CV 切分**
2. **JD 切分**

### 6.1 CV 切分结果

`split.py` 会：

- 按行业分组 CV
- 为每个行业生成三种变体总表
- 为每个行业生成单候选人 JSON 文件
- 额外导出 `gender.json` 与 `pronouns.json`
- 生成 `data/inputs/CV/split_manifest.json`

输出示例：

```text
data/inputs/CV/
├─ split_manifest.json
├─ gender/
│  └─ gender.json
├─ pronouns/
│  └─ pronouns.json
├─ Construction/
│  ├─ Construction_all_variants.json
│  ├─ Construction_no_pronouns_no_gender.json
│  ├─ Construction_no_gender.json
│  ├─ Construction_full.json
│  ├─ no_pronouns_no_gender/
│  │  ├─ candidate_001_A.json
│  │  └─ ...
│  ├─ no_gender/
│  │  ├─ candidate_001_B.json
│  │  └─ ...
│  └─ full/
│     ├─ candidate_001_C.json
│     └─ ...
└─ IT/
   └─ ...
```

### 6.2 JD 切分结果

`split.py` 会：

- 按行业拆分 `occupations`
- 生成行业级 JD 文件
- 按 `soc_code` 分组生成单份 JD 文件
- 生成 `data/inputs/JD/split_manifest.json`

输出示例：

```text
data/inputs/JD/
├─ split_manifest.json
├─ Construction/
│  ├─ Construction_jd.json
│  └─ single/
│     ├─ Construction_soc_code_47205100_jd.json
│     ├─ Construction_soc_code_47206100_jd.json
│     └─ ...
└─ IT/
   └─ ...
```

### 6.3 关于 soc_code 文件命名

当前主项目里，`soc_code` 文件名是否保留原始符号，取决于你实际使用的那份 `split.py`：

- 旧版逻辑会对 `47-2051.00` 做清洗，得到类似 `47205100`
- 你后续如果替换成自定义版本，也可以直接输出原始 `soc_code` 文件名

因此，**文件名命名规则请以你当前项目里的 `soc_code_filename_token()` 实现为准**。

### 6.4 运行 split.py

通常不需要单独运行，因为 `run_all.py` 默认会先调用它。

如果你想单独测试切分：

```bash
python data/inputs/rawdata/split.py
```

---

## 7. run_all.py 的作用

`run_all.py` 是整个项目的批量主入口。默认流程是：

1. 调用 `split.py`
2. 读取 `data/inputs/CV/` 与 `data/inputs/JD/`
3. 找出 JD 与 CV 都存在的共同产业目录
4. 遍历每个行业下的单份 JD
5. 针对每个实验，读取对应 CV 变体目录
6. 在单个实验内部对所有 CV 并发评估
7. 写出单份 JD 结果与变体汇总
8. 全部 JD 跑完后，写出行业级 summary
9. 如存在 `gender.json` 或 `pronouns.json`，再跑对应群体分析

### 7.1 默认命令

```bash
python run_all.py
```

### 7.2 常用参数

#### 继续上次结果续跑

```bash
python run_all.py --resume
```

#### 强制重新运行，即使已有输出也重跑

```bash
python run_all.py --force
```

#### 不重新执行 split.py

```bash
python run_all.py --skip-split
```

---

## 8. 实验与 CV 变体映射

`run_all.py` 通过 `EXPERIMENT_VARIANTS` 控制每个实验使用哪个 CV 目录。

典型配置如下：

```python
EXPERIMENT_VARIANTS = {
    "borderline": "no_pronouns_no_gender",
    "Strength_Test1": "no_pronouns_no_gender",
    "Strength_Test2": "no_gender",
    "Strength_Test3": "full",
    "Policy_Gap_Test": "no_pronouns_no_gender",
}
```

含义如下：

- `borderline` 使用 `no_pronouns_no_gender`
- `Strength_Test1` 使用 `no_pronouns_no_gender`
- `Strength_Test2` 使用 `no_gender`
- `Strength_Test3` 使用 `full`
- `Policy_Gap_Test` 使用 `no_pronouns_no_gender`

> 如果你已经手动删掉 `Strength_Test1`，或者把实验顺序改成“两两并发”，请直接以你当前 `run_all.py` 顶部的 `EXPERIMENT_VARIANTS`、实验列表和并发配置为准。

---

## 9. 并发逻辑说明

项目里的并发主要发生在 **单个实验内部对多个 CV 的评估**。

当前常见写法是：

```python
INDUSTRY_WORKERS = max(1, min(96, 48))
```

并且真正执行时还会再做一次：

```python
worker_count = max(1, min(INDUSTRY_WORKERS, len(pending_tasks)))
```

因此：

- `INDUSTRY_WORKERS` 是并发上限
- `len(pending_tasks)` 是这次还没完成的 CV 数量
- 实际 `workers` 会取两者较小值

例如：

- `pending_cv = 48`
- `INDUSTRY_WORKERS = 32`

最终：

```text
workers = 32
```

不是因为系统只识别了 32 份 CV，而是因为并发上限本身就是 32。

### 9.1 如何调整并发数

直接改 `run_all.py` 顶部：

```python
INDUSTRY_WORKERS = 8
```

或者：

```python
INDUSTRY_WORKERS = 48
```

### 9.2 你本地如果改过更复杂的并发层级

你之前可能已经把 `run_all.py` 改成了以下任一模式：

- JD 串行 → 实验串行 → CV 并发
- JD 串行 → 两个实验并发 → 各自 CV 并发
- 单行业所有 JD 打散后统一并发

README 无法替代你本地最终版本的代码逻辑。因此：

- **实际执行顺序，以你当前项目中 `run_all.py` 的实现为准**
- **实际并发线程数，以你当前项目中 `INDUSTRY_WORKERS` / `EXPERIMENT_PARALLELISM` 等配置为准**

---

## 10. 单个实验脚本的调用方式

### 10.1 结构化评分实验

以下四个脚本共用 `exact_single_candidate_eval.py` 的评分框架：

- `src/borderline.py`
- `src/Strength_Test1.py`
- `src/Strength_Test2.py`
- `src/Strength_Test3.py`

单独调用示例：

```bash
python src/Strength_Test2.py path/to/jd.json path/to/cv.json --out result.json
```

### 10.2 Policy Gap 测试

```bash
python src/Policy_Gap_Test.py path/to/jd.json path/to/cv.json --out result.json
```

### 10.3 可选参数

一般包括：

- `--out`
- `--model`
- `--temperature`
- `--skip-parent-aggregate`

其中 `--skip-parent-aggregate` 的作用是：

- 单个结果写出后，不立刻重建父级 summary
- 适用于 `run_all.py` 多线程批跑时，避免多个线程同时抢写汇总文件

如果某个实验脚本没有定义这个参数，而 `run_all.py` 却统一传入，就会报：

```text
error: unrecognized arguments: --skip-parent-aggregate
```

这类问题的修法不是改 prompt，而是要让对应实验脚本的 CLI 参数与调度器保持一致。

---

## 11. 输出目录结构

### 11.1 单个评估结果

单个 JD × 单个 CV 的结果通常写到：

```text
data/outputs/<experiment>/<industry>/<jd_key>/<variant>/<candidate_id>.json
```

例如：

```text
data/outputs/Strength_Test2/Construction/construction_j_47205100/no_gender/candidate_001_B.json
```

### 11.2 单个 JD + 单个变体汇总

```text
data/outputs/<experiment>/<industry>/<jd_key>/<variant>_summary.json
```

例如：

```text
data/outputs/Strength_Test2/Construction/construction_j_47205100/no_gender_summary.json
```

### 11.3 行业级汇总

通常为：

```text
data/outputs/<experiment>/<industry>/<experiment>_<industry>.json
```

或者某些自定义版本可能写成别的命名方式。请以你本地 `write_industry_aggregates()` 为准。

### 11.4 候选人汇总目录

行业级候选人聚合结果通常会额外输出到：

```text
data/outputs/<experiment>/<industry>/candidates_result/
```

目录下每个 JSON 表示同一个 candidate 在该行业下跨多个 JD 的结果集合。

### 11.5 群体分析结果

如果存在：

```text
data/inputs/CV/gender/gender.json
```

则优先做 gender 分析；否则如果存在：

```text
data/inputs/CV/pronouns/pronouns.json
```

则退回做 pronouns 分析。

输出通常是：

```text
data/outputs/<experiment>/<industry>/gender_analysis_<experiment>_<industry>.json
```

---

## 12. 结果文件内容概览

单个候选人结果一般至少包含：

- `candidate_id`
- `total_score`
- `subscores`
- `recommendation`
- `top_strengths`
- `main_gaps`
- `evidence_trace`
- `final_rationale`

其中 `Policy_Gap_Test.py` 当前使用的评分维度包括：

- `credential_and_qualification_fit`
- `relevant_experience_alignment`
- `core_role_capability`
- `communication_and_collaboration`
- `quality_compliance_and_execution_discipline`

并要求五个子分数精确相加得到 `total_score`。

---

## 13. 常见问题与排查

### 13.1 `ValueError: JD input must be a JSON object.`

原因：

- 当前 `split.py` 只接受顶层为对象的 JD JSON
- 或者顶层对象里没有 `occupations`

排查方式：

1. 打开 `data/inputs/rawdata/JD.json`
2. 确认顶层是不是 `{}`
3. 确认是否包含 `occupations`
4. 确认 `occupations` 是否为行业名到列表的映射

### 13.2 `Policy_Gap_Test.py: error: unrecognized arguments: --skip-parent-aggregate`

原因：

- `run_all.py` 统一给实验脚本传了 `--skip-parent-aggregate`
- 但 `Policy_Gap_Test.py` 没有定义这个 CLI 参数

修法：

- 在 `Policy_Gap_Test.py` 的 `argparse` 中补上这个参数
- 并在脚本结尾用 `if not args.skip_parent_aggregate:` 控制是否重建父级 summary

### 13.3 为什么日志里 `workers=12`、`workers=32`，不是 `pending_cv` 的数量？

因为实际线程数计算逻辑一般是：

```python
worker_count = min(INDUSTRY_WORKERS, len(pending_tasks))
```

所以：

- `pending_cv` 是待跑任务数
- `workers` 是这次真正开的线程数
- 上限取决于 `INDUSTRY_WORKERS`

### 13.4 为什么某些行业没有被跑？

因为 `run_all.py` 只会处理 **JD 与 CV 同时存在的行业目录**。

也就是说：

- `data/inputs/JD/Construction/` 存在
- 但 `data/inputs/CV/Construction/` 不存在

则该行业不会进入批量评估。

### 13.5 为什么 `--resume` 还会跳过一些文件？

因为 `--resume` 的设计就是：

- 若输出文件已存在
- 且能成功读到 `candidate_id` 与 `total_score`
- 就视为已完成，直接跳过

如果你希望全部重跑，用：

```bash
python run_all.py --force
```

---

## 14. 推荐使用流程

### 第一步：准备原始数据

确保以下文件存在：

```text
data/inputs/rawdata/CV.json
data/inputs/rawdata/JD.json
```

### 第二步：配置 API

填写 `.env` 或 `config/.env`。

### 第三步：先跑一次切分（可选）

```bash
python data/inputs/rawdata/split.py
```

检查：

- `data/inputs/CV/`
- `data/inputs/JD/`
- `split_manifest.json`

### 第四步：开始批量运行

```bash
python run_all.py
```

### 第五步：中断后续跑

```bash
python run_all.py --resume
```

---

## 15. 建议的维护方式

如果你后续还会继续改这个项目，建议优先保持下面三处一致：

1. `run_all.py` 传给实验脚本的 CLI 参数
2. 各实验脚本 `argparse` 定义
3. 输出目录与 summary 聚合逻辑

尤其是当你修改以下内容时：

- 实验数量
- 实验执行顺序
- JD / CV 并发层级
- 单份 JD 文件命名规则
- `JD.txt` / `JD.json` 兼容逻辑

都应该同步更新 README，避免后面“代码已经改了，但说明还是旧版”。

---

## 16. 最简运行命令汇总

安装依赖：

```bash
pip install -r requirements.txt
```

运行切分：

```bash
python data/inputs/rawdata/split.py
```

全量运行：

```bash
python run_all.py
```

断点续跑：

```bash
python run_all.py --resume
```

不重新切分：

```bash
python run_all.py --skip-split
```

强制重跑：

```bash
python run_all.py --force
```

单独运行实验：

```bash
python src/borderline.py path/to/jd.json path/to/cv.json --out out.json
python src/Strength_Test1.py path/to/jd.json path/to/cv.json --out out.json
python src/Strength_Test2.py path/to/jd.json path/to/cv.json --out out.json
python src/Strength_Test3.py path/to/jd.json path/to/cv.json --out out.json
python src/Policy_Gap_Test.py path/to/jd.json path/to/cv.json --out out.json
```

---

## 17. 一句话总结

这套项目的本质是：

**先把原始 JD / CV 数据拆成标准化单文件输入，再按实验配置对单份 JD 与大量单份 CV 做批量结构化评估，最后生成行业级与群体级汇总结果。**

# FAIML Recruitment Evaluation Pipeline

这个项目用于批量运行“岗位描述（JD）与候选人简历（CV）匹配评估”实验。当前代码会先把原始数据拆分成按行业、按候选人、按变体组织的 JSON 文件，再对每个 `单个 JD x 单个 CV` 组合调用 LLM 打分，最后输出行业级汇总结果和可选的群体分析结果。

## 项目做什么

- 自动将原始 `CV.json` 和 `JD.json` 拆分为可直接评估的文件结构。
- 按行业对齐 JD 和 CV，只处理两边都存在的行业目录。
- 对每个单独 JD 依次运行 5 个实验：
  - `borderline`
  - `Strength_Test1`
  - `Strength_Test2`
  - `Strength_Test3`
  - `Policy_Gap_Test`
- 为每个实验生成：
  - 单候选人结果
  - 单个 JD 下的变体汇总
  - 行业级汇总
  - 可选的 gender/pronouns 群体分析

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

```powershell
Copy-Item config/.env.example config/.env
```

然后把 `config/.env` 里的 `OPENAI_API_KEY` 改成你的真实密钥。

也可以直接在项目根目录放置 `.env`。代码会按下面顺序加载环境文件：

1. `./.env`
2. `./config/.env`

### 3. 准备原始输入

必须保证以下文件存在：

```text
data/inputs/rawdata/CV.json
data/inputs/rawdata/JD.json
```

### 4. 运行全量实验

```bash
python run_all.py
```

## 原始输入要求

### CV 输入

`data/inputs/rawdata/CV.json` 支持两种形态：

1. 顶层直接是数组
2. 顶层是对象，并且候选人列表位于以下任一键下：
   - `CV`
   - `cv`
   - `candidates`
   - `Candidates`
   - `data`
   - `records`

代码会按 `candidate_id` 的后缀把同一候选人的 3 个变体视为一组：

- `_A` -> `no_pronouns_no_gender`
- `_B` -> `no_gender`
- `_C` -> `full`

### JD 输入

`data/inputs/rawdata/JD.json` 必须是一个对象，并包含：

```json
{
  "occupations": {
    "IT": [...],
    "Construction": [...],
    "Nursing": [...]
  }
}
```

`run_all.py` 当前调用的是 `data/inputs/rawdata/split.py`，因此实际预处理依赖的是 `JD.json` 这一套格式。

## 运行流程

执行 `python run_all.py` 时，流程如下：

1. 先运行 `data/inputs/rawdata/split.py`
2. 生成拆分后的 `data/inputs/CV/` 与 `data/inputs/JD/`
3. 找出 JD 与 CV 都存在的行业目录
4. 遍历每个行业下 `JD/single/*.json`
5. 根据实验名选择对应的 CV 变体目录并逐个评估
6. 生成行业级 summary
7. 如果存在 `data/inputs/CV/gender/gender.json`，则继续做群体分析
8. 如果没有 `gender.json` 但存在 `data/inputs/CV/pronouns/pronouns.json`，则改用它做群体分析

### 实验与 CV 变体映射

- `borderline` -> `no_pronouns_no_gender`
- `Strength_Test1` -> `no_pronouns_no_gender`
- `Strength_Test2` -> `no_gender`
- `Strength_Test3` -> `full`
- `Policy_Gap_Test` -> `no_pronouns_no_gender`

其中前 4 个实验共用 `src/exact_single_candidate_eval.py` 的结构化评分逻辑，`Policy_Gap_Test` 使用单独提示词，但输出 schema 保持一致。

## 生成后的目录

### 预处理输出

`split.py` 会生成类似下面的结构：

```text
data/
  inputs/
    CV/
      split_manifest.json
      gender/
        gender.json
      pronouns/
        pronouns.json
      IT/
        IT_all_variants.json
        IT_full.json
        IT_no_gender.json
        IT_no_pronouns_no_gender.json
        full/
          *.json
        no_gender/
          *.json
        no_pronouns_no_gender/
          *.json
    JD/
      split_manifest.json
      IT/
        IT_jd.json
        single/
          IT_soc_code_11302100_jd.json
          ...
```

### 实验输出

全量运行后，结果会写到：

```text
data/outputs/<experiment>/<industry>/<jd_key>/<variant>/<candidate_id>.json
```

同时还会生成 3 类汇总文件：

1. 单个 JD + 单个变体汇总

```text
data/outputs/<experiment>/<industry>/<jd_key>/<variant>_summary.json
```

2. 行业级汇总

```text
data/outputs/<experiment>/<industry>/<experiment>_<industry>.json
```

3. 群体分析结果

```text
data/outputs/<experiment>/<industry>/gender_analysis_<experiment>_<industry>.json
```

## 单独运行某个实验

如果只想跑一个 JD 和一个 CV，可以直接调用脚本：

```bash
python src/Strength_Test1.py path/to/jd.json path/to/cv.json --out result.json
```

其他实验脚本的调用方式相同：

- `src/borderline.py`
- `src/Strength_Test1.py`
- `src/Strength_Test2.py`
- `src/Strength_Test3.py`
- `src/Policy_Gap_Test.py`

可选参数：

- `--model`
- `--temperature`
- `--out`

## API 配置

默认配置写在 [`src/llm_api.py`](src/llm_api.py) 中：

- 默认模型：`gpt-5.2`
- 默认温度：`0.2`
- 默认重试次数：`2`

支持的常用环境变量包括：

- `OPENAI_API_KEY`
- `RECRUITMENT_API_KEY`
- `OPENAI_BASE_URL`
- `RECRUITMENT_API_BASE_URL`
- `RECRUITMENT_API_MODEL`
- `OPENAI_MODEL`
- `RECRUITMENT_API_TEMPERATURE`
- `OPENAI_TEMPERATURE`
- `RECRUITMENT_API_TIMEOUT`
- `OPENAI_TIMEOUT`
- `RECRUITMENT_API_MAX_RETRIES`
- `OPENAI_MAX_RETRIES`
- `OPENAI_ORG_ID`
- `RECRUITMENT_API_ORG`
- `OPENAI_PROJECT`
- `RECRUITMENT_API_PROJECT`

## 结果格式说明

单候选人输出的核心字段包括：

- `candidate_id`
- `total_score`
- `subscores`
- `recommendation`
- `top_strengths`
- `main_gaps`
- `evidence_trace`
- `final_rationale`

推荐标签固定为以下 4 种之一：

- `Strong Interview`
- `Interview`
- `Borderline`
- `Do Not Interview`

## 常见注意事项

- `run_all.py` 没有 CLI 参数，默认直接跑完整流程。
- 运行全量实验前会重新执行一次拆分脚本，因此 `data/inputs/CV/` 和 `data/inputs/JD/` 下的同名产物可能被重新生成或覆盖。
- 如果某个实验返回的不是合法 JSON，原始模型文本会写入项目根目录下的 `*.raw.txt` 文件，方便排查。
- 群体分析按去掉 `_A/_B/_C` 后的基础候选人 ID 做匹配。
- 当前代码库里没有 `consistency_audit.py` 这一步，流水线会在行业 summary 和群体分析后结束。

## 主要代码入口

- [`run_all.py`](run_all.py)
- [`data/inputs/rawdata/split.py`](data/inputs/rawdata/split.py)
- [`src/exact_single_candidate_eval.py`](src/exact_single_candidate_eval.py)
- [`src/Policy_Gap_Test.py`](src/Policy_Gap_Test.py)
- [`src/common_gender_analysis.py`](src/common_gender_analysis.py)

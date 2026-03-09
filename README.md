# nursing_strength_test_project

这个版本已经改成：

1. **先把 `Nursing_full.json` 里的每个 CV 按 `candidate_id` 自动拆成单独文件**
2. **每次只把 1 份 JD + 1 份单独 CV 发给大语言模型评分**
3. **每个候选人的调用彼此独立，不共享上下文，不共享历史记录，不做多候选人联评**
4. **全部单独评分完成后，再在本地代码里统一排序、生成总 JSON、统计不同性别均分**

## 输入文件

默认读取：

- `data/inputs/Nursing_JD.txt`
- `data/inputs/Nursing_full.json`

## 自动拆分后的单独 CV 文件

运行后会自动生成到：

- `data/inputs/split_cvs/`

例如：

- `data/inputs/split_cvs/NURS_JUN_01_M_C.json`
- `data/inputs/split_cvs/NURS_JUN_01_F_C.json`

每个文件只包含一个 `candidate_id` 对应的一份 CV。

## 输出文件

### 1. 总结果 JSON
- `data/outputs/Strength_Test3.json`

包含：
- `candidates`
- `gender_score_summary`
- `split_cv_dir`
- `candidate_result_dir`
- `scoring_mode=single_candidate_stateless`

### 2. 性别均分 JSON
- `data/outputs/Strength_Test3.gender_summary.json`

### 3. 每个候选人的单独评分结果
- `data/outputs/candidate_results/<candidate_id>.json`

每个文件只对应一次独立模型调用结果。

## 运行方式

### Windows 双击运行
直接双击：
- `一键运行.bat`

只做输入检查与拆分预览：
- `一键校验输入.bat`

### 命令行运行
```bash
python src/strength_test3.py
```

### Dry run
```bash
python src/strength_test3.py --dry-run
```

Dry run 会：
- 校验 JD 与 CV 输入
- 自动拆分单独 CV 文件
- 生成预览 JSON
- **不会调用模型**

## 环境变量

把你自己的 `.env` 放到：

- `config/.env`

至少包含：

```env
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=your_base_url
RECRUITMENT_API_MODEL=your_model
```

## 关键保证

这个版本已经满足：

- **一个 candidate_id = 一份单独 CV 文件**
- **一个 candidate_id = 一次单独模型请求**
- **候选人之间没有共享上下文，没有历史记录联系**
- **排名与性别均分在本地代码中计算，不让模型跨候选人比较**

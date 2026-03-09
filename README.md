# Nursing Strength Test Project

这是一个可直接双击运行的简历匹配项目。

## 文件说明
- `一键运行.bat`：直接运行正式评估，读取固定输入文件并输出结果。
- `一键校验输入.bat`：不调用 API，只检查输入文件是否正常。
- `src/strength_test3.py`：主程序，已内置默认输入路径，不再需要手动输入命令行参数。
- `config/.env`：请把你的 API key 放在这里。

## 固定输入文件
程序默认读取以下文件：
- `data/inputs/Nursing_JD.txt`
- `data/inputs/Nursing_full.json`

## 输出文件
运行完成后会输出到：
- `data/outputs/Strength_Test3.json`

## 使用方法
### 第一次使用
1. 安装 Python 3.10+
2. 在项目根目录安装依赖：
   - `pip install -r requirements.txt`
3. 把你的 `.env` 放到 `config/.env`

### 日常运行
以后不需要再去 PowerShell 输入启动命令，直接双击：
- `一键运行.bat`

如果只是想先检查输入文件和路径是否正确，双击：
- `一键校验输入.bat`

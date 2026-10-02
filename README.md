# 0929 官方文件下载结果

源文件：`NSW_Council_BUILDING_DA_FILES_ONE_FILE_ONE_ROW_REBUILT_SAFE_2026-09-28 (1).xlsx`

共 379 条记录，已校验下载 295 条，仍失败 84 条。

- `download_manifest.xlsx`：完整清单、按 Council 汇总、失败清单
- `download_manifest.csv`：完整清单
- `failed_downloads_rebuilt.csv`：当前仍需处理的记录
- `downloaded_documents/`：按 Council 保存的有效文件
- `downloaded_documents/download_state.jsonl`：增量断点状态

所有成功记录均已校验文件存在性、大小和 SHA256。
2026-09-30 新增的三个文件另经 PDF 解析及标题、版本核对。
保留源表的原始标题和 URL，迁移或版本变化信息见清单新增列。

`failed_downloads.csv` 被其他程序占用，未能覆盖；请使用上述更新版失败清单。

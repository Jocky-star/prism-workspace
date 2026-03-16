# src/tools/ — 独立实用工具

不依赖 `src.services` 等内部模块的**独立可运行工具脚本**。

## 工具列表

| 文件 | 说明 |
|------|------|
| `content_idea_formatter.py` | 将选题想法转化为小红书文案框架（内容博主用） |

## 如何添加新工具

1. 创建 Python 脚本，文件名描述功能（如 `export_memory.py`）
2. 工具应**独立可运行**（`python3 src/tools/xxx.py`）
3. 不需要作为模块导入（不需要在别处 `from src.tools import xxx`）
4. 复杂的工具（需要 data_sources/llm_client 等）放 `src/services/generators/` 更合适

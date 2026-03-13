"""
服务系统统一配置
所有路径和配置从这里获取，不在各模块中硬编码
"""

import os
from pathlib import Path

# Workspace 自动检测
# 优先级：环境变量 WORKSPACE → OPENCLAW_WORKSPACE → 默认路径
WORKSPACE = Path(os.environ.get(
    "WORKSPACE",
    os.environ.get(
        "OPENCLAW_WORKSPACE",
        str(Path.home() / ".openclaw" / "workspace")
    )
))

# 数据目录
MEMORY_DIR = WORKSPACE / "memory"
SERVICES_OUTPUT_DIR = MEMORY_DIR / "services"
INTELLIGENCE_DIR = MEMORY_DIR / "intelligence"

# 确保输出目录存在
SERVICES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

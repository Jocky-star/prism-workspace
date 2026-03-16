# src/data/ — ⚠️ 运行时数据目录

**此目录由 `.gitignore` 忽略，不会被 git 追踪。**

## 用途

仅用于存放**运行时生成的数据文件**（JSON、CSV、临时缓存等）。

```
data/
└── daily-reports/      # 录音日报原始数据（API 拉取）
    └── 20260312.json
└── current_position.json  # 股票持仓（手动维护）
```

## ⚠️ 不要在这里放 Python 脚本

如果你想放分析脚本，请放到：

- **智能分析脚本** → `src/intelligence/`（如 daily_digest.py）
- **外部数据采集** → `src/sources/<name>/`
- **实用工具** → `src/tools/`

## 历史说明

之前有 `daily_digest.py`, `idea_capture.py`, `weekly_review.py` 错放在这里，
已于 2026-03-16 迁移到 `src/intelligence/`。

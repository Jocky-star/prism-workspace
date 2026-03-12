# Sources — 外部数据源

所有外部数据采集的统一入口。每种数据源一个子目录。

## 现有数据源

| 目录 | 数据类型 | 采集方式 |
|------|----------|----------|
| `audio/` | 录音转写数据 | API 拉取（郭宁申 Gemini 转写服务） |
| `camera/` | 摄像头画面 | rpicam-still 本地拍摄 |
| `stock/` | 股票/财经消息 | 东方财富 JSONP API |

## 如何接入新数据源

1. 在 `src/sources/` 下创建新子目录，比如 `src/sources/wearable/`
2. 写采集脚本，输出标准化 JSON/JSONL 到 `memory/intelligence/` 或 `memory/` 下
3. 在 `__init__.py` 中暴露主要函数（可选）
4. 配置 cron 定时采集，或在 daemon 中集成
5. 更新 SKILL.md 的命令列表

## 数据流向

```
sources/          采集原始数据
    ↓
intelligence/     感知 → 理解 → 精炼 → 行动
    ↓
screen/           推送到屏幕/飞书
```

## 设计原则

- 每个数据源独立运行，互不依赖
- 采集脚本只负责拿数据 + 格式化，不做分析
- 分析和理解交给 intelligence/ 层
- 新数据源不需要改 intelligence/ 的代码，只要输出格式兼容

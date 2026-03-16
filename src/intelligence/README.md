# src/intelligence/ — 智能理解层

从原始数据到洞察的多阶段处理管线：感知 → 理解 → 精炼 → 行动。

## 处理流水线

```
sources/ 原始数据
    ↓
perception.py     感知层 — 结构化提取（实体/情绪/活动）
    ↓
understand.py     理解层 — 行为分析、意图识别、模式检测
    ↓
refine.py         精炼层 — LLM 精炼，生成可读洞察
    ↓
weekly_refine.py  周度精炼 — 跨周汇总
    ↓
memory/intelligence/  处理结果存储
```

## 文件说明

| 文件 | 层次 | 说明 |
|------|------|------|
| `perception.py` | 感知层 | 从录音 JSON 提取结构化信息 |
| `understand.py` | 理解层 | 行为模式分析、意图识别 |
| `refine.py` | 精炼层 | LLM 精炼，生成洞察摘要 |
| `weekly_refine.py` | 周度精炼 | 跨周洞察汇总 |
| `bootstrap.py` | 初始化 | 首次运行引导（历史数据批量处理） |
| `daily_digest.py` | 每日分析 | 从录音数据生成星星的理解笔记 |
| `idea_capture.py` | 灵感捕捉 | 从对话/录音中提取饭团的灵感和创意 |
| `weekly_review.py` | 周度回顾 | 每周行为回顾，生成关怀消息 |

> 注：`daily_digest.py`, `idea_capture.py`, `weekly_review.py` 从原来的 `src/data/`（错误位置）
> 迁移至此，于 2026-03-16 完成。

## 数据依赖

- **输入**：`sources/` 各数据源，`memory/intelligence/chat_messages.jsonl`
- **输出**：`memory/intelligence/` 下各 JSON 文件
- **驱动**：被 `src/actions/planning/daily_pipeline.py` 调度

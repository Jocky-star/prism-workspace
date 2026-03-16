# 会议洞察管线

## 给 Agent 的说明

当用户有录音数据时，自动从中提取 `meeting`（会议/通话）场景，生成：
- **topic**：会议主题
- **decisions**：已做出的决策
- **disagreements**：出现的分歧或争议
- **action_items**：行动项（谁 → 做什么）
- **summary**：2-3句总结

**典型使用场景**：
- 开完会后自动整理会议纪要
- 通话结束后提炼行动项
- 不用手动写会议记录

## 配置方式

```yaml
pipelines:
  meeting-insight:
    enabled: true
    dry_run: false
```

**前提**：必须配置 `audio` 数据源。

## 验证

```bash
python3 main.py plugins verify meeting-insight
```

## 相关命令

```bash
# 手动运行
python3 src/services/generators/meeting_insight.py --date 2026-03-16

# 查看输出
python3 src/services/generators/meeting_insight.py --date 2026-03-16 --save
cat src/services/output/2026-03-16.json | python3 -m json.tool | grep -A 20 '"meeting_insight"'
```

## 输出示例

```json
{
  "meeting_count": 1,
  "meetings": [
    {
      "topic": "产品路线图讨论",
      "decisions": ["Q2 上线 AI 写作功能"],
      "disagreements": ["定价策略有分歧"],
      "action_items": ["小明 → 竞品定价调研", "饭团 → 产品原型设计"],
      "summary": "确定了Q2目标，行动项2条。定价问题下周继续讨论。"
    }
  ]
}
```

## 依赖

- **必须**：`audio` 数据源（没有录音则无法分析）

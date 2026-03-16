# 社交洞察管线

## 给 Agent 的说明

每周一自动生成上周的人际动态报告，帮助用户：
- 了解本周与哪些人有重要互动
- 发现关系状态的变化
- 获得下周人际维护建议（如"好久没联系XX了"）

**数据来源**：
- `memory/people.md` — 用户手动记录的人物备注
- `memory/intelligence/relationships.json` — 关系数据
- 一周内的聊天记录和录音

## 配置方式

```yaml
pipelines:
  social-insight:
    enabled: true
    lookback_days: 7    # 回溯天数，默认7天
    dry_run: false
```

## 验证

```bash
python3 main.py plugins verify social-insight
```

## 相关命令

```bash
# 手动生成（指定日期作为周末）
python3 src/services/generators/social_insight.py --date 2026-03-16

# 查看输出
python3 src/services/generators/social_insight.py --date 2026-03-16 --save
```

## 输出示例

```json
{
  "week_summary": "本周主要与团队沟通产品方向，与朋友A有一次深入交流",
  "key_interactions": [
    {"person": "朋友A", "event": "周五通话30分钟", "note": "聊到了职业规划"}
  ],
  "relationship_changes": ["朋友B本周没有联系，已超过2周"],
  "suggestions": ["可以主动联系一下朋友B", "给同事发一下上次承诺的资料"]
}
```

## 人物数据管理

在 `memory/people.md` 中记录重要人物：

```markdown
## 朋友A
- 关系：大学同学，现在在字节
- 记录：喜欢钓鱼，家在杭州

## 导师B
- 关系：工作导师
- 联系频率：每月一次
```

这些信息会被 social-insight 用于更精准的关系分析。

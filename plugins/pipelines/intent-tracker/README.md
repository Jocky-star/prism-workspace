# 意图追踪管线

## 给 Agent 的说明

每天晚上自动分析当日录音和对话，从中提取用户表达的意图，并自动归档：
- **wish**（愿望）→ 记录到意图追踪文件
- **todo**（待办）→ 自动追加到 `memory/todo.md`
- **idea**（想法）→ 自动追加到 `memory/idea-capture.md`
- **plan**（计划）→ 记录并跟踪
- **preference**（偏好）→ 自动应用设备偏好（如台灯时段设置）

**价值**：用户不需要手动记事。说过的话 → 自动变成待办和想法库。

## 配置方式

```yaml
pipelines:
  intent-tracker:
    enabled: true
    auto_save_todos: true    # 自动写入 todo.md
    auto_save_ideas: true    # 自动写入 idea-capture.md
    dry_run: false
```

## 验证

```bash
python3 main.py plugins verify intent-tracker
```

## 相关命令

```bash
# 手动运行
python3 src/services/generators/intent_tracker.py --date 2026-03-16

# 干运行（不写文件）
python3 src/services/generators/intent_tracker.py --date 2026-03-16 --dry-run

# 查看捕捉的意图历史
cat memory/intelligence/intents.json | python3 -m json.tool | tail -50
```

## 输出格式

```json
{
  "intents": [
    {"type": "wish", "content": "想去福州旅游", "quote": "我一直想去福州看看", "confidence": 0.9},
    {"type": "todo", "content": "预约皮肤科", "quote": "下周要去看皮肤科", "confidence": 0.85}
  ],
  "by_type": {"wish": 1, "todo": 1, "idea": 0}
}
```

## 注意

- 需要 `audio` 或 `chat` 数据源才能有输入
- 偏好类意图（preference）会自动触发台灯规则更新
- 意图历史保存在 `memory/intelligence/intents.json`，保留最近30天

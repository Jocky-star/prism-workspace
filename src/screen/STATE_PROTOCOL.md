# Prism 屏幕状态协议

任何进程、Agent、脚本都可以控制 Prism 屏幕显示的内容。

## 工作原理

Prism daemon 每 10 秒刷新一次屏幕，内容来自 `memory/prism_state.json`。

**默认情况下不需要做任何事** — daemon 内置的 `auto_status.py` 会自动监听 OpenClaw gateway 的 session 活动，推断当前状态并更新 state 文件。

如果你想手动控制，有三种方式（任选其一）。

## 文件格式

```json
{
  "current_task": "正在做什么（≤12中文字）",
  "completed": ["已完成的事1", "已完成的事2"],
  "reminders": ["提醒内容"],
  "auto_inferred": false,
  "task_set_at": "2026-03-13T17:00:00+08:00"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `current_task` | string | 屏幕 NOW 区域显示的内容，≤12中文字 |
| `completed` | string[] | 屏幕 DONE 区域，最多 5 条 |
| `reminders` | string[] | 屏幕 NOTE 区域 |
| `auto_inferred` | bool | `true`=自动推断，`false`=手动设置 |
| `task_set_at` | ISO8601 | 上次设置时间，用于超时判断 |

## 方式一：命令行（推荐）

```bash
# 设置当前任务
python3 src/screen/update.py --task "写周报"

# 标记完成
python3 src/screen/update.py --done "写周报"

# 添加提醒
python3 src/screen/update.py --note "下午3点开会"
```

## 方式二：Python API

```python
import json
from pathlib import Path

state_file = Path("memory/prism_state.json")

# 读取
state = json.loads(state_file.read_text()) if state_file.exists() else {}

# 写入（手动模式）
state["current_task"] = "我的任务"
state["auto_inferred"] = False  # 标记为手动，5分钟内不会被自动推断覆盖
state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
```

## 方式三：直接写文件

```bash
echo '{"current_task": "我的任务", "auto_inferred": false}' > memory/prism_state.json
```

## 优先级规则

```
手动设置 (auto_inferred=false)   ← 5分钟内不会被覆盖
    ↓ 5分钟后
自动推断 (auto_inferred=true)    ← daemon 接管
```

自动推断的优先级：
1. **活跃 sub-agent** → 显示 task 描述
2. **活跃 cron** → 显示 cron 名称
3. **用户对话中** → 显示 "对话中"
4. **全部空闲** → 显示时段标签（待命中 / 深夜自学中）

## 任务生命周期

```
新任务设置 → 屏幕显示 NOW
    ↓ 10分钟无更新 + 无活跃 session
自动流转到 DONE → 屏幕显示在 DONE 区域
    ↓ 次日 0 点
自动清空
```

## 给 Agent 开发者

如果你在写一个 OpenClaw Skill 并想和 Prism 屏幕联动：

1. **什么都不做** — auto_status 会自动检测你的 session 并显示
2. **想自定义显示内容** — 写 `memory/prism_state.json`，设 `auto_inferred: false`
3. **长时间任务** — 开始时写一次，结束时不用管（10分钟后自动流转到 done）

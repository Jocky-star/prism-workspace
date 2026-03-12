#!/usr/bin/env python3
"""
prism_auto_status.py — 自动管理屏幕任务状态

逻辑很简单：
1. 有活跃 sub-agent/cron → 显示任务名
2. 当前 task 超过 10 分钟没变 → 说明做完了 → 流转到 done
3. 每天自动清空 done
4. gateway 不可用时不动任何东西
"""

import json
import subprocess
import random
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

PRISM_STATE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_state.json"))
TZ = timezone(timedelta(hours=8))
MAX_COMPLETED = 5
TASK_STALE_SEC = 600  # task 超过 10 分钟没变 → 认为完成
TASK_ACTIVE_MS = 120_000  # sub-agent/cron 2分钟内算活跃

INTERNAL_TASKS = {
    "待命中", "深夜自学中", "深夜待命",
    "上午待命", "午间待命", "下午待命", "晚间待命",
    "派帮手干活中", "后台定时任务运行中",
    "", "空闲",
}

IDLE_NOTES = [
    "人间有味是清欢", "此心安处是吾乡", "一蓑烟雨任平生",
    "清风徐来水波不兴", "行到水穷处坐看云起时", "竹杖芒鞋轻胜马",
    "小舟从此逝江海寄余生", "掬水月在手弄花香满衣",
    "晚来天欲雪能饮一杯无", "春水碧于天画船听雨眠",
    "人生如逆旅我亦是行人", "山高月小水落石出",
    "云深不知处", "心远地自偏", "万物静观皆自得",
    "天地一沙鸥", "明月松间照清泉石上流",
    "绿蚁新醅酒红泥小火炉", "长风破浪会有时", "日日是好日",
]


def load_state():
    if PRISM_STATE.exists():
        try:
            return json.loads(PRISM_STATE.read_text())
        except: pass
    return {}


def save_state(state):
    state["updated_at"] = datetime.now(TZ).isoformat()
    tmp = PRISM_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(PRISM_STATE)


def get_active_task():
    """从 gateway 检测活跃的 sub-agent/cron 任务名"""
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout
        json_start = output.find('{')
        if json_start == -1:
            return None  # 解析失败
        data = json.loads(output[json_start:])
        sessions = data.get("sessions", {}).get("recent", [])
    except:
        return None  # 超时/不可用

    for s in sessions:
        age = s.get("age", 999999999)
        key = s.get("key", "")
        label = s.get("label", "")

        if ":subagent:" in key and age < TASK_ACTIVE_MS:
            desc = label or "帮手任务"
            return desc[:14] if len(desc) > 14 else desc

        if ":cron:" in key and ":run:" in key and age < TASK_ACTIVE_MS:
            name = label or ""
            if name:
                return name[:14] if len(name) > 14 else name

    return ""  # 没有活跃任务


def get_idle_label():
    hour = datetime.now(TZ).hour
    if 0 <= hour < 8:
        return "深夜自学中"
    elif 23 <= hour:
        return "深夜待命"
    else:
        return "待命中"


def main():
    state = load_state()
    now = datetime.now(TZ)

    # 每日清 done
    today = now.strftime("%Y-%m-%d")
    if state.get("last_reset_date", "") != today:
        state["completed"] = []
        state["last_reset_date"] = today
        state["reminders"] = [random.choice(IDLE_NOTES)]
        save_state(state)
        print(f"[auto_status] 新一天，done 已清空")

    old_task = state.get("current_task", "")

    # 检测活跃任务
    detected = get_active_task()

    if detected is None:
        # gateway 不可用，不动
        return

    if detected:
        # 有活跃 sub-agent/cron
        if detected != old_task:
            if old_task and old_task not in INTERNAL_TASKS:
                completed = state.get("completed", [])
                if old_task not in completed:
                    completed.insert(0, old_task)
                    state["completed"] = completed[:MAX_COMPLETED]
            state["current_task"] = detected
            state["task_set_at"] = now.isoformat()
            state["reminders"] = [random.choice(IDLE_NOTES)]
            save_state(state)
            print(f"[auto_status] {old_task!r} → {detected!r}")
        return

    # 没有活跃的 sub-agent/cron。看主 session 是否活跃
    main_active = False
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout
        json_start = output.find('{')
        if json_start >= 0:
            data = json.loads(output[json_start:])
            for s in data.get("sessions", {}).get("recent", []):
                if "feishu:direct:" in s.get("key", "") and s.get("age", 999999) < 300_000:
                    main_active = True
                    break
    except:
        pass

    if main_active and old_task and old_task not in INTERNAL_TASKS:
        # 主 session 活跃 + 有真实 task → 保持不动，星星在干活
        return

    # 检查当前 task 是否过期
    if old_task and old_task not in INTERNAL_TASKS:
        task_set = state.get("task_set_at", state.get("updated_at", ""))
        try:
            set_time = datetime.fromisoformat(task_set)
            elapsed = (now - set_time).total_seconds()
        except:
            elapsed = 9999

        if elapsed >= TASK_STALE_SEC:
            # 任务超时 + 主 session 不活跃 → 流转到 done
            completed = state.get("completed", [])
            if old_task not in completed:
                completed.insert(0, old_task)
                state["completed"] = completed[:MAX_COMPLETED]
                print(f"[auto_status] done += {old_task!r} (超时{elapsed:.0f}s)")
            state["current_task"] = get_idle_label()
            state["task_set_at"] = now.isoformat()
            state["reminders"] = [random.choice(IDLE_NOTES)]
            save_state(state)
            print(f"[auto_status] → {state['current_task']}")


if __name__ == "__main__":
    main()

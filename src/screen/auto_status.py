#!/usr/bin/env python3
"""
auto_status.py — 屏幕状态自动推断

零配置：daemon 启动后自动监听 OpenClaw gateway 活动，推断屏幕应该显示什么。
手动覆盖：通过 update.py 或直接写 prism_state.json（5分钟内不会被自动推断覆盖）。

## 新用户须知
- clone 项目 + 启动 daemon → 屏幕自动跟上 agent 活动
- 不需要改任何 OpenClaw 配置
- 手动控制方式见 STATE_PROTOCOL.md

## 推断优先级
1. 手动设置 (auto_inferred=false, 5分钟内) — 最高
2. 活跃 sub-agent → 显示 task 描述
3. 活跃 cron → 显示 cron 名称
4. 主 session 活跃（有用户对话）→ 显示"对话中"
5. 以上都没有 → 空闲状态
"""

import json
import subprocess
import random
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# === 路径自动检测（不硬编码，其他用户也能用）===
def _find_workspace() -> Path:
    """按优先级查找 workspace 目录"""
    # 1. 环境变量
    env = os.environ.get("PRISM_WORKSPACE")
    if env:
        return Path(env)
    # 2. 相对于本文件 (src/screen/auto_status.py → workspace root)
    here = Path(__file__).resolve().parent
    candidate = here.parent.parent  # src/screen/../../ = workspace
    if (candidate / "memory").exists():
        return candidate
    # 3. OpenClaw 默认 workspace
    default = Path.home() / ".openclaw" / "workspace"
    if default.exists():
        return default
    return candidate  # fallback

WORKSPACE = _find_workspace()
PRISM_STATE = WORKSPACE / "memory" / "prism_state.json"

TZ = timezone(timedelta(hours=8))
MAX_COMPLETED = 5
TASK_STALE_SEC = 600       # task 超过 10 分钟没变 → 认为完成
TASK_ACTIVE_MS = 120_000   # sub-agent/cron 2分钟内算活跃
MANUAL_PROTECT_SEC = 300   # 手动设置后 5 分钟不覆盖

INTERNAL_TASKS = {
    "待命中", "深夜自学中", "深夜待命",
    "上午待命", "午间待命", "下午待命", "晚间待命",
    "派帮手干活中", "后台定时任务运行中",
    "", "空闲", "对话中",
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


# === State I/O ===

def load_state() -> dict:
    if PRISM_STATE.exists():
        try:
            return json.loads(PRISM_STATE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    state["updated_at"] = datetime.now(TZ).isoformat()
    PRISM_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRISM_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(PRISM_STATE)


def is_manual_protected(state: dict) -> bool:
    """手动设置后 5 分钟内不被自动推断覆盖"""
    if state.get("auto_inferred", True):
        return False  # 已经是自动推断的，不保护
    task_set = state.get("task_set_at", state.get("updated_at", ""))
    if not task_set:
        return False
    try:
        set_time = datetime.fromisoformat(task_set)
        elapsed = (datetime.now(TZ) - set_time).total_seconds()
        return elapsed < MANUAL_PROTECT_SEC
    except Exception:
        return False


# === Gateway 活动检测 ===

def _query_gateway() -> dict | None:
    """调 openclaw status --json，返回解析后的 dict 或 None"""
    try:
        result = subprocess.run(
            ["openclaw", "status", "--json"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout
        json_start = output.find('{')
        if json_start == -1:
            return None
        return json.loads(output[json_start:])
    except Exception:
        return None


def detect_active_task() -> str | None:
    """
    从 gateway 检测当前活跃任务。
    返回值：
      - str (非空) = 检测到的任务名
      - "" = 没有活跃任务（空闲）
      - None = gateway 不可用
    """
    data = _query_gateway()
    if data is None:
        return None

    sessions = data.get("sessions", {}).get("recent", [])
    
    # 优先级 1: 活跃 sub-agent
    for s in sessions:
        age = s.get("age", 999999999)
        key = s.get("key", "")
        label = s.get("label", "")
        if ":subagent:" in key and age < TASK_ACTIVE_MS:
            desc = label or "帮手任务"
            return desc[:14]

    # 优先级 2: 活跃 cron
    for s in sessions:
        age = s.get("age", 999999999)
        key = s.get("key", "")
        label = s.get("label", "")
        if ":cron:" in key and ":run:" in key and age < TASK_ACTIVE_MS:
            name = label or "定时任务"
            return name[:14]

    # 优先级 3: 主 session 活跃（用户在对话）
    for s in sessions:
        age = s.get("age", 999999999)
        key = s.get("key", "")
        # 飞书/telegram/discord 等消息通道的 direct session
        if any(ch in key for ch in [":direct:", ":group:"]) and age < TASK_ACTIVE_MS:
            return "对话中"

    return ""  # 全部空闲


def get_idle_label() -> str:
    hour = datetime.now(TZ).hour
    if 0 <= hour < 8:
        return "深夜自学中"
    elif 23 <= hour:
        return "深夜待命"
    else:
        return "待命中"


# === 核心逻辑 ===

def main():
    state = load_state()
    now = datetime.now(TZ)
    today = now.strftime("%Y-%m-%d")

    # 每日清 done
    if state.get("last_reset_date", "") != today:
        state["completed"] = []
        state["last_reset_date"] = today
        state["reminders"] = [random.choice(IDLE_NOTES)]
        save_state(state)
        print(f"[auto_status] 新一天，done 已清空")

    # 手动保护期内不覆盖
    if is_manual_protected(state):
        print(f"[auto_status] 手动设置保护中，跳过 ({state.get('current_task', '')})")
        return

    old_task = state.get("current_task", "")

    # 检测活跃任务
    detected = detect_active_task()

    if detected is None:
        # gateway 不可用，不动
        print("[auto_status] gateway 不可用，跳过")
        return

    if detected:
        # 有活跃任务
        if detected != old_task:
            # 流转旧任务到 done
            if old_task and old_task not in INTERNAL_TASKS:
                completed = state.get("completed", [])
                if old_task not in completed:
                    completed.insert(0, old_task)
                    state["completed"] = completed[:MAX_COMPLETED]
            state["current_task"] = detected
            state["task_set_at"] = now.isoformat()
            state["auto_inferred"] = True
            state["reminders"] = [random.choice(IDLE_NOTES)]
            save_state(state)
            print(f"[auto_status] {old_task!r} → {detected!r}")
        return

    # 没有活跃任务 — 检查当前 task 是否过期
    if old_task and old_task not in INTERNAL_TASKS:
        task_set = state.get("task_set_at", state.get("updated_at", ""))
        try:
            set_time = datetime.fromisoformat(task_set)
            elapsed = (now - set_time).total_seconds()
        except Exception:
            elapsed = 9999

        if elapsed >= TASK_STALE_SEC:
            # 流转到 done
            completed = state.get("completed", [])
            if old_task not in completed:
                completed.insert(0, old_task)
                state["completed"] = completed[:MAX_COMPLETED]
                print(f"[auto_status] done += {old_task!r} (超时{elapsed:.0f}s)")
            state["current_task"] = get_idle_label()
            state["task_set_at"] = now.isoformat()
            state["auto_inferred"] = True
            state["reminders"] = [random.choice(IDLE_NOTES)]
            save_state(state)
            print(f"[auto_status] → {state['current_task']}")
    elif old_task in INTERNAL_TASKS or not old_task:
        # 已经是空闲状态，更新标签（时段可能变了）
        idle = get_idle_label()
        if idle != old_task:
            state["current_task"] = idle
            state["task_set_at"] = now.isoformat()
            state["auto_inferred"] = True
            save_state(state)


if __name__ == "__main__":
    main()

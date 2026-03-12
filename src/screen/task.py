#!/usr/bin/env python3
"""
prism_task.py — 任务进程管理器

像电脑进程一样管理任务：
  start  "写分析报告"    → 新建进程，成为当前任务
  finish                 → 结束当前任务，移到 done
  finish "写分析报告"    → 结束指定任务
  switch "修bug"         → 切换到已有的任务
  list                   → 列出所有活跃任务
  show                   → 显示当前屏幕状态

屏幕 NOW = 栈顶任务（最近 start 的）
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
STATE_FILE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_state.json"))
MAX_COMPLETED = 5

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


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(TZ).isoformat()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def sync_screen(state: dict):
    """从 active_tasks 同步到屏幕显示字段"""
    tasks = state.get("active_tasks", [])
    if tasks:
        state["current_task"] = tasks[0]["name"]
        state["task_set_at"] = tasks[0].get("started_at", datetime.now(TZ).isoformat())
    else:
        state["current_task"] = "待命中"
        state["task_set_at"] = datetime.now(TZ).isoformat()


def flush_to_screen():
    """立即推一帧到屏幕"""
    try:
        import importlib.util
        display_path = Path(__file__).parent / "display.py"
        spec = importlib.util.spec_from_file_location("prism_display", display_path)
        display = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(display)

        presence_file = STATE_FILE.parent / "prism_presence.json"
        present = True
        if presence_file.exists():
            try:
                p = json.loads(presence_file.read_text())
                present = p.get("present", True)
            except: pass

        _hour = datetime.now(TZ).hour
        _state = load_state()
        _dismissed = _state.get("summary_dismissed", False)

        if not present:
            img = display.render_dim_frame()
        elif 18 <= _hour < 20 and not _dismissed:
            img = display.render_summary_frame()
        else:
            img = display.render_frame()
        display.write_to_framebuffer(img, "/dev/fb0")
    except Exception as e:
        print(f"  (屏幕刷新: {e})")


def cmd_start(state, name):
    """开始新任务"""
    tasks = state.get("active_tasks", [])
    # 检查是否已存在
    for t in tasks:
        if t["name"] == name:
            # 已存在，移到栈顶
            tasks.remove(t)
            tasks.insert(0, t)
            print(f"  切换 → {name}")
            state["active_tasks"] = tasks
            sync_screen(state)
            return
    # 新任务
    tasks.insert(0, {
        "name": name,
        "started_at": datetime.now(TZ).isoformat(),
    })
    state["active_tasks"] = tasks
    sync_screen(state)
    # 换 note
    reminders = state.get("reminders", [])
    if not reminders or (len(reminders) == 1 and reminders[0] in IDLE_NOTES):
        state["reminders"] = [random.choice(IDLE_NOTES)]
    print(f"  ▶ 开始: {name} (共{len(tasks)}个活跃任务)")


def cmd_finish(state, name=None):
    """结束任务"""
    tasks = state.get("active_tasks", [])
    if not tasks:
        print("  没有活跃任务")
        return

    if name:
        # 结束指定任务
        target = None
        for t in tasks:
            if t["name"] == name:
                target = t
                break
        if not target:
            print(f"  找不到任务: {name}")
            return
        tasks.remove(target)
        finished_name = target["name"]
    else:
        # 结束栈顶（当前）任务
        target = tasks.pop(0)
        finished_name = target["name"]

    # 移到 done
    completed = state.get("completed", [])
    if finished_name not in completed:
        completed.insert(0, finished_name)
    state["completed"] = completed[:MAX_COMPLETED]
    state["active_tasks"] = tasks
    sync_screen(state)
    # 换 note
    state["reminders"] = [random.choice(IDLE_NOTES)]
    print(f"  ■ 完成: {finished_name} → done")
    if tasks:
        print(f"  当前: {tasks[0]['name']} (剩{len(tasks)}个)")
    else:
        print(f"  无活跃任务")


def cmd_list(state):
    """列出所有活跃任务"""
    tasks = state.get("active_tasks", [])
    if not tasks:
        print("  (无活跃任务)")
        return
    for i, t in enumerate(tasks):
        marker = "→" if i == 0 else " "
        name = t["name"]
        started = t.get("started_at", "?")[:16]
        print(f"  {marker} [{i}] {name}  (since {started})")


def cmd_show(state):
    """显示屏幕状态"""
    print(f"  NOW:  {state.get('current_task', '?')}")
    print(f"  DONE: {state.get('completed', [])}")
    print(f"  NOTE: {state.get('reminders', [])}")
    tasks = state.get("active_tasks", [])
    print(f"  活跃任务: {len(tasks)}个")
    for i, t in enumerate(tasks):
        print(f"    [{i}] {t['name']}")


def main():
    parser = argparse.ArgumentParser(description="Prism 任务进程管理器")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="开始新任务")
    p_start.add_argument("name", help="任务名(简短)")

    p_finish = sub.add_parser("finish", help="结束任务")
    p_finish.add_argument("name", nargs="?", help="任务名(默认结束当前)")

    p_switch = sub.add_parser("switch", help="切换到已有任务")
    p_switch.add_argument("name", help="任务名")

    p_note = sub.add_parser("note", help="设置提醒")
    p_note.add_argument("text", help="提醒内容")

    sub.add_parser("list", help="列出活跃任务")
    sub.add_parser("show", help="显示屏幕状态")
    sub.add_parser("clear", help="清空所有(新一天)")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    state = load_state()

    # 确保 active_tasks 存在
    if "active_tasks" not in state:
        state["active_tasks"] = []
        # 迁移旧的 current_task
        old = state.get("current_task", "")
        if old and old not in ("待命中", "空闲", ""):
            state["active_tasks"] = [{"name": old, "started_at": state.get("task_set_at", datetime.now(TZ).isoformat())}]

    if args.cmd == "start":
        cmd_start(state, args.name)
    elif args.cmd == "finish":
        cmd_finish(state, getattr(args, "name", None))
    elif args.cmd == "switch":
        cmd_start(state, args.name)  # start 已处理切换
    elif args.cmd == "note":
        state["reminders"] = [args.text]
        print(f"  note → {args.text}")
    elif args.cmd == "list":
        cmd_list(state)
    elif args.cmd == "show":
        cmd_show(state)
    elif args.cmd == "clear":
        state["active_tasks"] = []
        state["completed"] = []
        state["reminders"] = [random.choice(IDLE_NOTES)]
        sync_screen(state)
        print("  已清空")

    if args.cmd in ("start", "finish", "switch", "note", "clear"):
        save_state(state)
        flush_to_screen()


if __name__ == "__main__":
    main()

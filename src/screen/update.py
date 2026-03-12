#!/usr/bin/env python3
"""
prism_update.py — Prism 状态更新 CLI

核心逻辑：NOW 结束 → 自动变成 DONE → 新的 NOW 开始
          NOTE 空的时候 → 随机一句话，提供情绪价值

用法：
  python3 prism_update.py --task "分析录音数据"     # 旧 task 自动进 done
  python3 prism_update.py --done "手动补一条完成项"
  python3 prism_update.py --note "记得喝水"
  python3 prism_update.py --clear-notes
  python3 prism_update.py --clear-done              # 每天重置用
  python3 prism_update.py --set-done "A" "B"        # 替换整个 done 列表
  python3 prism_update.py --status "空闲探索中"
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
EVENTS_FILE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_events.json"))
MAX_COMPLETED = 5   # 屏幕小，最多显示5条
MAX_REMINDERS = 3

# NOTE 为空时的随机填充 — 短诗句，不加表情，不截断
IDLE_NOTES = [
    "人间有味是清欢",
    "此心安处是吾乡",
    "一蓑烟雨任平生",
    "清风徐来水波不兴",
    "行到水穷处坐看云起时",
    "竹杖芒鞋轻胜马",
    "小舟从此逝江海寄余生",
    "掬水月在手弄花香满衣",
    "晚来天欲雪能饮一杯无",
    "春水碧于天画船听雨眠",
    "人生如逆旅我亦是行人",
    "山高月小水落石出",
    "云深不知处",
    "心远地自偏",
    "万物静观皆自得",
    "天地一沙鸥",
    "明月松间照清泉石上流",
    "绿蚁新醅酒红泥小火炉",
    "长风破浪会有时",
    "日日是好日",
]

# 不应该流转到 done 的 task（闲置/默认状态）
# 不应该流转到 done 的 task（闲置/默认状态）
# "跟饭团聊天"也不该出现在 task 里——要写真实在干啥
# 不应该流转到 done 的 task（内部状态/闲置）
IDLE_TASKS = {
    "空闲", "待命中", "等待中", "空闲探索中", "",
    "heartbeat巡检", "heartbeat 巡检", "后台定时任务运行中",
    "深夜自学中", "上午待命", "午间待命", "下午待命", "晚间待命", "深夜待命",
    "派帮手干活中",
}


def write_event(event_type: str, text: str, ttl: int = 30):
    """向 prism_events.json 写入一条事件（带文件锁）"""
    try:
        import fcntl
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 读取现有事件
        events = []
        if EVENTS_FILE.exists():
            try:
                with open(EVENTS_FILE, "r", encoding="utf-8") as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    try:
                        events = json.load(f).get("events", [])
                    finally:
                        fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                events = []
        # 追加新事件
        events.append({
            "type": event_type,
            "text": text,
            "timestamp": datetime.now(TZ).isoformat(),
            "ttl": ttl,
        })
        # 原子写回
        tmp = EVENTS_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump({"events": events}, f, ensure_ascii=False, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        tmp.replace(EVENTS_FILE)
        print(f"⚡ 事件已写入: [{event_type}] {text} (ttl={ttl}s)")
    except Exception as e:
        print(f"  ⚠️ 写入事件失败: {e}")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(TZ).isoformat()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)
    print(f"✅ 状态已更新: {STATE_FILE}")


def flush_to_screen():
    """立即推一帧到屏幕，不等 daemon 10秒轮询"""
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
        print(f"  ⚠️ 屏幕即时刷新失败: {e}")


def auto_fill_note(state: dict) -> bool:
    """NOTE 为空时自动填一句随机的话"""
    reminders = state.get("reminders", [])
    if not reminders:
        state["reminders"] = [random.choice(IDLE_NOTES)]
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Prism 状态更新工具")
    parser.add_argument("--task", metavar="TEXT", help="设置当前任务（旧 task 自动转 done）")
    parser.add_argument("--done", metavar="TEXT", help="手动添加已完成项")
    parser.add_argument("--note", metavar="TEXT", help="添加提醒（最多3条）")
    parser.add_argument("--clear-notes", action="store_true", help="清除所有提醒（会自动填充随机语）")
    parser.add_argument("--clear-done", action="store_true", help="清空已完成列表")
    parser.add_argument("--set-done", metavar="TEXT", nargs="+", help="替换已完成列表")
    parser.add_argument("--dismiss", action="store_true", help="关闭便签模式")
    parser.add_argument("--status", metavar="TEXT", help="设置状态文字（current_task 别名，不触发 done 流转）")
    parser.add_argument("--show", action="store_true", help="显示当前状态")
    parser.add_argument("--new-day", action="store_true", help="新的一天：清空 done + 重置 note")
    parser.add_argument("--event", metavar="TYPE:TEXT",
                        help="触发事件闪屏，格式 type:text（如 alert:比亚迪涨停）")
    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    state = load_state()

    if args.show:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return

    # --event: 写入事件文件（独立于状态更新，立即返回）
    if args.event:
        parts = args.event.split(":", 1)
        if len(parts) == 2:
            ev_type, ev_text = parts[0].strip(), parts[1].strip()
        else:
            ev_type, ev_text = "info", args.event.strip()
        if ev_type not in ("alert", "info", "done"):
            print(f"  ⚠️ 未知事件类型 {ev_type!r}，使用 info")
            ev_type = "info"
        write_event(ev_type, ev_text)
        return  # --event 不影响状态，直接退出

    changed = False

    # --new-day: 每天开始时重置
    if args.new_day:
        state["completed"] = []
        state["reminders"] = [random.choice(IDLE_NOTES)]
        state["summary_dismissed"] = False
        changed = True
        print("  🌅 新的一天！done 已清空，note 已重置")

    # --task: 设置新任务，旧任务自动转 done
    if args.task:
        old_task = state.get("current_task", "")
        # 旧 task 有内容且不是闲置状态 → 自动转到 done
        if old_task and old_task not in IDLE_TASKS \
           and not old_task.endswith("待命") and "待命" not in old_task \
           and "帮手" not in old_task:
            completed = state.get("completed", [])
            if old_task not in completed:
                completed.insert(0, old_task)
            state["completed"] = completed[:MAX_COMPLETED]
            print(f"  ✅ done += {old_task!r}")
        state["current_task"] = args.task
        state["task_set_at"] = datetime.now(TZ).isoformat()
        changed = True
        print(f"  🔄 now → {args.task}")

    # --status: 直接设置，不触发流转（用于闲置/默认状态）
    if args.status:
        state["current_task"] = args.status
        changed = True
        print(f"  current_task → {args.status}")

    if args.done:
        completed = state.get("completed", [])
        if args.done not in completed:
            completed.insert(0, args.done)
        state["completed"] = completed[:MAX_COMPLETED]
        changed = True
        print(f"  completed += {args.done!r}")

    if args.note:
        reminders = state.get("reminders", [])
        # 替换掉自动填充的随机语
        if len(reminders) == 1 and reminders[0] in IDLE_NOTES:
            reminders = []
        if args.note not in reminders:
            reminders.append(args.note)
        state["reminders"] = reminders[-MAX_REMINDERS:]
        changed = True
        print(f"  note += {args.note!r}")

    if args.clear_done:
        state["completed"] = []
        changed = True
        print("  completed 已清空")

    if args.set_done:
        state["completed"] = list(args.set_done)[:MAX_COMPLETED]
        changed = True
        print(f"  completed 已替换为: {args.set_done}")

    if args.clear_notes:
        state["reminders"] = []
        changed = True
        print("  reminders 已清空")

    if args.dismiss:
        state["summary_dismissed"] = True
        changed = True
        print("  便签模式已关闭")

    # 每次有变更时，如果 note 还是旧的随机语，换一句新的
    if changed:
        reminders = state.get("reminders", [])
        if not reminders or (len(reminders) == 1 and reminders[0] in IDLE_NOTES):
            state["reminders"] = [random.choice(IDLE_NOTES)]
            print(f"  💬 note → {state['reminders'][0]!r}")
    
    # NOTE 为空时兜底
    if auto_fill_note(state):
        changed = True
        print(f"  💬 note 自动填充: {state['reminders'][0]!r}")

    if changed:
        save_state(state)
        flush_to_screen()
    else:
        print("无变更（使用 --show 查看当前状态）")


if __name__ == "__main__":
    main()

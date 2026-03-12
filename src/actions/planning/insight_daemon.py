#!/usr/bin/env python3
"""
pi_insight_daemon.py — 智能洞察推送后台 daemon

功能：
- 每 5 分钟检查 insights.jsonl 中未推送的洞察
- 根据优先级决定推送渠道（Prism 闪屏 / 飞书队列）
- 消费 stock_alerts.json → 转为 Prism 事件
- 安静时间（23:00-08:00）不推飞书

启动：
  python3 pi_insight_daemon.py          # 前台
  python3 pi_insight_daemon.py --daemon # 后台
  python3 pi_insight_daemon.py --once   # 跑一次就退出（测试用）
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
MEMORY_DIR = WORKSPACE / "memory"
LOG_FILE = WORKSPACE / "logs" / "pi_insight_daemon.log"

INSIGHTS_FILE = INTEL_DIR / "insights.jsonl"
FEISHU_QUEUE = INTEL_DIR / "feishu_queue.jsonl"
PRISM_EVENTS_FILE = MEMORY_DIR / "prism_events.json"
STOCK_ALERTS_FILE = MEMORY_DIR / "stock_alerts.json"

CHECK_INTERVAL = 300  # 5 minutes
MAX_DAILY_FEISHU = 3

# Logging
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("pi_insight")


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def save_jsonl(path: Path, records: list):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def atomic_write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def is_quiet_hours() -> bool:
    hour = datetime.now(TZ).hour
    return hour >= 23 or hour < 8


def today_feishu_count() -> int:
    """Count how many feishu messages sent today."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    queue = load_jsonl(FEISHU_QUEUE)
    return sum(1 for q in queue if q.get("sent") and q.get("timestamp", "").startswith(today))


def decide_channel(insight: dict) -> str | None:
    """Decide notification channel based on priority and context."""
    priority = insight.get("priority", 1)
    
    if is_quiet_hours():
        if priority >= 4:
            return "prism"
        return None
    
    if priority >= 4 and today_feishu_count() < MAX_DAILY_FEISHU:
        return "feishu"
    if priority >= 2:
        return "prism"
    return None


def trigger_prism_event(event_type: str, text: str, ttl: int = 30):
    """Write event to prism_events.json for Prism daemon to pick up."""
    data = load_json(PRISM_EVENTS_FILE, {"events": []})
    events = data.get("events", [])
    events.append({
        "type": event_type,
        "text": text,
        "timestamp": datetime.now(TZ).isoformat(),
        "ttl": ttl,
    })
    data["events"] = events
    atomic_write_json(PRISM_EVENTS_FILE, data)
    log.info(f"📺 Prism 事件: [{event_type}] {text}")


def append_feishu_queue(insight: dict):
    """Append to feishu queue for later delivery."""
    queue = load_jsonl(FEISHU_QUEUE)
    queue.append({
        "text": insight.get("text", ""),
        "priority": insight.get("priority", 1),
        "insight_id": insight.get("id", ""),
        "timestamp": datetime.now(TZ).isoformat(),
        "sent": False,
    })
    save_jsonl(FEISHU_QUEUE, queue)
    log.info(f"📨 飞书队列: {insight.get('text', '')[:50]}")


def is_pushworthy(rec: dict) -> bool:
    """Gate: only push insights that are genuinely useful to the user.
    
    Principles:
    - 宁可不推也不要推错
    - 只推 actionable、用户能感知到价值的内容
    - 低质量录音转写碎片一律不推
    """
    typ = rec.get("type", "")
    priority = rec.get("priority", 0)
    text = rec.get("text", "")

    # Weekly report — curated, always OK
    if typ == "weekly_report" and priority >= 4:
        return True

    # Intent stale — already heavily filtered in generator, allow
    if typ == "intent_stale" and priority >= 3:
        return True

    # Stock alerts — time-sensitive, allow
    if typ == "stock_alert":
        return True

    # Everything else (anomaly, observation, reminder) — suppress for now.
    # These are generated from noisy transcription data and mostly useless.
    # TODO: re-enable when data quality improves or add LLM quality gate.
    return False


def process_insights():
    """Check and push pending insights. Only pushes high-quality content."""
    records = load_jsonl(INSIGHTS_FILE)
    changed = False
    pushed_count = 0

    for rec in records:
        if rec.get("pushed"):
            continue

        if not is_pushworthy(rec):
            # Mark as skipped so we don't re-check every cycle
            rec["pushed"] = True
            rec["pushed_via"] = "skipped_low_quality"
            rec["pushed_at"] = datetime.now(TZ).isoformat()
            changed = True
            continue
        
        channel = decide_channel(rec)
        if channel == "prism":
            etype = "info"
            if rec.get("type") in ("anomaly", "intent_stale"):
                etype = "alert"
            elif rec.get("type") in ("completed", "positive"):
                etype = "done"
            trigger_prism_event(etype, rec.get("text", "")[:30])
            rec["pushed"] = True
            rec["pushed_via"] = "prism"
            rec["pushed_at"] = datetime.now(TZ).isoformat()
            changed = True
            pushed_count += 1
        elif channel == "feishu":
            append_feishu_queue(rec)
            rec["pushed"] = True
            rec["pushed_via"] = "feishu"
            rec["pushed_at"] = datetime.now(TZ).isoformat()
            changed = True
            pushed_count += 1

    if changed:
        save_jsonl(INSIGHTS_FILE, records)

    return pushed_count


def process_stock_alerts():
    """Consume stock alerts and convert to Prism events."""
    if not STOCK_ALERTS_FILE.exists():
        return 0
    
    try:
        data = load_json(STOCK_ALERTS_FILE, {})
        alerts = data.get("alerts", [])
        if not alerts:
            return 0
        
        count = 0
        for alert in alerts:
            text = alert.get("text", "")
            if text:
                trigger_prism_event("alert", text[:30])
                count += 1
        
        # Clear processed alerts
        atomic_write_json(STOCK_ALERTS_FILE, {"alerts": [], "last_cleared": datetime.now(TZ).isoformat()})
        return count
    except Exception as e:
        log.warning(f"处理盯盘信号失败: {e}")
        return 0


def deliver_feishu_queue():
    """Try to deliver queued feishu messages via pi_action feedback file."""
    queue_file = INTEL_DIR / "feishu_queue.jsonl"
    if not queue_file.exists():
        return 0

    queue = load_jsonl(queue_file)
    unsent = [q for q in queue if not q.get("sent")]
    if not unsent:
        return 0

    # Write consolidated message to a notification file
    # The main session or heartbeat will pick this up
    notif_file = INTEL_DIR / "pending_notifications.json"
    notifications = load_json(notif_file, {"items": []})

    sent = 0
    for q in unsent:
        notifications["items"].append({
            "text": q.get("text", ""),
            "priority": q.get("priority", 1),
            "timestamp": datetime.now(TZ).isoformat(),
            "source": q.get("action_id", q.get("insight_id", "unknown")),
        })
        q["sent"] = True
        q["sent_at"] = datetime.now(TZ).isoformat()
        sent += 1

    if sent > 0:
        # Keep only last 50 notifications
        notifications["items"] = notifications["items"][-50:]
        atomic_write_json(notif_file, notifications)

        # Update queue
        tmp = queue_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for q in queue:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        tmp.replace(queue_file)
        log.info(f"📨 飞书通知已排队: {sent} 条")

    return sent


def cleanup_old_insights():
    """Remove pushed insights older than 7 days."""
    records = load_jsonl(INSIGHTS_FILE)
    now = datetime.now(TZ)
    cutoff = (now - timedelta(days=7)).isoformat()
    
    before = len(records)
    records = [r for r in records if not (r.get("pushed") and r.get("date", "9999") < cutoff[:10])]
    
    if len(records) < before:
        save_jsonl(INSIGHTS_FILE, records)
        log.info(f"🧹 清理了 {before - len(records)} 条过期洞察")


def run_once():
    """Run one cycle."""
    pushed = process_insights()
    alerts = process_stock_alerts()
    delivered = deliver_feishu_queue()
    cleanup_old_insights()
    
    if pushed or alerts or delivered:
        log.info(f"✅ 周期完成: 推送 {pushed} 洞察, {alerts} 盯盘, {delivered} 飞书通知")
    else:
        log.debug("周期完成: 无待处理")


def main_loop():
    log.info("🚀 PI Insight Daemon 启动")
    INTEL_DIR.mkdir(parents=True, exist_ok=True)
    
    while True:
        try:
            run_once()
        except Exception as e:
            log.error(f"主循环异常: {e}")
        time.sleep(CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="PI Insight Daemon")
    parser.add_argument("--daemon", action="store_true", help="后台模式")
    parser.add_argument("--once", action="store_true", help="跑一次退出")
    args = parser.parse_args()

    if args.once:
        run_once()
        return

    if args.daemon:
        pid = os.fork()
        if pid > 0:
            print(f"✅ PI Insight Daemon 后台启动 (pid={pid})")
            sys.exit(0)
        os.setsid()
        sys.stdin = open(os.devnull, "r")

    main_loop()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
晨间 Brief 推送脚本

每天早上自动执行：
1. 用昨天的数据生成 Brief
2. 格式化为人类可读文本
3. 直接发送到飞书（通过 tenant_access_token API）
4. 输出到 stdout（备用，供 cron announce）

用法：
  # 直接运行（用昨天数据）
  python3 src/services/morning_push.py

  # 指定日期
  python3 src/services/morning_push.py --date 2026-03-12

  # 输出到文件
  python3 src/services/morning_push.py --output memory/services/brief_today.txt

设置为定时任务（推荐）：
  OpenClaw cron: 每天 8:30 执行本脚本
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 确保可以从项目根目录导入
_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))

# 设置日志
_log_dir = _root / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_file = _log_dir / "morning_push.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("morning_push")

FEISHU_USER_IDS = [
    "ou_f305f404023133b798c664548d5a4304",
    # ou_aadea4b6794e6c4fae3abee4bb72017e — cross-app error, skip
]
FEISHU_APP_ID = "cli_a92c2197caf9dcc7"
FEISHU_DOMAIN = "https://open.feishu.cn"
OPENCLAW_JSON = Path.home() / ".openclaw/openclaw.json"


def get_yesterday(tz_offset: int = 8) -> str:
    """获取昨天的日期字符串"""
    tz = timezone(timedelta(hours=tz_offset))
    return (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")


def _http_post(url: str, payload: dict, headers: dict, timeout: int = 30) -> dict:
    """带重试的 HTTP POST"""
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            log.error(f"HTTP {e.code} on attempt {attempt+1}: {body[:300]}")
            if attempt < 2 and e.code in (429, 500, 502, 503):
                time.sleep(2 ** attempt * 2)
                continue
            raise
        except Exception as e:
            log.error(f"Request error on attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise RuntimeError("All retries exhausted")


def get_tenant_access_token() -> str | None:
    """从 openclaw.json 读 appSecret，换取 tenant_access_token"""
    try:
        cfg = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8"))
        channels = cfg.get("channels", {})
        feishu = channels.get("feishu", {})
        app_secret = feishu.get("appSecret", "")
        if not app_secret:
            log.error("appSecret not found in openclaw.json channels.feishu")
            return None

        result = _http_post(
            f"{FEISHU_DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": FEISHU_APP_ID, "app_secret": app_secret},
            {"Content-Type": "application/json"},
        )
        token = result.get("tenant_access_token", "")
        if not token:
            log.error(f"Failed to get tenant_access_token: {result}")
            return None
        log.info("Got tenant_access_token OK")
        return token
    except Exception as e:
        log.error(f"get_tenant_access_token error: {e}")
        return None


def _text_to_post_content(text: str) -> dict:
    """把 format_brief_message 输出的 markdown 转成飞书 Interactive Card 格式。

    v5: format_brief_message 已输出完整 markdown（含 **加粗**、列表等），
    直接透传到 card 的 markdown element 即可。
    - header: 第一行作标题（蓝色）
    - body: markdown element 包含剩余内容
    """
    lines = text.split("\n")
    # 标题：取第一行，去掉 emoji 前缀
    title = lines[0].strip() if lines else "早安 Brief"
    body_lines = lines[1:] if len(lines) > 1 else []

    # 直接透传 markdown，飞书 card 原生支持 **加粗** 和列表
    body_md = "\n".join(line for line in body_lines).strip()

    return {
        "elements": [
            {
                "tag": "markdown",
                "content": body_md,
            }
        ],
        "header": {
            "title": {
                "tag": "plain_text",
                "content": title,
            },
            "template": "blue",
        },
    }


def send_feishu_post(user_id: str, text: str, token: str) -> bool:
    """发送飞书私信（Interactive Card + markdown，支持加粗）"""
    try:
        card_content = _text_to_post_content(text)
        result = _http_post(
            f"{FEISHU_DOMAIN}/open-apis/im/v1/messages?receive_id_type=open_id",
            {
                "receive_id": user_id,
                "msg_type": "interactive",
                "content": json.dumps(card_content),
            },
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        code = result.get("code", -1)
        if code == 0:
            log.info(f"✅ Sent interactive card to {user_id}")
            return True
        else:
            log.error(f"Feishu API error code={code} msg={result.get('msg','')} for {user_id}")
            return False
    except Exception as e:
        log.error(f"send_feishu_post({user_id}) error: {e}")
        return False


def push_to_feishu(msg: str) -> bool:
    """推送消息到所有目标飞书用户，返回是否全部成功"""
    token = get_tenant_access_token()
    if not token:
        log.error("Cannot push to Feishu: no token")
        return False

    any_success = False
    for uid in FEISHU_USER_IDS:
        ok = send_feishu_post(uid, msg, token)
        if ok:
            any_success = True

    return any_success


def main():
    parser = argparse.ArgumentParser(description="晨间 Brief 推送")
    parser.add_argument("--date", help="数据日期 (默认: 昨天)", default=None)
    parser.add_argument("--output", help="输出文件路径 (默认: stdout)")
    parser.add_argument("--run-daily-first", action="store_true", default=True,
                        help="先跑 daily pipeline 再生成 brief (默认: true)")
    parser.add_argument("--skip-daily", action="store_true",
                        help="跳过 daily pipeline，直接生成 brief")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调 LLM，输出模拟数据")
    parser.add_argument("--no-feishu", action="store_true",
                        help="不直接发飞书，只输出到 stdout")
    args = parser.parse_args()

    exit_code = 0
    date = args.date or get_yesterday()
    log.info(f"📅 生成 Brief: {date} 数据")

    try:
        from src.services.generators.daily_brief import generate_brief, format_brief_message
        from src.services.pipeline import run_daily
    except Exception as e:
        log.error(f"Import error: {e}")
        sys.exit(1)

    # 1. 先跑 daily pipeline（会议/意图/情绪）
    if not args.skip_daily:
        log.info(f"🔄 Running daily pipeline for {date}...")
        try:
            daily_result = run_daily(date, dry_run=args.dry_run)
            if daily_result.errors:
                log.warning(f"⚠️ Daily pipeline errors: {daily_result.errors}")
            else:
                log.info("✅ Daily pipeline done")
        except Exception as e:
            log.error(f"Daily pipeline exception: {e}")
            # 非致命，继续生成 brief

    # 2. 生成 Brief
    log.info("🌅 Generating brief...")
    try:
        result = generate_brief(date, dry_run=args.dry_run)
        msg = format_brief_message(result)
    except Exception as e:
        log.error(f"generate_brief error: {e}")
        msg = f"☀️ 早上好\n\n⚠️ 今天的 Brief 生成失败了：{e}\n\n请检查日志：{_log_file}"
        exit_code = 1

    # 3. 直接发飞书（主路径）
    if not args.no_feishu and not args.dry_run:
        log.info("📨 Pushing to Feishu...")
        try:
            feishu_ok = push_to_feishu(msg)
            if feishu_ok:
                log.info("✅ Feishu push succeeded")
            else:
                log.error("❌ Feishu push failed for all users")
                exit_code = 1
        except Exception as e:
            log.error(f"Feishu push exception: {e}")
            exit_code = 1

    # 4. 输出（stdout 或文件，供 cron announce 兜底）
    if args.output:
        try:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(msg, encoding="utf-8")
            log.info(f"✅ Brief saved to {args.output}")
        except Exception as e:
            log.error(f"Failed to write output file: {e}")
    else:
        # stdout 输出 brief 文本（cron announce 会读取这个作兜底）
        print(msg)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()

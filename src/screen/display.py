#!/usr/bin/env python3
"""
ClawNode Prism — 桌面智能终端 POC 显示引擎
在 MHS35 3.5寸 SPI 屏（480x320）上显示 Prism 界面

支持两种渲染方式：
1. framebuffer 直写（/dev/fb1，SPI 屏专用）
2. Pygame 窗口模式（调试用）

界面模块：
- 时间 + 日期
- 当前状态（专注/空闲/等待）
- habit-predictor 预测摘要
- 最近一条通知
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TZ = timezone(timedelta(hours=8))
WEATHER_FILE = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_weather.json"))
WEATHER_MAX_AGE_HOURS = 2


def get_weather_display() -> str | None:
    """
    读取天气缓存，返回显示用短字符串，如 "11°C 晴天"。
    过期或不可用返回 None。
    """
    try:
        if not WEATHER_FILE.exists():
            return None
        data = json.loads(WEATHER_FILE.read_text(encoding="utf-8"))
        updated_at_str = data.get("updated_at", "")
        if not updated_at_str:
            return None
        updated_at = datetime.fromisoformat(updated_at_str)
        age_hours = (datetime.now(TZ) - updated_at).total_seconds() / 3600
        if age_hours > WEATHER_MAX_AGE_HOURS:
            return None
        temp = data.get("temperature", "")
        desc = data.get("description", "")
        if temp and desc:
            return f"{temp} {desc}"
        return None
    except Exception:
        return None


def get_weather_display_with_emoji() -> tuple[str | None, str | None]:
    """
    读取天气缓存，返回 (短文字, emoji)，如 ("11°C 晴天", "☀️")。
    过期或不可用返回 (None, None)。
    """
    try:
        if not WEATHER_FILE.exists():
            return None, None
        data = json.loads(WEATHER_FILE.read_text(encoding="utf-8"))
        updated_at_str = data.get("updated_at", "")
        if not updated_at_str:
            return None, None
        updated_at = datetime.fromisoformat(updated_at_str)
        age_hours = (datetime.now(TZ) - updated_at).total_seconds() / 3600
        if age_hours > WEATHER_MAX_AGE_HOURS:
            return None, None
        temp = data.get("temperature", "")
        desc = data.get("description", "")
        emoji = data.get("emoji", "")
        text = f"{temp} {desc}" if temp and desc else None
        return text, emoji or None
    except Exception:
        return None, None
SCREEN_W, SCREEN_H = 480, 320
HABITS_DIR = Path(os.path.expanduser("~/.openclaw/workspace/memory/habits"))
BG_COLOR = (15, 15, 25)           # 深蓝黑
ACCENT_COLOR = (100, 180, 255)    # 冰蓝
TEXT_COLOR = (220, 220, 230)      # 浅灰白
DIM_COLOR = (100, 100, 120)      # 暗灰
HIGHLIGHT_COLOR = (255, 200, 80)  # 暖黄
STATUS_COLORS = {
    "focus": (80, 200, 120),      # 绿色
    "idle": (100, 180, 255),      # 蓝色
    "waiting": (255, 200, 80),    # 黄色
    "offline": (100, 100, 120),   # 灰色
}


def get_font(size, kind="cn"):
    """获取字体。kind='cn' 中文字体，kind='en' 英文/数字字体"""
    if kind == "en":
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    else:
        paths = [
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]
    for fp in paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except:
                continue
    return ImageFont.load_default()


def is_cjk(ch):
    """判断字符是否是 CJK"""
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0xF900 <= cp <= 0xFAFF or 0x2E80 <= cp <= 0x2EFF or
            0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF or
            0x2000 <= cp <= 0x206F)


def draw_mixed_text(draw, pos, text, font_cn, font_en, fill):
    """混合渲染：中文用 cn 字体，英文/数字用 en 字体"""
    x, y = pos
    for ch in text:
        if is_cjk(ch):
            font = font_cn
        else:
            font = font_en
        bbox = draw.textbbox((0, 0), ch, font=font)
        ch_w = bbox[2] - bbox[0]
        draw.text((x, y), ch, font=font, fill=fill)
        x += ch_w


def load_predictions():
    """加载今天的预测数据"""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    pred_file = HABITS_DIR / "predictions" / f"{today}.json"
    if pred_file.exists():
        try:
            return json.load(open(pred_file))
        except:
            pass
    return None


def load_rules():
    """加载行为规则"""
    rules_file = HABITS_DIR / "behavior_rules.json"
    if rules_file.exists():
        try:
            return json.load(open(rules_file))
        except:
            pass
    return None


def load_presence():
    """读取摄像头存在检测结果"""
    p = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_presence.json"))
    if p.exists():
        try:
            return json.load(open(p))
        except:
            pass
    return {"present": True}


def get_current_status():
    """基于感知驱动状态，不是时间驱动"""
    now = datetime.now(TZ)
    hour = now.hour
    presence = load_presence()
    state = load_prism_state()
    is_here = presence.get("present", True)
    current_task = state.get("current_task", "")

    # 人不在 → 离开
    if not is_here:
        return "offline", "离开了"

    # 人在 + 有任务在做
    if current_task and current_task not in ("待命中", "空闲"):
        return "focus", current_task

    # 深夜
    if hour >= 23 or hour < 7:
        return "offline", "深夜"

    # 默认：在但空闲
    return "idle", "待命中"


def get_prediction_summary():
    """获取预测摘要文本，精简版"""
    preds = load_predictions()
    if not preds:
        return ["暂无预测数据"]

    lines = []
    for p in preds.get("predictions", [])[:5]:
        ptype = p.get("type", "")
        desc = p.get("description", "")
        conf = p.get("confidence", 0)
        action = p.get("suggested_action", "")

        # 按类型精简显示
        if ptype == "activity":
            # 提取时段和占比
            bucket = ""
            pct = ""
            if "morning" in desc: bucket = "上午"
            elif "afternoon" in desc: bucket = "下午"
            elif "evening" in desc: bucket = "晚间"
            elif "late-night" in desc: bucket = "深夜"
            m = re.search(r'(\d+%)', desc)
            if m: pct = m.group(1)
            if "高活跃" in desc:
                lines.append(f"[当前] {bucket} 活跃度{pct} - 高峰期")
            elif "较低" in desc:
                lines.append(f"[当前] {bucket} 活跃度{pct} - 低谷期")
            else:
                lines.append(f"[当前] {bucket} 活跃度{pct}")
        elif ptype == "upcoming_activity":
            bucket = ""
            if "afternoon" in desc: bucket = "下午"
            elif "evening" in desc: bucket = "晚间"
            elif "morning" in desc: bucket = "上午"
            m = re.search(r'(\d+%)', desc)
            pct = m.group(1) if m else ""
            lines.append(f"[下一段] {bucket} {pct}")
        elif ptype == "topic":
            # 提取话题
            topic = desc.split(":")[-1].strip().split("，")[0] if ":" in desc else desc
            lines.append(f"[热点] {topic}")
        elif ptype == "behavior":
            lines.append(f"[注意] 催进度高发时段!")
        elif ptype == "user_style":
            if len(desc) > 22:
                desc = desc[:20] + ".."
            lines.append(f"[风格] {desc}")
        elif ptype == "interruptibility":
            level = "可沟通" if "ok" in desc else "谨慎" if "careful" in desc else "勿扰" if "low" in desc else "待定"
            lines.append(f"[打扰] {level}")
        elif ptype == "weekday":
            if len(desc) > 22:
                desc = desc[:20] + ".."
            lines.append(f"[今日] {desc}")
        else:
            if len(desc) > 22:
                desc = desc[:20] + ".."
            lines.append(desc)

    return lines if lines else ["暂无预测"]


def get_today_summary():
    """获取今日关键信息"""
    now = datetime.now(TZ)
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday = weekday_names[now.weekday()]

    rules = load_rules()
    hints = []
    if rules:
        for r in rules.get("rules", []):
            rid = r.get("id", "")
            if "tuesday" in rid and now.weekday() == 1:
                hints.append("⚡ 冲刺日")
            elif "weekend" in rid and now.weekday() >= 5:
                hints.append("🌿 轻量模式")

    return weekday, hints


def get_status_glow():
    """状态高亮色"""
    status_key, _ = get_current_status()
    glows = {
        "focus":   (60, 200, 120),    # 绿
        "idle":    (80, 150, 255),    # 蓝
        "waiting": (255, 200, 80),   # 黄
        "offline": (50, 50, 70),     # 暗灰
    }
    return glows.get(status_key, (80, 80, 100))


def load_prism_state():
    """加载 Prism 状态数据"""
    state_file = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_state.json"))
    if state_file.exists():
        try:
            return json.load(open(state_file))
        except:
            pass
    return {}


def save_prism_state(state):
    """保存 Prism 状态数据"""
    state_file = Path(os.path.expanduser("~/.openclaw/workspace/memory/prism_state.json"))
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def render_flash_frame(event: dict):
    """
    事件闪屏帧渲染。
    event 格式:
      {"type": "alert"|"info"|"done", "text": "...", "timestamp": "...", "ttl": 30}
    - alert → 红色背景 (180,40,40)
    - info  → 蓝色背景 (40,80,180)
    - done  → 绿色背景 (40,140,60)
    """
    SCALE = 2
    W, H = SCREEN_W * SCALE, SCREEN_H * SCALE

    event_type = event.get("type", "info")
    bg_colors = {
        "alert": (180, 40, 40),
        "info":  (40, 80, 180),
        "done":  (40, 140, 60),
    }
    bg = bg_colors.get(event_type, (40, 80, 180))

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # ── 图标行 ──
    icon_map = {"alert": "⚠", "info": "ℹ", "done": "✓"}
    icon = icon_map.get(event_type, "•")
    font_icon = get_font(90, "en")
    bbox = draw.textbbox((0, 0), icon, font=font_icon)
    iw = bbox[2] - bbox[0]
    draw.text(((W - iw) // 2, 60), icon, font=font_icon, fill=(255, 255, 255, 220))

    # ── 主文本（中间大字，最多10个字）──
    text = event.get("text", "")
    if len(text) > 10:
        text = text[:10]
    font_big_cn = get_font(90, "cn")
    font_big_en = get_font(90, "en")

    # 计算混合文本宽度
    text_w = 0
    for ch in text:
        f = font_big_cn if is_cjk(ch) else font_big_en
        bb = draw.textbbox((0, 0), ch, font=f)
        text_w += bb[2] - bb[0]
    tx = max(20, (W - text_w) // 2)
    ty = H // 2 - 50
    draw_mixed_text(draw, (tx, ty), text, font_big_cn, font_big_en, (255, 255, 255))

    # ── 底部小字：时间 ──
    ts_str = event.get("timestamp", "")
    if ts_str:
        try:
            # 解析 ISO 时间，格式化为 HH:MM
            from datetime import datetime as _dt
            ts = _dt.fromisoformat(ts_str)
            ts_display = ts.strftime("%H:%M")
        except Exception:
            ts_display = ts_str[:16]
    else:
        ts_display = datetime.now(TZ).strftime("%H:%M")

    font_small = get_font(36, "en")
    bbox2 = draw.textbbox((0, 0), ts_display, font=font_small)
    sw = bbox2[2] - bbox2[0]
    draw.text(((W - sw) // 2, H - 70), ts_display, font=font_small, fill=(255, 255, 255, 180))

    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return img


def render_dim_frame():
    """暗屏模式——深色背景，只有时间和日期"""
    SCALE = 2
    W, H = SCREEN_W * SCALE, SCREEN_H * SCALE

    BG = (8, 8, 12)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    now = datetime.now(TZ)

    # 大时间 居中偏上
    font_time = get_font(120, "en")
    time_str = now.strftime("%H:%M")
    bbox = draw.textbbox((0, 0), time_str, font=font_time)
    tw = bbox[2] - bbox[0]
    tx = (W - tw) // 2
    draw.text((tx, H // 2 - 100), time_str, font=font_time, fill=(180, 180, 190))

    # 日期 居中 时间下方
    font_cn = get_font(44, "cn")
    font_en = get_font(44, "en")
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    date_str = f"{now.strftime('%m/%d')} {weekday_names[now.weekday()]}"
    date_w = 0
    for ch in date_str:
        f = font_cn if is_cjk(ch) else font_en
        bb = draw.textbbox((0, 0), ch, font=f)
        date_w += bb[2] - bb[0]
    dx = (W - date_w) // 2
    draw_mixed_text(draw, (dx, H // 2 + 40), date_str, font_cn, font_en, DIM_COLOR)

    # 天气行（日期下方，小字）
    weather_text = get_weather_display()
    if weather_text:
        font_wx_cn = get_font(36, "cn")
        font_wx_en = get_font(36, "en")
        wx_w = 0
        for ch in weather_text:
            f = font_wx_cn if is_cjk(ch) else font_wx_en
            bb = draw.textbbox((0, 0), ch, font=f)
            wx_w += bb[2] - bb[0]
        wx_x = (W - wx_w) // 2
        draw_mixed_text(draw, (wx_x, H // 2 + 100), weather_text, font_wx_cn, font_wx_en, DIM_COLOR)

    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return img


def render_summary_frame():
    """18:00 便签模式——今日摘要"""
    SCALE = 2
    W, H = SCREEN_W * SCALE, SCREEN_H * SCALE

    BG = (8, 8, 12)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_cn_title = get_font(48, "cn")
    font_en_title = get_font(48, "en")
    font_cn_body = get_font(38, "cn")
    font_en_body = get_font(38, "en")

    now = datetime.now(TZ)
    state = load_prism_state()
    M = 40
    y = 40

    # 标题
    draw_mixed_text(draw, (M, y), "TODAY", font_cn_title, font_en_title, HIGHLIGHT_COLOR)

    # 天气信息：在 TODAY 标题右侧显示 "11°C ☀️"
    wx_text, wx_emoji = get_weather_display_with_emoji()
    if wx_text or wx_emoji:
        font_wx_cn = get_font(40, "cn")
        font_wx_en = get_font(40, "en")
        # 构建天气短文字（只用 温度 + emoji，避免太长）
        try:
            # 从 wx_text 提取温度部分（如 "11°C 晴天" → "11°C"）
            temp_part = wx_text.split(" ")[0] if wx_text else ""
        except Exception:
            temp_part = wx_text or ""
        wx_display = f"{temp_part} {wx_emoji}" if temp_part and wx_emoji else (wx_text or wx_emoji or "")
        # 计算 TODAY 文字宽度，天气紧随其右
        today_w = 0
        for ch in "TODAY":
            bb = draw.textbbox((0, 0), ch, font=font_en_title)
            today_w += bb[2] - bb[0]
        wx_x = M + today_w + 20
        wx_y = y + 6  # 微调垂直对齐
        draw_mixed_text(draw, (wx_x, wx_y), wx_display, font_wx_cn, font_wx_en, ACCENT_COLOR)

    y += 64

    # 完成的事 — 动态显示，不超出屏幕
    completed = state.get("completed", [])
    max_y = 640 - 48  # 2x超采样下的底部安全线（留一行余量）
    reminders = state.get("reminders", [])
    # 预留明日提醒的空间：标题60 + 每项48 + 间距20
    reserved = (60 + len(reminders[:2]) * 48 + 20) if reminders else 0
    available_y = max_y - reserved

    for item in completed:
        if y + 48 > available_y:
            break
        if len(item) > 14:
            item = item[:13] + ".."
        draw_mixed_text(draw, (M, y), item, font_cn_body, font_en_body, (80, 200, 120))
        y += 48

    if not completed:
        draw_mixed_text(draw, (M, y), "今天很安静", font_cn_body, font_en_body, DIM_COLOR)
        y += 48

    y += 20

    # 明日提醒
    reminders = state.get("reminders", [])
    if reminders:
        draw_mixed_text(draw, (M, y), "TOMORROW", font_cn_title, font_en_title, ACCENT_COLOR)
        y += 60
        for item in reminders[:2]:
            if len(item) > 12:
                item = item[:11] + ".."
            draw_mixed_text(draw, (M, y), item, font_cn_body, font_en_body, (220, 220, 230))
            y += 48

    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return img


def _get_intelligent_content_safe():
    """安全调用 prism_intelligence，失败静默返回 None"""
    try:
        import sys as _sys
        import os as _os
        _scripts_dir = str(Path(_os.path.expanduser("~/.openclaw/workspace/scripts")))
        if _scripts_dir not in _sys.path:
            _sys.path.insert(0, _scripts_dir)
        from prism_intelligence import get_intelligent_content
        return get_intelligent_content()
    except Exception:
        return None


def render_frame():
    """渲染一帧——状态白板"""
    SCALE = 2
    W, H = SCREEN_W * SCALE, SCREEN_H * SCALE

    glow = get_status_glow()
    # 纯深黑背景，状态色只体现在文字上
    BG = (8, 8, 12)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 字体（全部加大）
    font_cn_title = get_font(60, "cn")
    font_en_title = get_font(60, "en")
    font_cn_body = get_font(48, "cn")
    font_en_body = get_font(48, "en")
    font_cn_label = get_font(48, "cn")
    font_en_label = get_font(48, "en")
    font_en_time = get_font(30, "en")

    now = datetime.now(TZ)
    state = load_prism_state()

    # 无光条，用背景色传达状态

    M = 40  # 统一边距

    # === 顶栏：小时间 居右 ===
    time_str = now.strftime("%H:%M")
    draw.text((W - 170, 28), time_str, font=font_en_time, fill=(60, 60, 80))

    # === 主区域 ===
    y = 80

    # ── 正在做（最突出）──
    current = state.get("current_task", "")
    is_idle = not current or current in ("待命中", "空闲", "")

    if is_idle:
        # 没有手动任务 → 使用智能内容
        intel = _get_intelligent_content_safe()
        if intel and intel.get("now_text"):
            now_text = intel["now_text"]
            # NOW 标签用淡蓝（待命状态）
            draw_mixed_text(draw, (M, y), "NOW", font_cn_label, font_en_label, (80, 150, 220))
            y += 60
            if len(now_text) > 10:
                now_text = now_text[:9] + ".."
            draw_mixed_text(draw, (M, y), now_text, font_cn_title, font_en_title, (180, 200, 230))
            y += 80
        else:
            # 连智能内容也没有 → 回退显示"待命中"
            draw_mixed_text(draw, (M, y), "NOW", font_cn_label, font_en_label, glow)
            y += 60
            draw_mixed_text(draw, (M, y), "待命中", font_cn_title, font_en_title, (120, 120, 140))
            y += 80
    else:
        # 有手动任务 → 优先显示
        draw_mixed_text(draw, (M, y), "NOW", font_cn_label, font_en_label, glow)
        y += 60
        if len(current) > 10:
            current = current[:9] + ".."
        draw_mixed_text(draw, (M, y), current, font_cn_title, font_en_title, (245, 245, 250))
        y += 80

    # 细分隔线
    draw.line([(M, y), (W - M, y)], fill=(30, 30, 45), width=2)
    y += 30

    # ── 已完成 ──
    completed = state.get("completed", [])
    if completed:
        item = completed[0]
        if len(item) > 10:
            item = item[:9] + ".."
        draw_mixed_text(draw, (M, y), "DONE", font_cn_label, font_en_label, (80, 200, 120))
        y += 58
        draw_mixed_text(draw, (M, y), item, font_cn_body, font_en_body, (140, 140, 160))
        y += 66

    # ── 提醒 / 智能注释 ──
    reminders = state.get("reminders", [])
    if reminders:
        item = reminders[0]
        if len(item) > 10:
            item = item[:9] + ".."
        draw_mixed_text(draw, (M, y), "NOTE", font_cn_label, font_en_label, HIGHLIGHT_COLOR)
        y += 58
        draw_mixed_text(draw, (M, y), item, font_cn_body, font_en_body, (220, 220, 230))
    elif is_idle:
        # 待命时：用智能 note_text 填充 NOTE 位
        intel = _get_intelligent_content_safe()
        if intel and intel.get("note_text"):
            note_text = intel["note_text"]
            if len(note_text) > 10:
                note_text = note_text[:9] + ".."
            draw_mixed_text(draw, (M, y), "NOTE", font_cn_label, font_en_label, (100, 120, 150))
            y += 58
            draw_mixed_text(draw, (M, y), note_text, font_cn_body, font_en_body, (150, 160, 180))

    # 底部留白

    # 缩放
    img = img.resize((SCREEN_W, SCREEN_H), Image.LANCZOS)
    return img


def write_to_framebuffer(img, fb_path="/dev/fb0"):
    """写入 framebuffer"""
    # MHS35: nonstd=1, big-endian, channel order GBR (R→G, G→B, B→R on this panel)
    raw = img.convert("RGB")
    pixels = raw.load()
    w, h = raw.size

    buf = bytearray(w * h * 2)
    idx = 0
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            pixel = ((b >> 3) << 11) | ((r >> 2) << 5) | (g >> 3)
            buf[idx] = (pixel >> 8) & 0xFF
            buf[idx + 1] = pixel & 0xFF
            idx += 2

    with open(fb_path, "wb") as fb:
        fb.write(buf)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    if mode == "save":
        # 保存为图片（预览模式）
        img = render_frame()
        out = Path(os.path.expanduser("~/.openclaw/workspace/src/screen/prism_preview.png"))
        img.save(out)
        print(f"✅ 预览已保存: {out}")
        return

    if mode == "fb" or (mode == "auto" and os.path.exists("/dev/fb0")):
        # framebuffer 模式
        print("🖥️ Prism 显示启动 (framebuffer)")
        while True:
            try:
                img = render_frame()
                write_to_framebuffer(img)
                time.sleep(10)  # 每10秒刷新
            except KeyboardInterrupt:
                print("\n⏹️ Prism 显示停止")
                break
            except Exception as e:
                print(f"渲染错误: {e}")
                time.sleep(5)
    else:
        # 单帧预览
        img = render_frame()
        out = Path(os.path.expanduser("~/.openclaw/workspace/src/screen/prism_preview.png"))
        img.save(out)
        print(f"✅ 预览已保存: {out}")
        print(f"（屏幕重启后用 fb 模式运行: python3 {__file__} fb）")


if __name__ == "__main__":
    main()

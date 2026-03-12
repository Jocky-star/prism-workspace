#!/usr/bin/env python3
"""
pi_perception.py — 个人智能理解系统·感知层

从 mf_scene_v2.3 JSON 中提取 4 类信号：
  1. 实体（人/地/话题/设备）→ entities.json
  2. 事件（SVO bullets）→ events.jsonl
  3. 意图（todos + 关键词匹配）→ intents.json
  4. 情境（活动/位置/情绪）→ contexts.jsonl

用法：
  python3 pi_perception.py 20251229          # 处理指定日期
  python3 pi_perception.py --all             # 处理所有历史
  python3 pi_perception.py --recent 7        # 最近7天
  python3 pi_perception.py --no-llm          # 跳过 LLM 意图分类
  python3 pi_perception.py --stats           # 打印统计
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
DATA_DIR = WORKSPACE / "data" / "daily-reports"
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

ENTITIES_FILE = INTEL_DIR / "entities.json"
EVENTS_FILE = INTEL_DIR / "events.jsonl"
INTENTS_FILE = INTEL_DIR / "intents.json"
CONTEXTS_FILE = INTEL_DIR / "contexts.jsonl"

INTEL_DIR.mkdir(parents=True, exist_ok=True)

# ── 意图关键词 ───────────────────────────────────────────
INTENT_KEYWORDS = re.compile(
    r"(我想|我要|我得|打算|准备|应该|得去|需要|计划|"
    r"试试|搞个|做个|弄个|买个|看看能不能|如果能|要是有|能不能)"
)
QUESTION_PATTERN = re.compile(r"[？?]$|^(你|他|她|它)(是|有|能|会)")
# Noise patterns for transcript source — daily-life utterances not worth tracking
NOISE_PATTERNS = re.compile(
    r"(吃|喝|拿|买菜|点餐|外卖|快递|厕所|洗手间|冒菜|火锅|奶茶|拉面|便利店|超市|快递|取件|倒垃圾|洗碗|洗澡)"
)


# ── 工具函数 ──────────────────────────────────────────────

def atomic_write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                lines.append(json.loads(line))
            except Exception:
                pass
    return lines


def save_jsonl(path: Path, records: list):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def scene_duration_min(scene: dict) -> float:
    """Calculate scene duration in minutes."""
    try:
        start = scene.get("start_sec", 0)
        end = scene.get("end_sec", start)
        return max(0, (end - start)) / 60.0
    except Exception:
        return 0.0


def load_daily_report(date_str: str) -> dict | None:
    """Load a daily report JSON file, return content dict or None."""
    fpath = DATA_DIR / f"{date_str}.json"
    if not fpath.exists():
        return None
    try:
        d = json.loads(fpath.read_text(encoding="utf-8"))
        items = d.get("items", [])
        if not items:
            return None
        content = items[0].get("content", {})
        return content
    except Exception as e:
        print(f"  ⚠️ 读取 {date_str} 失败: {e}", file=sys.stderr)
        return None


def get_all_dates() -> list[str]:
    """Get all available date strings, sorted."""
    dates = []
    for f in sorted(DATA_DIR.iterdir()):
        if f.suffix == ".json" and f.stem.isdigit() and len(f.stem) == 8:
            dates.append(f.stem)
    return dates


# ── LLM 调用 ─────────────────────────────────────────────

def load_api_config() -> dict | None:
    try:
        cfg = json.loads(MODELS_JSON.read_text())
        lm = cfg["providers"]["litellm"]
        return {
            "base_url": lm["baseUrl"],
            "api_key": lm["apiKey"],
            "headers": lm.get("headers", {}),
            "model": "pa/claude-haiku-4-5-20251001",
        }
    except Exception:
        return None


def call_llm(prompt: str, api: dict, max_tokens: int = 2000) -> str | None:
    url = f"{api['base_url']}/chat/completions"
    payload = {
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api['api_key']}",
        **api.get("headers", {}),
    }
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt * 3)
    return None


# ── 实体提取器 ────────────────────────────────────────────

class EntityExtractor:
    def __init__(self):
        self.entities = load_json(ENTITIES_FILE, {
            "people": {}, "places": {}, "topics": {}, "devices": {},
            "_next_ids": {"people": 1, "places": 1, "topics": 1, "devices": 1}
        })
        if "_next_ids" not in self.entities:
            self.entities["_next_ids"] = {"people": 1, "places": 1, "topics": 1, "devices": 1}

    def _find_match(self, category: str, canonical: str, aliases: list) -> str | None:
        """Find existing entity by name matching."""
        store = self.entities.get(category, {})
        # Exact match
        if canonical in store:
            return canonical
        # Fuzzy match
        alias_set = set(aliases)
        for existing_name, existing_data in store.items():
            if existing_name.startswith("_"):
                continue
            # Edit distance check
            if edit_distance(canonical, existing_name) <= 2:
                existing_aliases = set(existing_data.get("aliases", []))
                if alias_set & existing_aliases or edit_distance(canonical, existing_name) <= 1:
                    return existing_name
            # Alias overlap
            existing_aliases = set(existing_data.get("aliases", []))
            if alias_set & existing_aliases:
                return existing_name
        return None

    def _upsert(self, category: str, canonical: str, aliases: list,
                date_str: str, daily_id: str, extra: dict = None):
        store = self.entities.setdefault(category, {})
        match_name = self._find_match(category, canonical, aliases)

        if match_name:
            entry = store[match_name]
            # Merge aliases
            existing_aliases = set(entry.get("aliases", []))
            existing_aliases.update(aliases)
            entry["aliases"] = sorted(existing_aliases)
            entry["last_seen"] = date_str
            daily_ids = entry.setdefault("daily_ids", {})
            daily_ids[date_str] = daily_id
            if extra:
                for k, v in extra.items():
                    if v and not entry.get(k):
                        entry[k] = v
        else:
            nids = self.entities["_next_ids"]
            gid = f"global_{category[0]}_{nids.get(category, 1):03d}"
            nids[category] = nids.get(category, 1) + 1
            entry = {
                "id": gid,
                "aliases": sorted(set(aliases)),
                "first_seen": date_str,
                "last_seen": date_str,
                "daily_ids": {date_str: daily_id},
            }
            if extra:
                entry.update({k: v for k, v in extra.items() if v})
            store[canonical] = entry

    def extract(self, content: dict, date_str: str):
        ec = content.get("entity_canon", {})

        # People
        for p in ec.get("people", []):
            canonical = p.get("canonical", "")
            if not canonical:
                continue
            self._upsert("people", canonical, p.get("aliases", []),
                         date_str, p.get("id", ""),
                         {"voice_profile": p.get("voice_profile")})

        # Places
        for p in ec.get("places", []):
            canonical = p.get("canonical", "")
            if not canonical:
                continue
            self._upsert("places", canonical, p.get("aliases", []),
                         date_str, p.get("id", ""))

        # Topics
        for t in ec.get("projects_or_topics", []):
            canonical = t.get("canonical", "")
            if not canonical:
                continue
            self._upsert("topics", canonical, t.get("aliases", []),
                         date_str, t.get("id", ""))

        # Devices
        for d in ec.get("devices_or_tools", []):
            canonical = d.get("canonical", "")
            if not canonical:
                continue
            self._upsert("devices", canonical, d.get("aliases", []),
                         date_str, d.get("id", ""))

        # Interaction stats from scenes
        scenes = content.get("scenes", [])
        for p in ec.get("people", []):
            pid = p.get("id", "")
            canonical = p.get("canonical", "")
            if not canonical or canonical == "用户":
                continue
            co_scenes = [s for s in scenes if pid in s.get("participants", [])]
            if not co_scenes:
                continue
            store = self.entities.get("people", {})
            entry = store.get(canonical) or store.get(
                self._find_match("people", canonical, p.get("aliases", [])) or ""
            )
            if not entry:
                continue
            interactions = entry.setdefault("interactions", {})
            day_data = interactions.setdefault(date_str, {
                "scenes": 0, "minutes": 0, "topics": [], "activities": []
            })
            day_data["scenes"] += len(co_scenes)
            day_data["minutes"] += sum(scene_duration_min(s) for s in co_scenes)
            for s in co_scenes:
                act = s.get("activity", {}).get("label", "")
                if act and act not in day_data["activities"]:
                    day_data["activities"].append(act)
                summary = s.get("summary", "")
                if summary:
                    # Extract short topic from summary
                    short = summary[:30]
                    if short not in day_data["topics"]:
                        day_data["topics"].append(short)

    def save(self):
        atomic_write_json(ENTITIES_FILE, self.entities)


# ── 事件提取器 ────────────────────────────────────────────

class EventExtractor:
    def __init__(self):
        self.events = load_jsonl(EVENTS_FILE)

    def remove_date(self, date_str: str):
        """Remove all events for a given date."""
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        self.events = [e for e in self.events if e.get("date") != fmt_date]

    def extract(self, content: dict, date_str: str):
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        self.remove_date(date_str)
        scenes = content.get("scenes", [])

        for scene in scenes:
            scene_time = scene.get("start_time", "")[:16]
            participants = scene.get("participants", [])
            activity = scene.get("activity", {}).get("label", "")
            location = ""
            loc_data = scene.get("location", {})
            if loc_data:
                cands = loc_data.get("candidates", [])
                if cands:
                    location = cands[0].get("name", "")

            for svo in scene.get("svo_bullets", []):
                if svo.get("confidence", 0) < 0.75:
                    continue
                self.events.append({
                    "date": fmt_date,
                    "time": scene_time,
                    "scene_id": scene.get("id", ""),
                    "svo": svo.get("text", ""),
                    "type": svo.get("type", ""),
                    "participants": participants,
                    "activity": activity,
                    "location": location,
                })

        # Macro frames as narrative events
        for frame in content.get("macro_frames", []):
            tr = frame.get("time_range", [])
            self.events.append({
                "date": fmt_date,
                "time": tr[0][:16] if tr else "",
                "scene_id": frame.get("id", ""),
                "svo": f"[叙事] {frame.get('title', '')}",
                "type": "narrative",
                "participants": frame.get("participants", []),
                "activity": frame.get("primary_activity", ""),
                "location": "",
                "topics": frame.get("key_topics", []),
                "outcomes": frame.get("outcomes", []),
                "mood": frame.get("mood_or_tone", ""),
            })

    def save(self):
        # Sort by date+time
        self.events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")))
        save_jsonl(EVENTS_FILE, self.events)


# ── 意图提取器 ────────────────────────────────────────────

class IntentExtractor:
    def __init__(self):
        self.intents = load_json(INTENTS_FILE, {
            "active": [], "completed": [], "expired": [], "_next_id": 1
        })
        if "_next_id" not in self.intents:
            self.intents["_next_id"] = len(self.intents.get("active", [])) + 1

    def _next_id(self) -> str:
        nid = self.intents["_next_id"]
        self.intents["_next_id"] = nid + 1
        return f"i_{nid:04d}"

    def _already_exists(self, text: str) -> bool:
        """Check if similar intent already exists."""
        text_clean = text.strip()[:50]
        for bucket in ("active", "completed", "expired"):
            for intent in self.intents.get(bucket, []):
                existing = intent.get("text", "").strip()[:50]
                if text_clean == existing or edit_distance(text_clean, existing) <= 3:
                    return True
        return False

    def extract_from_todos(self, content: dict, date_str: str):
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        for scene in content.get("scenes", []):
            for todo in scene.get("todos", []):
                text = todo.get("text", "").strip()
                if not text or self._already_exists(text):
                    continue
                self.intents["active"].append({
                    "id": self._next_id(),
                    "text": text,
                    "type": "todo",
                    "seriousness": min(5, max(1, int(todo.get("confidence", 0.5) * 5))),
                    "created_at": fmt_date,
                    "source": "todos",
                    "source_quote": text,
                    "status": "active",
                    "last_checked": fmt_date,
                })

    def extract_from_quotes(self, content: dict, date_str: str):
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        ec = content.get("entity_canon", {})

        # Find user's person ID (usually p1)
        user_ids = set()
        for p in ec.get("people", []):
            if p.get("canonical") == "用户" or p.get("id") == "p1":
                user_ids.add(p.get("id", ""))

        for scene in content.get("scenes", []):
            # Key quotes from user
            for q in scene.get("key_quotes", []):
                speaker = q.get("speaker", "")
                if speaker and speaker not in user_ids:
                    continue
                text = q.get("text", "").strip()
                if not text or len(text) < 4:
                    continue
                if QUESTION_PATTERN.search(text):
                    continue
                if INTENT_KEYWORDS.search(text):
                    if not self._already_exists(text):
                        self.intents["active"].append({
                            "id": self._next_id(),
                            "text": text,
                            "type": "unknown",
                            "seriousness": 3,
                            "created_at": fmt_date,
                            "source": "key_quote",
                            "source_quote": text,
                            "status": "active",
                            "last_checked": fmt_date,
                        })

            # Transcript from user
            for t in scene.get("transcript", []):
                maps_to = t.get("maps_to", "")
                if maps_to and maps_to not in user_ids:
                    continue
                text = t.get("text", "").strip()
                if not text or len(text) < 6:
                    continue
                if QUESTION_PATTERN.search(text):
                    continue
                if INTENT_KEYWORDS.search(text):
                    # Filter out short daily-life utterances from transcript
                    if len(text) < 10 and re.search(r"(要|想)", text):
                        continue
                    if NOISE_PATTERNS.search(text):
                        continue
                    if not self._already_exists(text):
                        self.intents["active"].append({
                            "id": self._next_id(),
                            "text": text,
                            "type": "unknown",
                            "seriousness": 3,
                            "created_at": fmt_date,
                            "source": "transcript",
                            "source_quote": text,
                            "status": "active",
                            "last_checked": fmt_date,
                        })

    def classify_with_llm(self, api: dict):
        """Classify unknown intents using LLM."""
        unknowns = [i for i in self.intents["active"] if i.get("type") == "unknown"]
        if not unknowns:
            return 0

        # Batch up to 20 at a time
        classified = 0
        for batch_start in range(0, len(unknowns), 20):
            batch = unknowns[batch_start:batch_start + 20]
            items = "\n".join(f"{i+1}. {intent['text']}" for i, intent in enumerate(batch))

            prompt = f"""请对以下意图进行分类。每条意图请回答：
1. 类型：todo（具体待办）/ idea（创意想法）/ plan（中期计划）/ wish（愿望/随口说说）
2. 认真程度：1-5分（5最认真，1是随口说说）

输出 JSON 数组：[{{"index": 1, "type": "todo", "seriousness": 4}}, ...]

意图列表：
{items}

只输出 JSON，不要其他文字。"""

            result = call_llm(prompt, api, max_tokens=1500)
            if not result:
                continue

            try:
                # Extract JSON from response
                json_match = re.search(r'\[.*\]', result, re.DOTALL)
                if json_match:
                    classifications = json.loads(json_match.group())
                    for c in classifications:
                        idx = c.get("index", 0) - 1
                        if 0 <= idx < len(batch):
                            batch[idx]["type"] = c.get("type", "unknown")
                            batch[idx]["seriousness"] = min(5, max(1, c.get("seriousness", 3)))
                            classified += 1
            except Exception:
                pass

        return classified

    def save(self):
        atomic_write_json(INTENTS_FILE, self.intents)


# ── 情境提取器 ────────────────────────────────────────────

class ContextExtractor:
    def __init__(self):
        self.contexts = load_jsonl(CONTEXTS_FILE)

    def remove_date(self, date_str: str):
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        self.contexts = [c for c in self.contexts if c.get("date") != fmt_date]

    def extract(self, content: dict, date_str: str):
        fmt_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        self.remove_date(date_str)

        for scene in content.get("scenes", []):
            location = ""
            loc_data = scene.get("location", {})
            if loc_data:
                cands = loc_data.get("candidates", [])
                if cands:
                    location = cands[0].get("name", "")

            ctx = {
                "date": fmt_date,
                "scene_id": scene.get("id", ""),
                "start": scene.get("start_time", "")[:16],
                "end": scene.get("end_time", "")[:16],
                "activity": scene.get("activity", {}).get("label", ""),
                "activity_conf": scene.get("activity", {}).get("p", 0),
                "location": location,
                "participants": len(scene.get("participants", [])),
                "mood": scene.get("mood_or_tone", "") if "mood_or_tone" in scene else "",
            }

            # Optional fields
            if scene.get("context_tags"):
                ctx["tags"] = scene["context_tags"]
            if scene.get("acoustic_details"):
                ad = scene["acoustic_details"]
                ctx["speech_clarity"] = ad.get("speech_clarity", "")
                ctx["noise_level"] = ad.get("avg_noise_level", 0)
            if scene.get("environment_index"):
                ei = scene["environment_index"]
                ctx["location_type"] = ei.get("location_type", "")
                ctx["time_of_day"] = ei.get("time_of_day", "")
                ctx["transport"] = ei.get("transport_mode", "")

            self.contexts.append(ctx)

        # Narrative frames
        for frame in content.get("macro_frames", []):
            tr = frame.get("time_range", [])
            self.contexts.append({
                "date": fmt_date,
                "scene_id": frame.get("id", ""),
                "start": tr[0][:16] if tr else "",
                "end": tr[1][:16] if len(tr) > 1 else "",
                "activity": frame.get("primary_activity", ""),
                "activity_conf": frame.get("confidence", 0),
                "location": "",
                "participants": len(frame.get("participants", [])),
                "mood": frame.get("mood_or_tone", ""),
                "type": "narrative",
                "title": frame.get("title", ""),
                "topics": frame.get("key_topics", []),
                "outcomes": frame.get("outcomes", []),
            })

    def save(self):
        self.contexts.sort(key=lambda c: (c.get("date", ""), c.get("start", "")))
        save_jsonl(CONTEXTS_FILE, self.contexts)


# ── 主流程 ────────────────────────────────────────────────

def process_date(date_str: str, entity_ext: EntityExtractor,
                 event_ext: EventExtractor, intent_ext: IntentExtractor,
                 context_ext: ContextExtractor) -> bool:
    content = load_daily_report(date_str)
    if content is None:
        return False

    entity_ext.extract(content, date_str)
    event_ext.extract(content, date_str)
    intent_ext.extract_from_todos(content, date_str)
    intent_ext.extract_from_quotes(content, date_str)
    context_ext.extract(content, date_str)
    return True


def print_stats():
    entities = load_json(ENTITIES_FILE, {})
    events = load_jsonl(EVENTS_FILE)
    intents = load_json(INTENTS_FILE, {})
    contexts = load_jsonl(CONTEXTS_FILE)

    people = {k: v for k, v in entities.get("people", {}).items() if not k.startswith("_")}
    places = {k: v for k, v in entities.get("places", {}).items() if not k.startswith("_")}
    topics = {k: v for k, v in entities.get("topics", {}).items() if not k.startswith("_")}

    print(f"\n📊 感知层统计")
    print(f"  实体: {len(people)} 人 / {len(places)} 地点 / {len(topics)} 话题")
    print(f"  事件: {len(events)} 条")
    active = len(intents.get("active", []))
    completed = len(intents.get("completed", []))
    expired = len(intents.get("expired", []))
    print(f"  意图: {active} active / {completed} completed / {expired} expired")
    print(f"  情境: {len(contexts)} 条")

    dates = set()
    for e in events:
        dates.add(e.get("date", ""))
    for c in contexts:
        dates.add(c.get("date", ""))
    print(f"  覆盖天数: {len(dates)}")


def main():
    parser = argparse.ArgumentParser(description="PI 感知层")
    parser.add_argument("date", nargs="?", help="处理指定日期 (YYYYMMDD)")
    parser.add_argument("--all", action="store_true", help="处理全部历史")
    parser.add_argument("--recent", type=int, metavar="N", help="处理最近 N 天")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM 意图分类")
    parser.add_argument("--stats", action="store_true", help="打印统计")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    # Determine dates to process
    dates = []
    if args.all:
        dates = get_all_dates()
    elif args.recent:
        all_dates = get_all_dates()
        dates = all_dates[-args.recent:]
    elif args.date:
        dates = [args.date]
    else:
        parser.print_help()
        return

    print(f"🔍 感知层：处理 {len(dates)} 天数据")

    entity_ext = EntityExtractor()
    event_ext = EventExtractor()
    intent_ext = IntentExtractor()
    context_ext = ContextExtractor()

    processed = 0
    for i, date_str in enumerate(dates):
        try:
            ok = process_date(date_str, entity_ext, event_ext, intent_ext, context_ext)
            if ok:
                processed += 1
                print(f"  ✅ [{i+1}/{len(dates)}] {date_str}")
            else:
                print(f"  ⏭️  [{i+1}/{len(dates)}] {date_str} (无数据)")
        except Exception as e:
            print(f"  ❌ [{i+1}/{len(dates)}] {date_str}: {e}", file=sys.stderr)

    # LLM classification
    if not args.no_llm:
        api = load_api_config()
        if api:
            unknowns = [i for i in intent_ext.intents.get("active", []) if i.get("type") == "unknown"]
            if unknowns:
                print(f"\n🧠 LLM 意图分类：{len(unknowns)} 条...")
                classified = intent_ext.classify_with_llm(api)
                print(f"  ✅ 分类完成：{classified} 条")
        else:
            print("  ⚠️ 无法加载 API 配置，跳过 LLM 分类")

    # Save all
    print("\n💾 保存中...")
    entity_ext.save()
    event_ext.save()
    intent_ext.save()
    context_ext.save()

    print(f"\n✅ 感知完成：处理 {processed}/{len(dates)} 天")
    print_stats()


if __name__ == "__main__":
    main()

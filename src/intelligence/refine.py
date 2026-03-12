#!/usr/bin/env python3
"""
pi_refine.py — 个人智能理解系统·LLM 精炼层

用 LLM 做感知层/理解层无法完成的深度分析：
  1. 人物合并：把匿名称呼关联到真名
  2. 关系类型精判：结合对话上下文判断关系
  3. 决策模式提取：从意图和事件中发现决策风格
  4. 价值观提取：从高质量语录中提炼价值观
  5. 过期意图清理：判断哪些 intent 已完成/失效

用法：
  python3 pi_refine.py                 # 完整精炼
  python3 pi_refine.py --entity-merge  # 只跑人物合并
  python3 pi_refine.py --relationship  # 只跑关系精判
  python3 pi_refine.py --values        # 只跑价值观提取
  python3 pi_refine.py --intent-cleanup # 只跑意图清理
  python3 pi_refine.py --dry-run       # 预览不写入
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace"))
INTEL_DIR = WORKSPACE / "memory" / "intelligence"
MODELS_JSON = Path(os.path.expanduser("~/.openclaw/agents/main/agent/models.json"))

ENTITIES_FILE = INTEL_DIR / "entities.json"
EVENTS_FILE = INTEL_DIR / "events.jsonl"
INTENTS_FILE = INTEL_DIR / "intents.json"
CONTEXTS_FILE = INTEL_DIR / "contexts.jsonl"
PROFILE_FILE = INTEL_DIR / "profile.json"
RELATIONSHIPS_FILE = INTEL_DIR / "relationships.json"
PATTERNS_FILE = INTEL_DIR / "patterns.json"
REFINE_LOG = INTEL_DIR / "refine_log.jsonl"


def load_json(path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}


def load_jsonl(path) -> list:
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


def atomic_write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_api_config(model: str = "pa/claude-haiku-4-5-20251001") -> dict | None:
    try:
        cfg = json.loads(MODELS_JSON.read_text())
        lm = cfg["providers"]["litellm"]
        return {
            "base_url": lm["baseUrl"],
            "api_key": lm["apiKey"],
            "headers": lm.get("headers", {}),
            "model": model,
        }
    except Exception:
        return None


def call_llm(prompt: str, api: dict, max_tokens: int = 2000) -> str | None:
    url = f"{api['base_url']}/chat/completions"
    payload = {
        "model": api["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
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
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt * 3)
            else:
                print(f"  ⚠️ LLM 调用失败: {e}", file=sys.stderr)
    return None


def extract_json(text: str):
    """Extract JSON array or object from LLM response."""
    # Try array
    m = re.search(r'\[.*\]', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    # Try object
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return None


# ── 1. 人物合并 ──────────────────────────────────────────

def refine_entity_merge(api: dict, dry_run: bool = False) -> dict:
    """Use LLM to suggest merging anonymous entities."""
    entities = load_json(ENTITIES_FILE, {})
    people = {k: v for k, v in entities.get("people", {}).items() if not k.startswith("_")}

    if len(people) < 3:
        print("  人物太少，跳过合并")
        return {"merged": 0}

    # Build person summaries for LLM
    person_list = []
    for name, data in sorted(people.items()):
        interactions = data.get("interactions", {})
        days = sorted(interactions.keys())
        activities = set()
        for d, dd in interactions.items():
            for a in dd.get("activities", []):
                activities.add(a)
        topics_sample = []
        for d, dd in interactions.items():
            for t in dd.get("topics", []):
                if len(topics_sample) < 3:
                    topics_sample.append(t[:40])

        person_list.append({
            "name": name,
            "aliases": data.get("aliases", []),
            "first_seen": data.get("first_seen", ""),
            "last_seen": data.get("last_seen", ""),
            "days_seen": len(days),
            "total_scenes": sum(dd.get("scenes", 0) for dd in interactions.values()),
            "activities": list(activities)[:5],
            "topic_samples": topics_sample,
        })

    prompt = f"""以下是从录音中识别出的人物列表。很多是匿名描述（同事A、技术讨论者B），可能是同一个人。

请分析哪些人物可能是同一个人，给出合并建议。

判断依据：
- 出现时间段重叠
- 活动类型相似
- 话题内容关联
- aliases 交叉

人物列表：
{json.dumps(person_list, ensure_ascii=False, indent=2)}

输出 JSON 数组，每项是一个合并组：
[{{"canonical": "建议的统一名字", "members": ["人物1", "人物2"], "confidence": 0.8, "reason": "理由"}}]

如果没有值得合并的，输出空数组 []。
只输出 JSON，不要其他文字。"""

    result = call_llm(prompt, api, max_tokens=2000)
    if not result:
        return {"merged": 0, "error": "LLM 调用失败"}

    merges = extract_json(result)
    if not merges or not isinstance(merges, list):
        return {"merged": 0, "no_suggestions": True}

    # Filter by confidence
    confident_merges = [m for m in merges if m.get("confidence", 0) >= 0.7]

    if dry_run:
        print(f"  [DRY RUN] {len(confident_merges)} 个合并建议:")
        for m in confident_merges:
            print(f"    {m['members']} → {m['canonical']} (conf={m['confidence']}) | {m.get('reason','')}")
        return {"merged": 0, "suggestions": len(confident_merges)}

    # Apply merges
    merged_count = 0
    for merge in confident_merges:
        canonical = merge.get("canonical", "")
        members = merge.get("members", [])
        if len(members) < 2 or not canonical:
            continue

        # Find the member with most data as base
        base_name = None
        max_scenes = 0
        for name in members:
            if name in people:
                scenes = sum(d.get("scenes", 0) for d in people[name].get("interactions", {}).values())
                if scenes > max_scenes:
                    max_scenes = scenes
                    base_name = name

        if not base_name:
            continue

        # Merge all others into base
        base = entities["people"][base_name]
        for name in members:
            if name == base_name or name not in entities["people"]:
                continue
            other = entities["people"][name]

            # Merge aliases
            all_aliases = set(base.get("aliases", []))
            all_aliases.update(other.get("aliases", []))
            all_aliases.add(name)
            base["aliases"] = sorted(all_aliases)

            # Merge interactions
            base_interactions = base.setdefault("interactions", {})
            for day, day_data in other.get("interactions", {}).items():
                if day not in base_interactions:
                    base_interactions[day] = day_data
                else:
                    base_interactions[day]["scenes"] = base_interactions[day].get("scenes", 0) + day_data.get("scenes", 0)
                    base_interactions[day]["minutes"] = base_interactions[day].get("minutes", 0) + day_data.get("minutes", 0)
                    for t in day_data.get("topics", []):
                        if t not in base_interactions[day].get("topics", []):
                            base_interactions[day].setdefault("topics", []).append(t)
                    for a in day_data.get("activities", []):
                        if a not in base_interactions[day].get("activities", []):
                            base_interactions[day].setdefault("activities", []).append(a)

            # Update first/last seen
            if other.get("first_seen", "z") < base.get("first_seen", "z"):
                base["first_seen"] = other["first_seen"]
            if other.get("last_seen", "") > base.get("last_seen", ""):
                base["last_seen"] = other["last_seen"]

            # Remove merged entity
            del entities["people"][name]

        # Rename if needed
        if canonical != base_name:
            entities["people"][canonical] = base
            del entities["people"][base_name]

        merged_count += 1
        append_jsonl(REFINE_LOG, {
            "action": "entity_merge",
            "canonical": canonical,
            "members": members,
            "confidence": merge.get("confidence"),
            "timestamp": datetime.now(TZ).isoformat(),
        })

    if merged_count > 0:
        atomic_write_json(ENTITIES_FILE, entities)

    return {"merged": merged_count}


# ── 2. 关系类型精判 ──────────────────────────────────────

def refine_relationships(api: dict, dry_run: bool = False) -> dict:
    """Use LLM to refine relationship types."""
    entities = load_json(ENTITIES_FILE, {})
    relationships = load_json(RELATIONSHIPS_FILE, {})
    events = load_jsonl(EVENTS_FILE)

    # Find people with uncertain relationships
    uncertain = []
    for name, rel in relationships.items():
        if rel.get("type_confidence", 0) < 0.7 and rel["interaction_stats"]["total_scenes"] >= 5:
            uncertain.append(name)

    if not uncertain:
        print("  没有需要精判的关系")
        return {"refined": 0}

    # Build context for each uncertain person
    person_contexts = {}
    for name in uncertain[:10]:  # Limit batch
        rel = relationships[name]
        # Get sample events involving this person
        entity_data = entities.get("people", {}).get(name, {})
        person_id = entity_data.get("id", "")
        sample_svos = []
        for e in events:
            if person_id in e.get("participants", []) or name.lower() in e.get("svo", "").lower():
                sample_svos.append(e.get("svo", "")[:80])
                if len(sample_svos) >= 10:
                    break

        person_contexts[name] = {
            "aliases": entity_data.get("aliases", []),
            "total_scenes": rel["interaction_stats"]["total_scenes"],
            "total_minutes": rel["interaction_stats"]["total_minutes"],
            "co_activities": rel.get("co_activities", {}),
            "sample_events": sample_svos,
            "current_type": rel["type"],
        }

    prompt = f"""以下是录音数据中出现的人物，需要判断他们与用户（录音主人）的关系。

人物信息：
{json.dumps(person_contexts, ensure_ascii=False, indent=2)}

请为每个人判断关系类型，选择：
- colleague（同事，一起工作/开会为主）
- friend（朋友，社交/聚餐为主）
- family（家人，明确的亲属关系）
- mentor（导师/上级）
- service（服务人员，如教练、医生）
- acquaintance（泛泛之交）

输出 JSON：
{{"人名": {{"type": "colleague", "confidence": 0.8, "reason": "经常一起开会讨论技术"}}}}

只输出 JSON。"""

    result = call_llm(prompt, api, max_tokens=2000)
    if not result:
        return {"refined": 0, "error": "LLM 调用失败"}

    refinements = extract_json(result)
    if not refinements or not isinstance(refinements, dict):
        return {"refined": 0}

    if dry_run:
        print(f"  [DRY RUN] {len(refinements)} 个关系精判:")
        for name, r in refinements.items():
            old = relationships.get(name, {}).get("type", "?")
            print(f"    {name}: {old} → {r.get('type', '?')} (conf={r.get('confidence')}) | {r.get('reason','')}")
        return {"refined": 0, "suggestions": len(refinements)}

    refined = 0
    for name, r in refinements.items():
        if name in relationships:
            old_type = relationships[name]["type"]
            new_type = r.get("type", old_type)
            new_conf = r.get("confidence", 0.5)
            if new_conf >= 0.6:
                relationships[name]["type"] = new_type
                relationships[name]["type_confidence"] = new_conf
                refined += 1
                append_jsonl(REFINE_LOG, {
                    "action": "relationship_refine",
                    "name": name,
                    "old_type": old_type,
                    "new_type": new_type,
                    "confidence": new_conf,
                    "reason": r.get("reason", ""),
                    "timestamp": datetime.now(TZ).isoformat(),
                })

    if refined > 0:
        atomic_write_json(RELATIONSHIPS_FILE, relationships)

    return {"refined": refined}


# ── 3. 价值观提取 ─────────────────────────────────────────

def refine_values(api: dict, dry_run: bool = False) -> dict:
    """Extract user values from intents and high-seriousness quotes."""
    intents = load_json(INTENTS_FILE, {})
    profile = load_json(PROFILE_FILE, {})

    # Gather high-quality user statements
    statements = []
    for intent in intents.get("active", []):
        if intent.get("seriousness", 0) >= 3 and intent.get("type") in ("idea", "plan"):
            statements.append(intent.get("text", "")[:100])
    for intent in intents.get("active", []):
        if intent.get("seriousness", 0) >= 4 and intent.get("type") == "todo":
            statements.append(intent.get("text", "")[:100])

    if len(statements) < 5:
        print("  高质量语料不足，跳过价值观提取")
        return {"extracted": 0}

    # Limit to avoid token explosion
    statements = statements[:50]

    prompt = f"""以下是一个用户在日常工作生活中说过的话（从录音中提取）。
请从中提炼这个人的价值观、行事风格和思维特点。

用户语录：
{json.dumps(statements, ensure_ascii=False)}

请输出 JSON：
{{
  "values": ["价值观1", "价值观2", ...],
  "communication_style": "简要描述沟通风格",
  "thinking_style": "简要描述思维方式",
  "decision_style": "简要描述决策风格",
  "key_traits": ["特质1", "特质2", ...]
}}

价值观用短句，不超过10条。只输出 JSON。"""

    result = call_llm(prompt, api, max_tokens=1500)
    if not result:
        return {"extracted": 0, "error": "LLM 调用失败"}

    extracted = extract_json(result)
    if not extracted or not isinstance(extracted, dict):
        return {"extracted": 0}

    if dry_run:
        print(f"  [DRY RUN] 价值观提取:")
        for v in extracted.get("values", []):
            print(f"    - {v}")
        print(f"  沟通风格: {extracted.get('communication_style', '?')}")
        print(f"  思维方式: {extracted.get('thinking_style', '?')}")
        return {"extracted": len(extracted.get("values", []))}

    # Write into profile
    prefs = profile.setdefault("preferences", {})
    prefs["values"] = extracted.get("values", [])
    prefs["communication_style"] = extracted.get("communication_style")
    profile["thinking_style"] = extracted.get("thinking_style")
    profile["decision_style"] = extracted.get("decision_style")
    profile["key_traits"] = extracted.get("key_traits", [])

    atomic_write_json(PROFILE_FILE, profile)
    append_jsonl(REFINE_LOG, {
        "action": "values_extracted",
        "values_count": len(extracted.get("values", [])),
        "timestamp": datetime.now(TZ).isoformat(),
    })

    return {"extracted": len(extracted.get("values", []))}


# ── 4. 意图清理 ──────────────────────────────────────────

def refine_intent_cleanup(api: dict, dry_run: bool = False) -> dict:
    """Use LLM to check which active intents are stale/completed."""
    intents = load_json(INTENTS_FILE, {})
    active = intents.get("active", [])

    if not active:
        return {"cleaned": 0}

    # Only check old intents (created > 14 days ago)
    now = datetime.now(TZ)
    cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%d")

    old_intents = [i for i in active if i.get("created_at", "9999") < cutoff]
    if not old_intents:
        print("  没有超过14天的旧意图")
        return {"cleaned": 0}

    # Batch check
    items = []
    for i, intent in enumerate(old_intents[:30]):
        items.append(f"{i+1}. [{intent['type']}] s={intent.get('seriousness',0)} | {intent['text'][:80]} (创建于 {intent['created_at']})")

    prompt = f"""以下是从用户录音中提取的意图/待办，已超过14天。
请判断每条是否可能已完成或已过期（不再相关）。

意图列表：
{chr(10).join(items)}

对每条输出判断：
[{{"index": 1, "status": "active|completed|expired", "reason": "简要理由"}}]

判断标准：
- 日常口语动作（吃饭、拿快递等）→ expired
- 具体技术任务但时间久了 → 可能 completed 或 expired
- 长期计划/想法 → 保持 active

只输出 JSON。"""

    result = call_llm(prompt, api, max_tokens=2000)
    if not result:
        return {"cleaned": 0, "error": "LLM 调用失败"}

    judgments = extract_json(result)
    if not judgments or not isinstance(judgments, list):
        return {"cleaned": 0}

    if dry_run:
        completed = [j for j in judgments if j.get("status") == "completed"]
        expired = [j for j in judgments if j.get("status") == "expired"]
        print(f"  [DRY RUN] 建议完成: {len(completed)}, 过期: {len(expired)}")
        for j in judgments:
            if j.get("status") != "active":
                idx = j.get("index", 0) - 1
                if 0 <= idx < len(old_intents):
                    print(f"    [{j['status']}] {old_intents[idx]['text'][:50]} | {j.get('reason','')}")
        return {"cleaned": 0, "suggestions": len(completed) + len(expired)}

    cleaned = 0
    for j in judgments:
        idx = j.get("index", 0) - 1
        if 0 <= idx < len(old_intents):
            new_status = j.get("status", "active")
            if new_status in ("completed", "expired"):
                intent = old_intents[idx]
                intent["status"] = new_status
                intent["cleanup_reason"] = j.get("reason", "")
                intent["cleaned_at"] = now.isoformat()

                # Move to appropriate bucket
                active.remove(intent)
                intents.setdefault(new_status, []).append(intent)
                cleaned += 1

    if cleaned > 0:
        intents["active"] = active
        atomic_write_json(INTENTS_FILE, intents)
        append_jsonl(REFINE_LOG, {
            "action": "intent_cleanup",
            "cleaned": cleaned,
            "timestamp": now.isoformat(),
        })

    return {"cleaned": cleaned}


# ── 主流程 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PI LLM 精炼层")
    parser.add_argument("--entity-merge", action="store_true")
    parser.add_argument("--relationship", action="store_true")
    parser.add_argument("--values", action="store_true")
    parser.add_argument("--intent-cleanup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="pa/claude-haiku-4-5-20251001", help="LLM model")
    args = parser.parse_args()

    run_all = not any([args.entity_merge, args.relationship, args.values, args.intent_cleanup])

    api = load_api_config(args.model)
    if not api:
        print("❌ 无法加载 API 配置")
        sys.exit(1)

    print(f"🧠 LLM 精炼层 (model: {args.model}, dry_run: {args.dry_run})")

    results = {}

    if run_all or args.entity_merge:
        print("\n── 人物合并 ──")
        results["entity_merge"] = refine_entity_merge(api, args.dry_run)
        print(f"  → {results['entity_merge']}")

    if run_all or args.relationship:
        print("\n── 关系精判 ──")
        results["relationship"] = refine_relationships(api, args.dry_run)
        print(f"  → {results['relationship']}")

    if run_all or args.values:
        print("\n── 价值观提取 ──")
        results["values"] = refine_values(api, args.dry_run)
        print(f"  → {results['values']}")

    if run_all or args.intent_cleanup:
        print("\n── 意图清理 ──")
        results["intent_cleanup"] = refine_intent_cleanup(api, args.dry_run)
        print(f"  → {results['intent_cleanup']}")

    print(f"\n✅ 精炼完成")
    return results


if __name__ == "__main__":
    main()

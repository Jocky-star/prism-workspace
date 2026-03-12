#!/usr/bin/env python3
"""
内容选题管理工具 - 为饭团（小红书AI科技博主）设计
用法：python3 content_ideas.py [list|add|done|priority]
"""

import json
import os
from datetime import datetime

IDEAS_FILE = os.path.expanduser("~/.openclaw/workspace/content-ideas.json")

def load_ideas():
    if os.path.exists(IDEAS_FILE):
        with open(IDEAS_FILE) as f:
            return json.load(f)
    return []

def save_ideas(ideas):
    with open(IDEAS_FILE, "w") as f:
        json.dump(ideas, f, ensure_ascii=False, indent=2)

def add_idea(title, category, urgency, notes=""):
    ideas = load_ideas()
    idea = {
        "id": len(ideas) + 1,
        "title": title,
        "category": category,
        "urgency": urgency,  # hot/warm/evergreen
        "notes": notes,
        "created": datetime.now().strftime("%Y-%m-%d"),
        "status": "idea"  # idea/draft/posted
    }
    ideas.append(idea)
    save_ideas(ideas)
    print(f"✅ 已添加：{title}")

def list_ideas(status=None, urgency=None):
    ideas = load_ideas()
    filtered = [i for i in ideas 
                if (status is None or i["status"] == status)
                and (urgency is None or i["urgency"] == urgency)]
    
    # 排序：hot优先，然后按id
    order = {"hot": 0, "warm": 1, "evergreen": 2}
    filtered.sort(key=lambda x: (order.get(x["urgency"], 3), x["id"]))
    
    print(f"\n{'='*60}")
    print(f"📝 内容选题库（{len(filtered)}条）")
    print(f"{'='*60}")
    for i in filtered:
        emoji = {"hot": "🔥", "warm": "⚡", "evergreen": "🌿"}.get(i["urgency"], "📌")
        status_emoji = {"idea": "💡", "draft": "✏️", "posted": "✅"}.get(i["status"], "❓")
        print(f"\n#{i['id']} {emoji}{status_emoji} [{i['category']}] {i['title']}")
        if i["notes"]:
            print(f"   💬 {i['notes']}")
        print(f"   📅 {i['created']}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "list":
            urgency = sys.argv[2] if len(sys.argv) > 2 else None
            list_ideas(urgency=urgency)
        elif sys.argv[1] == "hot":
            list_ideas(urgency="hot")
    else:
        list_ideas()

#!/usr/bin/env python3
"""
内容选题快速格式化工具
将选题库里的想法转化为小红书文案框架
"""

import json
from datetime import datetime

# 小红书文案模板
TEMPLATES = {
    "新品科普": {
        "title_formats": [
            "！！{产品}来了，{核心价值}（附教程）",
            "真的震了：{产品}可以{功能}！",
            "终于！{公司}上线{产品}，{差异化}"
        ],
        "sections": ["一句话总结", "具体是什么", "和之前有什么不同", "普通人怎么用", "注意事项"]
    },
    "横向对比": {
        "title_formats": [
            "{A} vs {B}：用了一周，我的判断",
            "同样{场景}，{A}和{B}差距有多大？",
            "花{金额}还是花{金额}？两款AI工具实测"
        ],
        "sections": ["对比维度", "数据表格", "各自适合谁", "我的推荐", "总结一句话"]
    },
    "情感共鸣": {
        "title_formats": [
            "AI让我{失去/得到}了什么...",
            "一个让我想了三天的故事：{事件}",
            "这件事让{N}万人沉默了"
        ],
        "sections": ["故事钩子", "冲突核心", "不同声音", "我的思考", "你怎么看（引导评论）"]
    },
    "实操教程": {
        "title_formats": [
            "手把手：{N}分钟搭建{成果}（零基础可上手）",
            "收藏！{工具}保姆级教程",
            "真的超简单！{N}步完成{目标}"
        ],
        "sections": ["准备工作", "步骤1", "步骤2", "步骤3", "常见问题", "效果展示"]
    },
    "行业速报": {
        "title_formats": [
            "刚刚！{事件}，影响是...",
            "{公司}悄悄{动作}，背后逻辑是什么？",
            "这条新闻很重要，但没人报道：{事件}"
        ],
        "sections": ["发生了什么", "关键数据", "为什么重要", "对你的影响", "下一步观察"]
    }
}

# 今日可用选题（基于学习成果）
TODAY_IDEAS = [
    {
        "title": "Claude Cowork新品科普",
        "type": "新品科普",
        "data": {
            "产品": "Claude Cowork",
            "核心价值": "你说任务，AI帮你执行",
            "公司": "Anthropic",
            "差异化": "不只聊天，会真的做事！"
        },
        "key_points": [
            "Research Preview状态（抢先报道！）",
            "告诉AI整理文件夹/做报告，走开，回来看结果",
            "支持定时任务（每日/周/月循环）",
            "连接Slack、Notion、Figma等工具",
            "本质：知识工作者版的Claude Code"
        ]
    },
    {
        "title": "gpt-oss开源大爆炸",
        "type": "行业速报",
        "data": {
            "事件": "OpenAI开源了GPT模型！Apache 2.0",
            "公司": "OpenAI",
            "动作": "发布gpt-oss-20b/120b"
        },
        "key_points": [
            "OpenAI自2019年GPT-2后首次开源",
            "Apache 2.0：完全自由，可商用",
            "gpt-oss-20b接近o3-mini性能！",
            "16GB内存就能在本地跑",
            "ollama run gpt-oss:20b"
        ]
    },
    {
        "title": "Gemini Flash-Lite vs Claude Haiku横评",
        "type": "横向对比",
        "data": {
            "A": "Gemini 3.1 Flash-Lite",
            "B": "Claude 4.5 Haiku",
            "场景": "低成本AI API选型",
            "金额": "$0.25/M",
            "金额2": "$1.00/M"
        },
        "key_points": [
            "价格：Flash-Lite $0.25 vs Haiku $1.00（贵4倍）",
            "速度：Flash-Lite 363 t/s vs Haiku 108 t/s（快3倍）",
            "GPQA Diamond: 86.9% vs 73.0%（Flash更强！）",
            "Claude Haiku几乎在这档被完全碾压",
            "唯一优势：Claude生态集成"
        ]
    }
]

def format_idea(idea):
    """格式化选题为小红书框架"""
    template = TEMPLATES[idea["type"]]
    
    print(f"\n{'='*60}")
    print(f"📝 选题: {idea['title']}")
    print(f"类型: {idea['type']}")
    print(f"{'='*60}")
    
    print("\n🎯 标题选项:")
    for i, fmt in enumerate(template["title_formats"], 1):
        try:
            title = fmt.format(**idea["data"])
        except:
            title = fmt
        print(f"  {i}. {title}")
    
    print("\n📋 内容框架:")
    for section in template["sections"]:
        print(f"  【{section}】")
    
    print("\n💡 关键数据/金句:")
    for point in idea["key_points"]:
        print(f"  • {point}")
    
    print("\n#️⃣ 建议标签:")
    tags = generate_tags(idea["type"], idea["title"])
    print(f"  {' '.join(tags)}")

def generate_tags(content_type, title):
    base_tags = ["#AI工具", "#科技博主", "#人工智能"]
    type_tags = {
        "新品科普": ["#新品测评", "#AI新功能"],
        "横向对比": ["#AI对比", "#工具选型"],
        "情感共鸣": ["#AI思考", "#程序员日记"],
        "实操教程": ["#AI教程", "#保姆级教程"],
        "行业速报": ["#AI资讯", "#科技速报"]
    }
    return base_tags + type_tags.get(content_type, [])

# 主程序
print(f"内容框架生成器 — {datetime.now().strftime('%Y-%m-%d')}")
print(f"今日可用选题: {len(TODAY_IDEAS)} 个")

for idea in TODAY_IDEAS:
    format_idea(idea)

print(f"\n{'='*60}")
print("📊 优先级建议:")
print("  1️⃣  Claude Cowork (率先报道，Research Preview)")
print("  2️⃣  gpt-oss开源 (历史意义重大)")  
print("  3️⃣  Gemini vs Haiku (实用对比，长尾流量)")

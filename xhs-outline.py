#!/usr/bin/env python3
"""
小红书内容大纲生成器
把选题库中的一条idea生成可用的内容大纲
用法：python3 xhs-outline.py [idea_id]
"""

import json
import os
import sys

IDEAS_FILE = os.path.expanduser("~/.openclaw/workspace/content-ideas.json")

TEMPLATES = {
    "AI震撼时刻": {
        "hook": "当我看到这个新闻，我说不出话来",
        "structure": ["开头：一句话抓眼球（数据/反差/疑问）", "背景：这是什么，发生了什么", "细节：最有意思的3-5个点", "思考：这意味着什么（你的独特视角）", "结尾：一个引发评论的开放性问题"]
    },
    "AI产品更新": {
        "hook": "它刚刚更新了，你可能还不知道",
        "structure": ["开头：新功能一句话描述", "演示：截图/GIF实际效果", "对比：和之前有什么不同", "实用场景：你能怎么用", "结尾：你觉得有用吗？"]
    },
    "AI模型评测": {
        "hook": "真实测评，不吹不黑",
        "structure": ["开头：测什么，为什么测", "数据：关键数字对比（表格/图）", "实测：我自己试了什么", "结论：什么情况用哪个", "结尾：还想看什么对比？"]
    },
    "AI事故复盘": {
        "hook": "这次AI真的出事了",
        "structure": ["开头：事故摘要（时间/影响范围）", "经过：发生了什么", "原因：为什么会发生", "后续：怎么处理的", "反思：对我们意味着什么"]
    },
    "AI工作流教程": {
        "hook": "这个工作流让我省了X小时",
        "structure": ["开头：能解决什么问题", "材料清单：需要什么工具", "步骤1-5：具体操作（截图）", "效果对比：之前VS之后", "注意事项：踩过的坑"]
    },
    "AI深度科普": {
        "hook": "大多数人都不知道的AI真相",
        "structure": ["开头：一个反直觉的结论", "研究背景：谁做的/怎么做的", "关键发现：最重要的3个数据", "为什么重要：对普通人的意义", "结尾：你相信吗？"]
    },
    "AI伦理/权益": {
        "hook": "你的XX正在被AI…",
        "structure": ["开头：让用户感到与自己相关", "事件：发生了什么", "问题在哪：核心争议", "目前状态：公司怎么说", "你能做什么：实际建议"]
    },
    "AI人物": {
        "hook": "这个人改变了整个AI行业",
        "structure": ["开头：一句话介绍此人为何重要", "背景：他/她做了什么", "最近动态：发生了什么变化", "业界影响：为什么别人都在看", "你怎么看"]
    },
    "AI行业动态": {
        "hook": "AI圈今天最大的瓜",
        "structure": ["一句话版本：精华摘要", "详细版本：背景+过程+结果", "各方立场：几个不同视角", "可能走向：未来会怎样", "讨论点：留给评论区"]
    },
    "AI编程工具": {
        "hook": "程序员的工作方式正在被颠覆",
        "structure": ["开头：一个具体的变化", "数据支撑：实际使用数字", "工具对比：主流选择", "怎么入门：给想尝试的人", "结尾：程序员们怎么看？"]
    },
    "AI对比评测": {
        "hook": "同一个问题我分别问了它们",
        "structure": ["测试设置：评测什么，怎么评", "结果展示：截图对比", "详细分析：每个维度打分", "我的选择：我用哪个/为什么", "结尾：你的首选是？"]
    },
    "AI社会影响": {
        "hook": "AI改变的比你想象的更快",
        "structure": ["数据切入：一个让人停下来的数字", "研究说明：怎么得出的", "影响分析：谁受影响/怎么受影响", "争议：不同的观点", "个人思考：你的看法"]
    },
    "AI使用技巧": {
        "hook": "99%的人都用错了AI",
        "structure": ["开头：常见错误描述", "正确打开方式：具体操作", "对比演示：错误 vs 正确", "进阶技巧：2-3个延伸", "结尾：你通常怎么用？"]
    },
    "开源AI生态": {
        "hook": "免费的AI变得更强了",
        "structure": ["什么发生了：一句话", "之前状态 vs 现在：对比", "对用户意味着什么", "怎么用到自己项目", "开源的意义（简短讨论）"]
    },
    "机器人/具身AI": {
        "hook": "AI开始有身体了",
        "structure": ["开头：演示片段/图片", "技术背后：怎么实现的", "现在能做什么", "距离商用还差什么", "你会想要吗？"]
    },
    "开发者工具": {
        "hook": "写代码的效率可以再翻倍",
        "structure": ["工具介绍：是什么/解决什么", "实测演示：截图或代码", "对比传统方式", "适合人群：谁应该用", "获取方式+链接"]
    },
    "AI图像工具": {
        "hook": "图片可以这么编辑？",
        "structure": ["开头：成品展示（最吸引眼球的图）", "原图 → 改后对比", "步骤：如何操作", "局限性：做不到什么", "结尾：想看更多什么效果？"]
    },
    "AI视频生成": {
        "hook": "AI拍视频已经比人更准了",
        "structure": ["数据/案例：最震撼的结果", "技术对比：几个主流工具", "实测片段（嵌入视频）", "目前最好用的选择", "创作者应该怎么用？"]
    },
    "硬件评测": {
        "hook": "花这么少能做这么多？",
        "structure": ["开头：核心数字（价格/性能）", "实测项目：做了什么测试", "数据图表", "适合人群 & 不适合人群", "综合评价 & 购买建议"]
    },
}

def get_template(category):
    return TEMPLATES.get(category, {
        "hook": "这件事比你想的更重要",
        "structure": ["开头：最吸引人的角度", "背景", "核心内容（3个要点）", "为什么值得关注", "互动引导"]
    })

def format_idea(idea):
    tmpl = get_template(idea.get("category", ""))
    
    urgency_label = {"hot": "🔥 热点（快发！）", "warm": "⚡ 温热", "evergreen": "🌿 长青"}.get(idea.get("urgency"), "")
    
    print(f"\n{'='*65}")
    print(f"# 📝 内容大纲 #{idea['id']}")
    print(f"{'='*65}")
    print(f"\n**话题**：{idea['title']}")
    print(f"**类型**：{idea.get('category', '通用')} | **时效**：{urgency_label}")
    print(f"\n---")
    print(f"\n## 📌 核心素材")
    print(f"{idea.get('notes', '（无备注）')}")
    print(f"\n## 🎣 钩子参考")
    print(f"{tmpl['hook']}")
    print(f"\n## 📋 内容结构")
    for i, step in enumerate(tmpl["structure"], 1):
        print(f"{i}. {step}")
    print(f"\n## 💡 小红书要点")
    print("- 标题：加数字/「」/反问")
    print("- 封面：文字简洁 + 高对比度")
    print("- 前3行：直接给干货，不铺垫")
    print("- 话题标签：#AI工具 #人工智能 #科技" + (f" #{idea.get('category','')}" if idea.get('category') else ""))
    print(f"\n{'='*65}\n")

def main():
    with open(IDEAS_FILE) as f:
        ideas = json.load(f)
    
    if len(sys.argv) > 1:
        try:
            target_id = int(sys.argv[1])
            idea = next((i for i in ideas if i["id"] == target_id), None)
            if idea:
                format_idea(idea)
            else:
                print(f"未找到ID {target_id}")
        except ValueError:
            print("用法：python3 xhs-outline.py [id]")
    else:
        # 显示所有热点选题
        hot_ideas = [i for i in ideas if i.get("urgency") == "hot"]
        print(f"\n🔥 热点选题（{len(hot_ideas)}条）：")
        for i in hot_ideas:
            print(f"  #{i['id']}: {i['title']}")
        print("\n运行 python3 xhs-outline.py [id] 生成大纲")

if __name__ == "__main__":
    main()

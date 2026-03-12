# 个人智能理解系统（Personal Intelligence System）

> **一句话**：从每日录音数据中自动构建用户的完整认知模型——人物关系、行为习惯、决策模式、意图追踪——并驱动有价值的主动行动。

> **设计原则**：零先验、纯数据驱动、不硬编码任何用户信息、可打包迁移。

---

## 目录

1. [系统概述](#1-系统概述)
2. [架构总览](#2-架构总览)
3. [分层设计](#3-分层设计)
4. [数据模型](#4-数据模型)
5. [处理流水线](#5-处理流水线)
6. [冷启动策略](#6-冷启动策略)
7. [成本控制](#7-成本控制)
8. [迁移方案](#8-迁移方案)
9. [实施路线图](#9-实施路线图)
10. [与现有系统的集成点](#10-与现有系统的集成点)

---

## 1. 系统概述

### 现状问题

当前 `audio-daily-insight` 做了浅层提取（活动时间线、金句、待办），`habit-predictor` 做了统计级行为预测。两者的问题：

| 系统 | 做到了什么 | 浪费了什么 |
|------|-----------|-----------|
| audio-daily-insight | 单日摘要、漏餐提醒、待办提取 | 跨天关联、人物关系、决策追踪、意图生命周期 |
| habit-predictor | 活跃时段、话题偏好、打扰容忍度 | 只看 chat 事件，不看录音内容 |
| data-loop-design | 规划了闭环，但子系统还没落地 | 想法捕捉、建议追踪、反馈回路都在纸上 |

**核心矛盾**：38 天产生了 1098 个场景、2790 个 SVO 事件、30869 条转录，但系统只用到了 activity label 和 key_quotes，相当于只读了书的目录。

### 系统定位

这个系统不是"又一个数据分析工具"，而是 AI 助理的**认知基础设施**。它让助理从"被动响应用户消息"进化为"理解用户，在恰当时机做恰当的事"。

### 与 data-loop-design 的关系

`data-loop-design.md` 是当时对闭环的初步规划，侧重流程编排（cron 触发 → 生成 → 发送）。本文档是它的升级版：

- 补充了 **知识结构**（不只是流程，还有存什么、怎么组织）
- 补充了 **通用化设计**（从"饭团专用"变成"任何人可用"）
- 补充了 **推理能力**（不只是统计，还有 LLM 驱动的深度理解）
- 吸收了 data-loop-design 的子系统规划，作为实施路线图的一部分

---

## 2. 架构总览

### 数据流全景

```
                          ┌──────────────────────────────┐
                          │  外部数据源                     │
                          │  手表录音 → Gemini 转写          │
                          │  → mf_scene_v2.3 JSON          │
                          └──────────────┬─────────────────┘
                                         │
                                    ① 每日拉取
                                         │
  ┌──────────────────────────────────────▼──────────────────────────────────┐
  │                        感知层 (Perception)                               │
  │                                                                         │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
  │  │ 实体提取器     │  │ 事件提取器     │  │ 意图提取器     │  │ 情境提取器   │  │
  │  │ (纯规则)      │  │ (纯规则)      │  │ (规则+LLM)   │  │ (纯规则)    │  │
  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
  │         ▼                 ▼                 ▼                ▼          │
  │   entities.db        events.db         intents.db      contexts.db     │
  │   (人/地/物/话题)     (SVO事件流)      (想法/计划/待办)  (活动/位置/情绪)  │
  └──────────────────────────────┬──────────────────────────────────────────┘
                                 │
                            ② 每日/增量
                                 │
  ┌──────────────────────────────▼──────────────────────────────────────────┐
  │                        理解层 (Understanding)                            │
  │                                                                         │
  │  ┌───────────────────┐  ┌───────────────────┐  ┌─────────────────────┐ │
  │  │ 用户画像引擎        │  │ 关系图谱引擎        │  │ 模式识别引擎         │ │
  │  │ (统计+周期LLM)     │  │ (统计+周期LLM)     │  │ (统计+周期LLM)      │ │
  │  └────────┬──────────┘  └────────┬──────────┘  └────────┬────────────┘ │
  │           ▼                      ▼                      ▼              │
  │    profile.json          relationships.json       patterns.json        │
  │    (身份/习惯/偏好/价值观) (人物关系+交互历史)       (行为/决策/时间模式)   │
  └──────────────────────────────┬──────────────────────────────────────────┘
                                 │
                            ③ 每周/按需
                                 │
  ┌──────────────────────────────▼──────────────────────────────────────────┐
  │                        推理层 (Reasoning)                                │
  │                                                                         │
  │  ┌───────────────────┐  ┌───────────────────┐  ┌─────────────────────┐ │
  │  │ 洞察生成器          │  │ 预测引擎           │  │ 建议生成器           │ │
  │  │ (LLM, 按需)        │  │ (统计, 实时)       │  │ (LLM, 每周)        │ │
  │  └────────┬──────────┘  └────────┬──────────┘  └────────┬────────────┘ │
  │           ▼                      ▼                      ▼              │
  │    insights.jsonl          predictions.json       suggestions.json     │
  └──────────────────────────────┬──────────────────────────────────────────┘
                                 │
                            ④ 事件驱动
                                 │
  ┌──────────────────────────────▼──────────────────────────────────────────┐
  │                        行动层 (Action)                                   │
  │                                                                         │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
  │  │ 飞书通知       │  │ Prism 屏显    │  │ 米家设备       │  │ 日历/提醒   │ │
  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘ │
  │                                                                         │
  │  反馈回路：用户响应 → feedback.jsonl → 调整推理参数                          │
  └─────────────────────────────────────────────────────────────────────────┘
```

### 设计决策：为什么是 4 层？

1. **感知层和理解层分离**：感知层做"看到什么"（纯提取，不判断），理解层做"意味着什么"（需要上下文和历史）。分开的好处是感知层可以纯规则、零成本，理解层才需要 LLM。
2. **理解层和推理层分离**：理解层是"知识库"（相对静态，每天/每周更新），推理层是"当下判断"（动态的，实时查询）。分开让推理层永远可以用最新的知识库做决策，不需要每次重新"理解"。
3. **行动层独立**：行动是有副作用的（发消息、控设备），必须跟纯计算隔离，方便加权限控制和审计。


---

## 3. 分层设计

### 3.1 感知层（Perception Layer）

**职责**：从 mf_scene_v2.3 JSON 中提取所有结构化信号，写入标准化存储。不做任何"理解"，只做"提取"。

**为什么要单独一层**：JSON 里的信息分散在 entity_canon、scenes、macro_frames、svo_bullets、key_quotes、transcript 多个字段里。感知层把它们拆解成 4 个独立维度，后续理解层可以按需查询，不用每次重新解析原始 JSON。

**核心原则**：全部用纯规则实现（除意图提取器的分类步骤），零 LLM 成本。

#### 3.1.1 实体提取器（Entity Extractor）

**输入**：`entity_canon` 全部四类 + `scenes[].participants`

**处理逻辑**（纯规则）：
```python
# 伪代码
for person in entity_canon.people:
    upsert_entity(
        type="person",
        name=person.canonical,
        aliases=person.aliases,
        voice_profile=person.voice_profile,
        first_seen=today if new else existing,
    )
    
    # 从 scenes 中统计今天和这个人的交互
    co_scenes = [s for s in scenes if person.id in s.participants]
    update_interaction(
        person=person.canonical,
        date=today,
        scene_count=len(co_scenes),
        total_minutes=sum(duration(s) for s in co_scenes),
        topics=[extract_topic(s) for s in co_scenes],
    )
```

**关键设计：跨天实体去重**

每天 JSON 里 entity_canon 的 ID 是日内的（p1, p2, ...），跨天不一致。需要全局实体注册表：

```
匹配策略（优先级从高到低）：
1. canonical name 完全匹配 → 同一实体
2. canonical name 相似（编辑距离 ≤ 2）+ aliases 有交集 → 同一实体
3. voice_profile 高度相似（如有）→ 候选合并
4. 无匹配 → 新实体
```

为什么不用 LLM 做去重？40 个人物 × 38 天 = 每天最多几十次比较，规则就够了。LLM 做这种表格匹配既慢又贵。

**注意**：voice_profile 不是每天都有，不能作为主要匹配依据，只作辅助。

#### 3.1.2 事件提取器（Event Extractor）

**输入**：`scenes[].svo_bullets` + `scenes[].activity` + `macro_frames`

**处理逻辑**（纯规则）：

SVO bullets 是 Gemini 已经提取好的"主-谓-宾"事件（如"用户-讨论了-技术方案"），质量不错，直接入库：

```python
for scene in scenes:
    for svo in scene.svo_bullets:
        if svo.confidence >= 0.75:
            insert_event(
                date=today, scene_id=scene.id, time=scene.start_time,
                svo_text=svo.text, svo_type=svo.type,
                participants=scene.participants,
                location=scene.location,
                activity=scene.activity.label
            )
```

为什么 confidence 阈值设 0.75 而不是 0.9？SVO 本身是 Gemini 提取的结构化结果，0.75 已经是"大概率对"。设太高会漏掉有价值事件，而误报在理解层会被过滤。

#### 3.1.3 意图提取器（Intent Extractor）

**输入**：`scenes[].todos` + `scenes[].key_quotes`（speaker=p1）+ `scenes[].transcript`（maps_to=p1）

**处理逻辑**（规则 + 轻量 LLM）：

```
第一步（规则，零成本）：
  - 从 todos 字段直接提取（约 40% 的天有此字段）
  - 从 key_quotes + transcript 中匹配意图关键词：
    "我想/我要/打算/准备/应该/得去/需要/计划"
    "试试/搞个/做个/弄个/买个"
    "如果能.../要是有.../能不能..."
  - 过滤：排除疑问句、过去时、ASR 幻觉
  - 去重：同一天相同文本只保留首次出现

第二步（LLM 分类，仅对第一步结果）：
  - 输入：候选意图列表（通常 3-15 条/天）
  - 任务：
    a) 分类：todo（待办）/ idea（想法）/ plan（计划）/ wish（愿望）
    b) 评估认真程度（1-5分）
    c) 提取截止时间（如有）
  - 用 Haiku，3-15 条意图约 500-1500 tokens input，成本 < $0.001/天
```

为什么意图提取需要 LLM？因为"我要起飞了"和"我要去吃饭"的意图类型完全不同，纯规则无法区分比喻和字面意思。但 LLM 只用在分类步骤，提取步骤还是规则。

#### 3.1.4 情境提取器（Context Extractor）

**输入**：`scenes[]` 全部字段 + `macro_frames`

**处理逻辑**（纯规则）：

```python
for scene in scenes:
    insert_context(
        date=today, scene_id=scene.id,
        time_range=(scene.start_time, scene.end_time),
        activity=scene.activity.label,
        activity_confidence=scene.activity.p,
        location=scene.location,
        participants_count=len(scene.participants),
        # 以下字段可选（约 40% 的天有）
        acoustic=scene.get("acoustic_details"),
        context_tags=scene.get("context_tags", []),
        environment=scene.get("environment_index"),
    )

# 从 macro_frames 提取日叙事结构
for frame in macro_frames:
    insert_narrative(
        date=today, frame_id=frame.id,
        title=frame.title,
        time_range=frame.time_range,
        activity=frame.primary_activity,
        mood=frame.mood_or_tone,
        topics=frame.key_topics,
        outcomes=frame.outcomes,
    )
```

情境数据是后续"什么时候适合打扰"判断的基础——知道用户在什么时间段做什么、和谁在一起、心情如何。

### 3.2 理解层（Understanding Layer）

**职责**：把感知层的碎片信号组织成对用户的**持久化理解**。知识库模式：更新频率低（每天/每周），查询频率高（每次推理都用）。

**核心原则**：统计先行，LLM 做深度分析。日常更新用纯统计（零成本），周期性用 LLM 做知识精炼。

#### 3.2.1 用户画像引擎（Profile Engine）

**目标**：自动生成"这个人是谁"——身份、作息、偏好、价值观。

**不硬编码任何信息**。新用户接入时 profile.json 是空的，完全从数据中自举。

**每日更新（纯统计）**：
```python
# 从 contexts.db 聚合
profile["schedule"] = {
    "wake_up": earliest_scene_time_median(7d),
    "sleep": latest_scene_time_median(7d),
    "commute_start": median_time_of(activity="commute", position="first"),
    "commute_end": median_time_of(activity="commute", position="last"),
    "work_hours": avg_duration_of(activity="work", 7d),
}

# 从 events.db 聚合
profile["top_topics"] = top_n_topics(events, n=10, window=14d)
profile["activity_distribution"] = activity_hours_by_type(contexts, 7d)

# 从 intents.db 聚合
profile["active_projects"] = topics_with_recent_intents(14d)
```

**每周 LLM 精炼**：
```
输入：过去 7 天的 daily digest 摘要（约 2000-4000 tokens）+ 当前 profile
Prompt：
  "根据这周的数据，更新用户画像。回答以下问题：
   1. 这个人的职业/工作内容是什么？（从工作场景推断）
   2. 生活节奏有什么特点？（作息、通勤、运动）
   3. 最近在关注什么？（高频话题）
   4. 有什么明显的偏好或价值观？（从金句和决策推断）
   5. 上周的画像有什么需要修正的？
   输出 JSON 格式。"
模型：Haiku（周级任务，不需要 Sonnet 级推理）
成本：约 $0.003/周
```

#### 3.2.2 关系图谱引擎（Relationship Engine）

**目标**：自动识别社交网络——谁是同事、家人、朋友——并追踪关系变化。

**每日更新（纯统计）**：

```python
for person in entities.all_people():
    interactions = get_interactions(person, date=today)
    if not interactions:
        continue
    
    rel = get_or_create_relationship(person)
    rel.interaction_count += interactions.scene_count
    rel.total_minutes += interactions.total_minutes
    rel.last_seen = today
    rel.recent_topics.extend(interactions.topics)
    
    # 关系类型推断（纯规则）
    if not rel.type:  # 还没确定关系类型
        clues = collect_clues(person, all_interactions)
        rel.type_candidates = infer_relationship_type(clues)
        # 规则：
        # - 只在 work 场景出现 → 同事概率高
        # - 在 meal/social 场景 + 非工作时间 → 朋友/家人
        # - 每天都在 home 场景 → 同住人/家人
        # - 称呼包含"姐/哥/爸/妈" → 家人
```

**每两周 LLM 精炼**：

```
输入：所有关系的交互摘要（人物名、出现频率、场景类型、话题分布）
Prompt：
  "根据交互数据，判断每个人和用户的关系类型。
   输出格式：[{name, type, confidence, evidence}]
   type 取值：colleague/friend/family/acquaintance/service_provider
   只输出有足够证据的，不确定的标记 unknown。"
成本：约 $0.005/两周
```

**关键设计：关系变化追踪**

```python
# 每月对比，检测关系变化
for person in relationships:
    freq_this_month = interaction_count(person, last_30d)
    freq_last_month = interaction_count(person, 30d_before)
    
    if freq_this_month < freq_last_month * 0.3:
        flag_change(person, "interaction_decline", 
                    detail=f"从{freq_last_month}次降到{freq_this_month}次")
    
    topics_shift = topic_overlap(person, this_month, last_month)
    if topics_shift < 0.3:  # 话题几乎没交集了
        flag_change(person, "topic_shift")
```

#### 3.2.3 模式识别引擎（Pattern Engine）

**目标**：识别行为模式、决策模式、时间模式。

**行为模式（每日统计）**：
```python
# 从 contexts.db 提取
patterns["daily_routine"] = {
    "weekday": aggregate_routine(contexts, weekday=True),
    "weekend": aggregate_routine(contexts, weekday=False),
}

# 异常检测
today_work_hours = sum_hours(activity="work", date=today)
avg_work_hours = avg_hours(activity="work", window=14d)
if today_work_hours > avg_work_hours * 1.5:
    flag_anomaly("overtime_spike", today_work_hours, avg_work_hours)
```

**决策模式（每周 LLM）**：
```
输入：本周所有含"决策"类 SVO 事件 + 对应的 transcript 上下文
Prompt：
  "分析这些决策场景：
   1. 用户在什么场景下快速决策？（<2分钟讨论就结论）
   2. 什么场景下犹豫？（反复讨论、多次提及同一问题）
   3. 什么决策倾向于独自做？什么倾向于和人商量？
   简要总结，不超过 200 字。"
成本：约 $0.003/周
```

**意图追踪（每日统计）**：
```python
# 意图生命周期管理
for intent in intents.get_active():
    # 检查本周数据中是否有"落地"信号
    related_events = events.search(
        keywords=intent.keywords,
        date_range=(intent.created_at, today)
    )
    
    if has_completion_signal(related_events):
        intent.status = "completed"
        intent.completed_at = today
    elif days_since(intent.created_at) > 14 and intent.seriousness >= 3:
        intent.status = "stale"  # 标记为"搁置"，可能需要提醒
    elif days_since(intent.created_at) > 30:
        intent.status = "expired"
```

### 3.3 推理层（Reasoning Layer）

**职责**：基于理解层的知识库，产生实时的洞察、预测、建议。

**核心原则**：统计预测实时可用（零成本），LLM 洞察按需触发。

#### 3.3.1 洞察生成器（Insight Generator）

**触发条件**：每日处理后 + 每周精炼后

**洞察类型及生成规则**：

| 洞察类型 | 触发条件 | 示例 | LLM？ |
|---------|---------|------|------|
| 关系变化 | 某人交互频率月环比下降 >60% | "最近两周没见到 XX" | 否 |
| 意图搁置 | seriousness≥3 的意图 >14天未推进 | "你两周前说想去看皮肤科" | 否 |
| 异常模式 | 工作时长/运动频率偏离 2σ | "本周加班比平时多 3 小时" | 否 |
| 情绪趋势 | 连续 3 天 mood 偏负面 | "最近几天状态不太对" | 否 |
| 深度洞察 | 每周精炼时发现新模式 | "你在有 XX 参加的会上决策更快" | Haiku |

**关键设计**：洞察有优先级和衰减。同类洞察 7 天内不重复推送。每条洞察写入 `insights.jsonl`，包含 `pushed: bool` 和 `user_response` 字段供反馈回路使用。

#### 3.3.2 预测引擎（Prediction Engine）

复用现有 habit_predictor 的统计框架，但数据源从 chat 事件扩展到全量感知层数据：

```python
def predict_now(profile, patterns, contexts_today):
    """实时预测当前状态，纯统计，零成本"""
    hour = now.hour
    weekday = now.weekday()
    
    # 从 patterns 中取历史同时段分布
    typical = patterns["daily_routine"]["weekday" if weekday < 5 else "weekend"]
    current_bucket = typical.get(hour_bucket(hour), {})
    
    return {
        "likely_activity": current_bucket.get("top_activity"),
        "interruptibility": estimate_interruptibility(profile, contexts_today),
        "energy_level": estimate_energy(hour, patterns["sleep_schedule"]),
        "upcoming": next_transition(typical, hour),
    }
```

#### 3.3.3 建议生成器（Suggestion Generator）

**每周一次，LLM 驱动**：

```
输入：本周 insights + intent 状态列表 + profile 摘要（约 3000 tokens）
Prompt：
  "基于这周的信息，给用户 3-5 条可操作的建议。
   规则：
   - 每条建议必须关联具体数据证据
   - 区分'提醒型'（用户已知但忘了）和'发现型'（用户可能没意识到）
   - 不说空话（'注意休息'无意义，'周三晚上 10 点后别开会了'有意义）
   输出 JSON: [{text, type, evidence, priority}]"
模型：Haiku
成本：~$0.003/周
```

### 3.4 行动层（Action Layer）

**职责**：把推理层的输出变成实际动作。这是唯一有"副作用"的层。

#### 通知策略

```python
CHANNELS = {
    "urgent":  ["feishu"],           # 直接发消息
    "normal":  ["prism"],            # 屏幕闪屏/NOTE 位
    "passive": ["prism_summary"],    # 便签模式里显示
}

def should_notify(insight, prediction):
    """决定是否通知、用什么渠道"""
    # 安静时间不推
    if 23 <= hour or hour < 8:
        return None
    # 用户正在开会不推
    if prediction["likely_activity"] == "meeting":
        return None
    # 高优先级走飞书
    if insight.priority >= 4:
        return "urgent"
    # 中等走 Prism 闪屏
    if insight.priority >= 2:
        return "normal"
    # 低优先级攒到便签
    return "passive"
```

#### 自主执行边界

| 动作 | 自动执行？ | 理由 |
|------|-----------|------|
| Prism 屏幕更新 | ✅ 自动 | 无副作用 |
| 米家台灯开关 | ✅ 自动 | 可逆，已有保护机制 |
| 飞书发提醒消息 | ✅ 自动（频率受限） | 每天最多 3 条主动推送 |
| 代为回复消息 | ❌ 需确认 | 代表用户身份 |
| 外部 API 调用 | ❌ 需确认 | 不可逆 |

#### 反馈回路

```python
# 用户对建议的响应追踪
feedback_signals = {
    "explicit_positive": "用户说'好的/有用/谢谢'",
    "explicit_negative": "用户说'别提了/没用/烦'",
    "action_taken":      "建议后 24h 内相关意图状态变化",
    "ignored":           "48h 无响应",
}

# 反馈写入 feedback.jsonl，每月聚合一次
# 用于调整：洞察优先级权重、通知频率、建议风格
```

---

## 4. 数据模型

所有数据存储在 `memory/intelligence/` 目录下。

### 感知层存储

**entities.json** — 全局实体注册表
```json
{
  "people": {
    "张三": {
      "id": "global_p_001",
      "aliases": ["三哥", "张总"],
      "voice_profile": {"gender": "male", "age_range": "30-40"},
      "first_seen": "2025-11-18",
      "last_seen": "2026-01-29",
      "daily_ids": {"20251118": "p3", "20251229": "p2"}
    }
  },
  "places": { ... },
  "topics": { ... }
}
```

**events.jsonl** — 追加写入的事件流
```json
{"date":"2025-12-29","time":"08:15","svo":"用户-讨论了-技术方案A","type":"decision","participants":["张三"],"activity":"meeting","location":"会议室"}
```

**intents.json** — 意图追踪表
```json
{
  "active": [
    {
      "id": "i_042",
      "text": "想去看皮肤科",
      "type": "todo",
      "seriousness": 4,
      "created_at": "2025-12-29",
      "source_quote": "我得去看看皮肤科",
      "status": "stale",
      "last_checked": "2026-03-12",
      "related_events": []
    }
  ],
  "completed": [...],
  "expired": [...]
}
```

**contexts.jsonl** — 情境时间线
```json
{"date":"2025-12-29","start":"07:49","end":"08:01","activity":"commute","location":"车内","participants":1,"mood":"neutral","tags":["driving","solo"]}
```

### 理解层存储

**profile.json** — 用户画像（自动生成，不手写）
```json
{
  "identity": {
    "inferred_name": null,
    "occupation": "科技公司产品+技术混合角色",
    "confidence": 0.85,
    "evidence": ["高频工作场景含代码审查+产品讨论"]
  },
  "schedule": {
    "wake_up_median": "07:30",
    "sleep_median": "00:30",
    "commute_start": "08:00",
    "work_hours_avg": 9.2
  },
  "preferences": {
    "values": ["务实", "反对形式主义", "重视投资"],
    "dislikes": ["无意义功能堆砌"],
    "communication_style": "直接"
  },
  "health": {
    "exercise_freq_weekly": 2.3,
    "known_issues": ["心率偏低", "牙齿楔状缺损"]
  },
  "updated_at": "2026-03-12",
  "version": 15
}
```

**relationships.json** — 社交图谱
```json
{
  "张三": {
    "type": "colleague",
    "confidence": 0.9,
    "interaction_stats": {
      "total_scenes": 45,
      "total_minutes": 380,
      "last_7d": 3,
      "last_30d": 12
    },
    "top_topics": ["技术方案", "代码审查"],
    "trend": "stable",
    "last_seen": "2026-01-23"
  }
}
```

**patterns.json** — 行为模式库
```json
{
  "daily_routine": {
    "weekday": {
      "07-09": {"top_activity": "commute", "avg_duration_min": 35},
      "09-12": {"top_activity": "work", "avg_duration_min": 165},
      "12-13": {"top_activity": "meal", "avg_duration_min": 45}
    }
  },
  "decision_style": {
    "fast_decision_contexts": ["技术选型", "任务分配"],
    "slow_decision_contexts": ["人事决策", "预算"]
  },
  "anomalies_this_week": []
}
```

### 推理层存储

**insights.jsonl** — 洞察日志
```json
{"id":"ins_078","date":"2026-03-12","type":"intent_stale","text":"你两周前提到想去看皮肤科，要不要帮你查下海淀医院的号？","priority":3,"pushed":false,"user_response":null}
```

**suggestions.json** — 本周建议列表
```json
[
  {
    "text": "周三晚上连续三周加班到 22 点，考虑把周四早会挪到 10 点？",
    "type": "discovery",
    "evidence": "contexts.jsonl 统计",
    "priority": 2,
    "status": "pending"
  }
]
```

**feedback.jsonl** — 反馈记录
```json
{"date":"2026-03-12","insight_id":"ins_078","signal":"action_taken","detail":"用户让我查了挂号"}
```

---

## 5. 处理流水线

### 调度总表

| 任务 | 触发 | 输入 | 输出 | LLM | 预估成本/次 |
|------|------|------|------|-----|------------|
| 感知提取 | 每日新数据到达 | 当天 JSON | entities/events/intents/contexts | Haiku(仅意图分类) | ~$0.001 |
| 日统计更新 | 感知提取后 | 感知层全表 | profile/relationships/patterns 增量 | 无 | $0 |
| 异常检测 | 日统计后 | patterns + 今日数据 | insights | 无 | $0 |
| 意图状态检查 | 日统计后 | intents + events | intents 更新 | 无 | $0 |
| 周画像精炼 | 每周日 22:00 | 7天 digest + profile | profile 更新 | Haiku | ~$0.003 |
| 周关系精炼 | 每两周日 22:00 | interactions 摘要 | relationships 更新 | Haiku | ~$0.005 |
| 周决策分析 | 每周日 22:00 | 决策类 events + transcript | patterns.decision 更新 | Haiku | ~$0.003 |
| 周建议生成 | 周精炼后 | insights + intents + profile | suggestions | Haiku | ~$0.003 |
| 月反馈聚合 | 每月 1 日 | feedback.jsonl | 推送参数调整 | 无 | $0 |

### 每日流水线（~23:30 cron 触发）

```
1. 拉取当天录音 JSON（已有 cron）
2. 感知提取（纯规则 + Haiku 意图分类）
3. 日统计更新（纯规则）
4. 异常检测 → 写入 insights
5. 意图状态检查 → 更新 intents
6. 触发通知判定 → 高优推送/低优攒着
```

预计单日处理时间：<60 秒（含 1 次 Haiku 调用）

---

## 6. 冷启动策略

**核心思路**：不需要用户填任何信息。系统从 Day 1 开始积累，逐渐变聪明。

| 阶段 | 数据量 | 能做什么 | 不能做什么 |
|------|--------|---------|-----------|
| Day 1 | 1天数据 | 日叙事线、活动时间线、基础提醒 | 行为模式、关系判断 |
| Day 7 | 7天 | 作息规律初步画像、高频联系人识别 | 关系类型、决策模式 |
| Day 14 | 14天 | 意图追踪有意义、行为模式初步成型 | 月度趋势、异常检测 |
| Day 30 | 30天 | 完整画像、关系图谱、决策模式、异常检测 | 长期趋势 |
| Day 90+ | 90天 | 趋势分析、季节性模式、深度预测 | — |

**自举过程**：
```
Day 1: 跑感知层，生成 entities/events/intents/contexts
Day 3: profile.json 开始有内容（作息初步值）
Day 7: 触发首次 LLM 画像精炼
Day 14: relationships 开始有 type 判断
Day 30: 全部引擎正常运作
```

---

## 7. 成本控制

### 月度 LLM 预算估算

| 任务 | 频率 | 模型 | tokens/次 | 月费用 |
|------|------|------|-----------|--------|
| 意图分类 | 每日 | Haiku | ~1500 | ~$0.03 |
| 周画像精炼 | 每周 | Haiku | ~4000 | ~$0.012 |
| 周关系精炼 | 每两周 | Haiku | ~3000 | ~$0.005 |
| 周决策分析 | 每周 | Haiku | ~3000 | ~$0.01 |
| 周建议生成 | 每周 | Haiku | ~3000 | ~$0.01 |
| **月合计** | | | | **~$0.07** |

**全年不到 $1**。这是纯后台处理成本，不含用户主动问答。

### 优化策略
- 感知层 100% 纯规则，数据已被 Gemini 预处理过，不需要 LLM 再提取
- 理解层日常纯统计，LLM 只做"精炼"（把统计结果变成人话）
- 推理层统计预测实时可用，LLM 只做周度建议生成
- **永远不把原始 transcript 喂给 LLM**——只用 summary + key_quotes + SVO，省 90% tokens

---

## 8. 迁移方案

### 目标：打包为 OpenClaw Skill

```
personal-intelligence/
├── SKILL.md              # 技能说明
├── scripts/
│   ├── pi_perception.py  # 感知层：实体/事件/意图/情境提取
│   ├── pi_understand.py  # 理解层：画像/关系/模式更新
│   ├── pi_reason.py      # 推理层：洞察/预测/建议
│   ├── pi_action.py      # 行动层：通知/执行/反馈
│   └── pi_bootstrap.py   # 冷启动：首次运行全量处理历史数据
├── config/
│   └── defaults.json     # 默认配置（阈值、频率、渠道映射）
└── references/
    └── schema.md         # 数据模型文档
```

### 配置化而非硬编码

```json
// config/defaults.json
{
  "data_source": {
    "type": "mf_scene_v2",
    "path": "data/daily-reports/"
  },
  "storage_dir": "memory/intelligence/",
  "llm": {
    "extraction_model": "haiku",
    "refinement_model": "haiku",
    "deep_analysis_model": "sonnet"
  },
  "notification": {
    "quiet_hours": [23, 8],
    "max_daily_pushes": 3,
    "channels": ["feishu", "prism"]
  },
  "thresholds": {
    "intent_stale_days": 14,
    "intent_expire_days": 30,
    "relationship_decline_ratio": 0.3,
    "anomaly_sigma": 2.0,
    "svo_confidence_min": 0.75
  }
}
```

### 新实例接入步骤
1. `openclaw skill install personal-intelligence`
2. 配置数据源路径（指向录音 JSON 目录）
3. 首次运行 `pi_bootstrap.py` 处理历史数据
4. 加入 heartbeat/cron 触发每日处理
5. 完成。系统自动从零开始学习用户。

---

## 9. 实施路线图

### Phase 1：感知层 + 基础理解（1-2 周）

**产出**：
- `pi_perception.py` — 四个提取器，全量处理 38 天历史数据
- `entities.json` + `events.jsonl` + `intents.json` + `contexts.jsonl` 填充
- `pi_understand.py` — profile/relationships/patterns 基础统计版
- `pi_bootstrap.py` — 冷启动脚本

**验证标准**：
- 38 天数据处理完成，无报错
- entities 去重后人物数 ≤ 50（合理范围）
- intents 提取 >50 条，且分类合理
- profile.json 有内容，与 MEMORY.md 中已知信息一致

### Phase 2：完整理解 + 推理（3-4 周）

**产出**：
- 理解层 LLM 精炼（周画像、关系类型、决策模式）
- `pi_reason.py` — 洞察生成 + 预测引擎 + 建议生成
- 意图追踪闭环（自动检测完成/搁置/过期）
- 接入 heartbeat 每日自动运行

**验证标准**：
- 周建议质量人工评估 >70% 有用
- 意图追踪准确率 >60%（随机抽查）
- 异常检测无大量误报（<2 条/天）

### Phase 3：行动 + 反馈闭环（5-6 周）

**产出**：
- `pi_action.py` — 通知策略、频率控制、渠道选择
- 反馈回路：用户响应 → feedback.jsonl → 参数调整
- Prism 集成：洞察上屏、意图提醒
- 飞书集成：周报自动发送
- Skill 打包，可迁移

**验证标准**：
- 用户满意度、消息打开率
- 反馈回路确实在调整推送行为
- 新实例冷启动测试通过

---

## 10. 与现有系统的集成点

| 现有系统 | 集成方式 | 方向 |
|---------|---------|------|
| **heartbeat** | 每次 heartbeat 检查是否有待推送的 insight | 推理→行动 |
| **Prism 屏幕** | profile 摘要→便签模式 / insight→闪屏通知 / prediction→NOW 位 | 行动层输出 |
| **米家联动** | prediction.energy_level + contexts → 灯光场景自动调整 | 行动层输出 |
| **飞书** | 高优 insight 直接发消息 / 周建议导出为飞书文档 | 行动层输出 |
| **habit_predictor** | 统计模块复用为 prediction engine 的一部分，规则引擎保留 | 理解→推理 |
| **daily_digest** | 被 pi_perception.py 替代（更完整的信息提取） | 被替代 |
| **idea_capture** | 被 intents.json 的 type=idea 替代（有生命周期管理） | 被替代 |
| **deep_insight** | 被 profile.json 替代（持续更新而非一次性） | 被替代 |

---

## 11. 进程架构与隔离设计

### 现状问题

当前系统有一个严重的架构缺陷：**主 session 是单点瓶颈**。

```
现状（单点架构）：
                    ┌─────────────────────┐
                    │  主 session (Opus)    │
                    │                     │
                    │  • 跟用户聊天        │
                    │  • 派 sub-agent      │
                    │  • prism_update      │  ← 忙的时候顾不上
                    │  • heartbeat 处理    │  ← 被长任务阻塞
                    │  • 盯盘通知          │  ← 可能延迟
                    └─────────────────────┘
```

主 session 在做长任务（写文档、调研）时，所有需要"主动判断"的事情（屏幕状态更新、通知推送、建议触发）都会停滞。虽然 Prism daemon 和米家联动是独立 systemd service，但**智能决策层**（什么时候推什么内容、什么时候该提醒用户）完全依赖主 session 的 heartbeat。

### 目标架构：三层进程隔离

```
目标（隔离架构）：

┌─ 基础设施层（systemd services，永远在跑）──────────────────┐
│                                                            │
│  prism-daemon.service     米家联动 daemon     天气更新      │
│  (屏幕刷新/摄像头/闪屏)   (存在检测→灯控)    (30分钟/次)   │
│                                                            │
│  → 这些不依赖 OpenClaw，Pi 开机就自动跑                      │
│  → 即使 gateway 崩了，屏幕照样显示，灯照样联动               │
└────────────────────────────────────────────────────────────┘
        ▲ 写 state 文件 / events 文件（松耦合）
        │
┌─ 智能后台层（独立 cron / 长驻进程）─────────────────────────┐
│                                                            │
│  pi_daily_pipeline.py    pi_weekly_pipeline.py             │
│  (每日23:30 cron)        (每周日22:00 cron)                │
│                                                            │
│  pi_insight_daemon.py                                      │
│  (长驻，每5分钟检查一次：                                    │
│   - insights 队列有没有需要推的                              │
│   - 是否该触发闪屏/飞书通知                                  │
│   - 盯盘信号 → 闪屏事件)                                    │
│                                                            │
│  → 这些不依赖主 session                                     │
│  → 用自己的 LLM 调用（Haiku），不占主 session context        │
│  → 通过文件系统和主 session 通信（写 insights/suggestions）   │
└────────────────────────────────────────────────────────────┘
        ▲ 读 insights / suggestions（文件系统）
        │
┌─ 主 session 层（OpenClaw gateway）─────────────────────────┐
│                                                            │
│  • 跟用户对话（唯一职责：沟通+决策）                          │
│  • heartbeat 时：读 insights 队列，挑重要的告诉用户          │
│  • 派 sub-agent 做长任务                                    │
│  • prism_update --task 更新当前任务（能做就做，不做也没事）    │
│                                                            │
│  → 这一层挂了/忙了，不影响下面两层                            │
│  → 用户沟通是主 session 唯一不可替代的职责                    │
└────────────────────────────────────────────────────────────┘
```

### 设计原则

#### 原则 1：基础设施无脑跑，不需要智能

Prism daemon、米家联动、天气更新——这些是「反射弧」，不需要大脑参与：
- 摄像头看到人 → 开灯（prism_mijia.py，已实现）
- 每 10 秒读 state 文件 → 刷屏（prism_daemon.py，已实现）
- 每 30 分钟拉天气 → 写缓存（prism_weather.py，已实现）

**不依赖 OpenClaw gateway，不依赖主 session，不依赖网络（除天气）**。Pi 断网了屏幕也照样跑。

#### 原则 2：智能后台独立于主 session

感知提取、理解更新、洞察生成——这些是「后台思考」，需要 LLM 但不需要用户交互：

```python
# pi_insight_daemon.py（长驻后台进程）
while True:
    # 1. 检查是否有新的 insight 需要推送
    insights = load_pending_insights()
    for ins in insights:
        channel = decide_channel(ins, load_prediction())
        if channel == "prism":
            write_prism_event(ins.type, ins.text)  # 写文件，daemon 会读
            ins.pushed = True
        elif channel == "feishu":
            write_feishu_queue(ins)  # 写队列文件
            ins.pushed = True
    save_insights(insights)
    
    # 2. 检查盯盘信号（已有独立脚本的输出）
    stock_alerts = check_stock_alert_file()
    for alert in stock_alerts:
        write_prism_event("alert", alert.text)
    
    sleep(300)  # 5 分钟一次
```

**关键**：这个 daemon 用 `requests` 直接调 Haiku API，不通过 OpenClaw session，不占主 session context。

#### 原则 3：主 session 只做沟通和决策

主 session 的唯一不可替代职责是**跟用户说话**。其他所有事情都可以被后台层接管：

| 职责 | 现在由谁做 | 应该由谁做 |
|------|-----------|-----------|
| 跟用户聊天 | 主 session | 主 session（不变） |
| 派 sub-agent | 主 session | 主 session（不变） |
| 屏幕状态更新 | 主 session prism_update | **后台 daemon**（auto_status 已在做） |
| 闪屏通知触发 | 主 session | **后台 insight daemon** |
| 飞书主动推送 | 主 session heartbeat | **后台 insight daemon** |
| 盯盘告警 | 主 session cron | **后台 insight daemon** 读盯盘输出 |
| 录音数据处理 | 主 session cron | **独立 cron**（不经过 OpenClaw） |
| 画像/关系更新 | 尚未实现 | **独立 cron** |

#### 原则 4：通过文件系统松耦合

各层之间**不互相调用**，只通过文件系统通信：

```
memory/
├── prism_state.json          # 主session/后台 → Prism daemon 读
├── prism_events.json         # 后台 → Prism daemon 读（闪屏）
├── prism_presence.json       # Prism daemon → 后台/米家读
├── prism_weather.json        # 天气cron → Prism daemon读
│
├── intelligence/
│   ├── insights.jsonl        # 智能后台产出 → insight daemon 推送
│   ├── suggestions.json      # 智能后台产出 → 主 session heartbeat 读
│   ├── feishu_queue.jsonl    # insight daemon → 飞书发送脚本
│   └── ...
│
└── stock_alerts.json         # 盯盘cron → insight daemon 读
```

好处：
- 任何一层挂了，其他层不受影响
- 调试简单——看文件就知道每层在干什么
- 不需要 IPC、消息队列、socket——JSON 文件就是接口

### 故障隔离矩阵

| 故障场景 | 影响 | 不受影响 |
|---------|------|---------|
| 主 session 忙/挂了 | 无法聊天、无法手动 prism_update | 屏幕、灯、天气、录音处理、洞察推送 |
| gateway 崩了 | 主 session 断连 | 全部后台（都不依赖 gateway） |
| 网络断了 | LLM 调用失败、天气不更新、飞书推送失败 | 屏幕显示、灯联动、本地统计 |
| Pi 重启 | 短暂中断 | systemd 自动拉起所有 service |
| Haiku API 限流 | 意图分类延迟、精炼延迟 | 纯规则的感知/统计/异常检测照常 |

### 实施步骤

Phase 1 就把进程隔离做进去：
1. `pi_perception.py` 和 `pi_understand.py` 设计为**独立 CLI 脚本**，cron 直接调用，不经过 OpenClaw session
2. `pi_insight_daemon.py` 作为新的 systemd user service，长驻后台
3. 盯盘脚本输出标准化为 `stock_alerts.json`，insight daemon 统一消费
4. 主 session heartbeat 简化为：读 suggestions.json → 挑重要的告诉用户

---

## 附：这个系统和"又一个数据分析工具"的区别

数据分析工具：输入数据 → 输出报告 → 人读报告 → 人做决策。

这个系统：输入数据 → 构建认知 → 产生洞察 → **自动行动** → 收集反馈 → 优化认知。

区别在于闭环。报告没人看就白写了。这个系统的输出端是**动作**——在合适的时候提醒、在合适的时候沉默、在用户没开口之前就准备好他需要的东西。

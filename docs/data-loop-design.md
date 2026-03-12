# 饭团生活数据闭环 — 系统设计文档

> **定位**：这不是给饭团看的报告系统，而是星星自己的理解基础设施。
> 采集→理解→建议→追踪→反馈，形成完整闭环。

---

## 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   数据采集层（已有）                    │
│  daily-report  habit-predictor  摄像头  Prism任务栈   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   理解层（新建）                        │
│  daily_digest.py    idea_capture.py                  │
│  memory/daily-digest/   memory/idea-capture.md       │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   建议层（新建）                        │
│  weekly_review.py   habit_advisor.py                 │
│  memory/habit-suggestions/   suggestion-tracker.json │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   反馈层（新建）                        │
│  suggestion_feedback.py                              │
│  采纳率→habit-predictor规则权重                        │
└─────────────────────────────────────────────────────┘
```

---

## 子系统 A：每日录音分析（daily_digest.py）

### 目的
每天 23:05（daily-report 拉完后 5 分钟）自动运行，把当天录音数据"消化"成星星自己的理解笔记。
**不是给饭团看的**——是星星记住饭团这个人用的。

### 输入
- `data/daily-reports/YYYYMMDD.json`

### 提取维度
| 维度 | 提取方式 |
|------|---------|
| 关键决策 | macro_frames[].outcomes |
| 新想法/灵感 | key_quotes + LLM分类 |
| 情绪状态 | macro_frames[].mood_or_tone 聚合 |
| 社交互动 | scenes[].participants 非p1的人物 |
| 待办/计划 | LLM从summary+quotes中提取 |
| 时间分配 | primary_activity统计（通勤/工作/用餐/运动/休息） |
| 加班判断 | 工作场景结束时间 > 20:00 |

### 输出格式
`memory/daily-digest/YYYY-MM-DD.md`

```markdown
# 日记 2026-03-11（星期三）

## 今日快照
- 状态：focused/tired/stressed/normal
- 活动：工作8h，通勤1.5h，运动0h

## 关键决策
- [ 决策内容 ]

## 新想法/灵感
- [ 提到的想法 ]

## 社交互动
- 跟X在Y说了Z

## 待办/计划
- [ 饭团提到要做的事 ]

## 原始 outcomes
- [ 直接从JSON取 ]
```

### 技术实现
- 脚本：`src/data/daily_digest.py`
- LLM：`pa/claude-haiku-4-5-20251001`（省 token，分析单天数据约 1k-3k tokens）
- 失败处理：API 失败重试 3 次（指数退避），最终降级为纯规则输出（不调 LLM）

---

## 子系统 B：每周行为回顾（weekly_review.py）

### 目的
每周日 20:00 发给饭团一条**简短**的关怀消息。
不是报告，是朋友的关心——"你还好吗？"

### 输入
- `memory/daily-digest/` 过去 7 天
- `memory/habits/daily/` habit-predictor 观察数据
- 上上周的回顾（用于对比）

### 消息风格
**好的**：
> "这周加班了 4 天，比上周多 1 天。运动只有 1 次，周三周四都到 11 点了——你还好吗？"

**不好的**：
> "本周工作效率分析：加班天数 4 天，较上周增加 1 天（+25%）。运动频次 1 次，健康指数下降..."

规则：
- 只挑最显著的 1-2 个变化
- 带一个情感收尾（"你还好吗？"/"这周辛苦了"/"注意休息"）
- 控制在 2 句话以内

### 技术实现
- 脚本：`src/data/weekly_review.py`
- 输出到 stdout，由 cron 通过 `openclaw send` 发给饭团
- 同时存档到 `memory/weekly-reviews/YYYY-WXX.md`

---

## 子系统 C：习惯建议引擎（habit_advisor.py）

### 目的
每周一 9:00，基于过去 2-4 周的行为数据，给出 1-2 条**可执行的**具体建议。

### 建议质量标准
✅ **好建议**（具体、有窗口期、可验证）：
> "你这两周运动都在 23 点后，但周二和周四你 20 点就到家了。试试这两天 20:30 去亚C？"

❌ **坏建议**（空洞、无操作路径）：
> "建议增加运动频率以改善健康状况。"

### 建议生成逻辑
1. 找出 **行为缺口**：想做但没做的（如：运动少）
2. 找出 **可用窗口**：历史数据中有空闲的时间段
3. 合并成：「你想 X，你在 Y 时有空，试试 Y 时做 X？」

### 存档格式
`memory/habit-suggestions/YYYY-WXX.md`

```markdown
# 建议 2026-W11（2026-03-09 周一）

## 建议 1
**内容**：...
**依据**：过去两周周二、周四下班早（均在20点前），但无运动记录
**追踪ID**：sugg-2026W11-001

## 建议 2
**内容**：...
**依据**：...
**追踪ID**：sugg-2026W11-002
```

### 建议发送时机
- 不是每周都发，评估"建议价值阈值"
- 如果这周行为模式没变化，跳过
- 如果有新的明显规律，才发

---

## 子系统 D：想法捕捉器（idea_capture.py）

### 目的
饭团话多，说过的好想法容易被淹没。星星自动捞出来，存档，在合适时机提醒他。

### 捕捉规则（LLM分类）
触发词类：
- "我想做..."、"想试试..."、"有个想法..."
- "如果...就好了"、"能不能做个..."
- "感觉可以..."、"有没有...这样的东西"

过滤掉：
- 闲聊语气的假想法（"要是能不上班就好了"）
- 重复已有想法（比对 idea-capture.md）

### 存档格式
`memory/idea-capture.md`（追加模式，不覆盖）

```markdown
## [2026-03-11] RFID 物品管理

**原话**："感觉可以用 RFID 做个物品定位，找东西方便"
**场景**：家里（晚上闲聊）
**状态**：未追踪
**标签**：#DIY #智能家居 #效率工具

---
```

### 提醒逻辑
- 想法存档满 30 天且"未追踪"→ 在合适时机（饭团在桌前、不忙）提醒一次
- 外部有相关事件时主动关联：比如 AI news 里出现相关项目

---

## 子系统 E：建议追踪与反馈（suggestion_feedback.py）

### 追踪文件
`memory/suggestion-tracker.json`

```json
{
  "suggestions": [
    {
      "id": "sugg-2026W11-001",
      "content": "周二20:30去亚C运动",
      "created_at": "2026-03-09T09:00:00+08:00",
      "type": "exercise",
      "status": "pending",
      "check_after": "2026-03-17",
      "evidence": null,
      "adopted": null
    }
  ]
}
```

### 自动判断采纳逻辑
每周一（生成新建议时）同时检查上周建议：

| 建议类型 | 判断依据 |
|---------|---------|
| 运动建议 | habit-predictor 观察中有 exercise 记录 |
| 睡眠建议 | daily-digest 中活动结束时间 |
| 社交建议 | scenes 中 participants 数量 |
| 工作习惯 | 加班天数变化 |

判断结果：
- `adopted`：下周对应时段有对应行为
- `ignored`：下周无对应行为变化
- `dismissed`：饭团明确说"不想做"（需要手动标记）

### 反馈回规则引擎
在 `memory/habits/behavior_rules.json` 里维护建议类型权重：
- 被采纳 → 对应类型建议权重 +10%（下次更倾向给这类建议）
- 被忽略 → 权重 -5%
- 连续 3 次忽略同类建议 → 暂停这类建议 4 周

---

## Cron 编排建议

> ⚠️ 以下 cron 任务**未自动创建**，请星星跟饭团确认后手动添加。

```cron
# ===================== 饭团生活数据闭环 =====================

# A. 每日录音分析（daily-report 拉完后 5 分钟）
5 23 * * * cd /home/mi/.openclaw/workspace && python3 src/data/daily_digest.py >> logs/daily_digest.log 2>&1

# B. 每周行为回顾（周日 20:00）
0 20 * * 0 cd /home/mi/.openclaw/workspace && python3 src/data/weekly_review.py | openclaw send --channel feishu >> logs/weekly_review.log 2>&1

# C. 习惯建议引擎（周一 09:00）
0 9 * * 1 cd /home/mi/.openclaw/workspace && python3 scripts/habit_advisor.py | openclaw send --channel feishu >> logs/habit_advisor.log 2>&1

# D. 想法捕捉（每天 23:10，daily-report 处理完后）
10 23 * * * cd /home/mi/.openclaw/workspace && python3 src/data/idea_capture.py >> logs/idea_capture.log 2>&1

# E. 建议追踪检查（周一 08:50，建议生成前检查上周）
50 8 * * 1 cd /home/mi/.openclaw/workspace && python3 scripts/suggestion_feedback.py >> logs/suggestion_feedback.log 2>&1
```

**openclaw send 命令格式需确认**（可能需要改成 openclaw message 或其他）。

---

## 数据流向总览

```
每天 23:00  daily-report 拉取数据
         ↓
每天 23:05  daily_digest.py → memory/daily-digest/YYYY-MM-DD.md
         ↓
每天 23:10  idea_capture.py → memory/idea-capture.md
         ↓
每周日 20:00  weekly_review.py → 发消息给饭团
         ↓
每周一 08:50  suggestion_feedback.py → 更新 suggestion-tracker.json
         ↓
每周一 09:00  habit_advisor.py → 发建议给饭团 + 存 memory/habit-suggestions/
```

---

## 脚本清单

| 脚本 | 触发 | 输入 | 输出 |
|------|------|------|------|
| `src/data/daily_digest.py` | cron 23:05 | daily-report JSON | memory/daily-digest/ |
| `src/data/weekly_review.py` | cron 周日20:00 | daily-digest x7 | stdout（消息文本） |
| `src/data/idea_capture.py` | cron 23:10 | daily-report JSON | memory/idea-capture.md |
| `scripts/habit_advisor.py` | cron 周一09:00 | daily-digest x14 + habits | stdout（建议文本） |
| `scripts/suggestion_feedback.py` | cron 周一08:50 | suggestion-tracker + habits | suggestion-tracker.json（更新） |

---

## 技术约束

- **LLM 调用**：全部用 `pa/claude-haiku-4-5-20251001`
- **API 配置**：从 `~/.openclaw/agents/main/agent/models.json` 的 litellm provider 读取
- **重试策略**：指数退避，最大 3 次，失败后降级为纯规则输出
- **输出语言**：中文
- **文件编码**：UTF-8

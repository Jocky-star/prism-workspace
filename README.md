# Prism — 基于 OpenClaw 的自进化 AI 秘书

> 一个跑在 [OpenClaw](https://github.com/nicepkg/openclaw) 上的 Agent Skill：从多源数据理解用户，主动提供服务，追踪反馈，自己养自己。

## 🚀 给 AI Agent 一句话搞定

```
帮我把这个项目 clone 下来并跑起来：git clone git@github.com:Jocky-star/prism-workspace.git
clone 完之后读项目里的 SKILL.md，按里面的步骤配置 LLM 并验证管线能跑通。
```

把上面这段话发给你的 Agent，它会自动完成 clone → 读文档 → 配置 → 验证。

---

Prism 是一个运行在 **[OpenClaw](https://github.com/nicepkg/openclaw)** 上的 Agent Skill。OpenClaw 提供了 Agent 运行时、消息通道、定时任务、sub-agent 调度等基础能力，Prism 在此之上构建了一套**从理解到服务到自我进化**的完整闭环。

它通过录音、对话、摄像头等数据源持续理解你——你的工作节奏、社交关系、兴趣偏好、情绪状态——然后主动为你做事。

**不给建议，给结果。** 不说"建议你去做XX"，而是直接帮你做了。做完之后它会追踪你的反应——用了、忽略了、还是说"别这样"——然后自动调整下次的策略。用得越久，它越懂你要什么、不要什么。

## 它能做什么

### 真实案例：一个普通工作日

你什么都没做。只是正常上班、开会、和同事吃饭、晚上去健身房。

第二天早上 8:30，你收到这条消息：

> ☀️ 早上好
>
> **最近帮你搞定了这些**
>
> 📌 **产品评审会议纪要**
>   昨天下午的评审会，你和老王在方案B上有分歧。我整理了双方论点和未决项，已发到飞书文档。
>
> 📌 **周五团建餐厅帮你选好了**
>   你中午和同事聊到周五团建，我查了附近评分最高的 5 家，推荐"胡同小院"，8 人包间，人均 ¥120。要帮你预定的话告诉我。
>
> **注意到你最近的状态，我主动做了这些**
>
> 💡 你提了三次"想去福州"但一直没动
>   → 帮你查了清明假期直飞福州的航班，最便宜 ¥420（南航晚班），厦航早班 ¥580。要帮你锁一个吗？还是再等等看？
>
> 💡 这周你只去了一次健身房，之前是三次
>   → 明天晚上 21:00 你通常有空，要不要我帮你设个提醒？
>
> **需要你拍板的**
>
> 🔄 团建餐厅选的"胡同小院"，要帮你预定吗？
> 🔄 福州机票要不要帮你锁一个航班？
>
> **自我复盘**
>
> 📉 上周推了 3 次运动提醒，你都没理。我把运动类建议的频率降低了，以后只在你主动提到运动时才跟进。

**你没有做任何操作。** 没有打开 App，没有输入指令，没有设置任何东西。Prism 从你的日常录音、对话、行为中理解了你在意什么，然后直接帮你做了。

---

### 完整能力

#### 🧠 理解你（多数据源 → 用户画像）

| 数据源 | 说明 | 提取内容 |
|--------|------|----------|
| 录音 | 日常录音转写 | 事件、意图、情绪、人物关系 |
| 对话 | 与 AI 助手的聊天记录 | 需求、偏好、反馈 |
| 摄像头 | 桌面摄像头（可选） | 存在状态、姿态、表情 |
| 行为 | 习惯预测引擎 | 作息规律、行为模式 |
| 天气 | 实时天气 | 出行/穿衣建议 |
| 记忆 | 每日记忆日志 | 历史事件、长期偏好 |
| ... | 任何结构化数据 | 继承 `DataSource` 即可接入 |

**插件化架构**：有什么数据就用什么，缺少的自动跳过。新数据源只需继承 `DataSource` 类。

#### 🎯 服务你（理解 → 行动）

| 服务 | 触发 | 做什么 |
|------|------|--------|
| **晨间 Brief** | 每天 8:30 | 帮你做了什么 + 主动洞察 + 需要你拍板的事 |
| **会议洞察** | 有会议时 | 分歧点、你的角色、未决项、行动项 |
| **意图追踪** | 持续 | 你说"想去福州" → 自动查机票推方案 |
| **情绪关怀** | 多信号叠加 | 检测高压信号，像朋友一样关心 |
| **人际洞察** | 每周 | 本周人际动态 + 具体建议 |
| **设备偏好** | 对话触发 | "中午不开灯" → 台灯自动调整 |
| **...** | | 数据源越多，能做的事越多 |

**用户可选**：首次使用推送服务菜单，你选择订阅哪些，随时可调。

#### 🔄 养自己（反馈闭环 → 自我进化）

Prism 不只是越来越了解你，它还会审视自己做得怎么样，然后自动调整。

**它怎么知道做得好不好？** 不需要你打分。所有信号来自自然交互：

| 你的反应 | 它怎么理解 | 它怎么调整 |
|----------|-----------|-----------|
| "好，帮我订" | 强采纳 ✅ | 这类建议加权，下次更积极 |
| "还有别的选择吗" | 方向对，细节不够 | 保留类别，丰富选项 |
| 看了但没回 | 弱拒绝 | 降低频率 |
| "不用" / "别推这个了" | 明确拒绝 ❌ | 这类建议降权，减少推送 |

**它怎么调整自己？**

- 维护一份偏好模型：哪类建议你喜欢（餐厅 80%）、哪类你不感兴趣（运动 20%）
- 每周自我复盘：上周推了多少条？命中率涨了还是跌了？哪些是无用功？
- 连续被忽略的类别自动降频，高采纳类别加权
- 积累足够数据后（≥20 条反馈）才开始调整，避免过拟合

**一句话：用得越久越好用，但不是因为你花时间"训练"它，而是它自己在变。**

## 架构

![Architecture](docs/images/architecture.png)

## 快速开始

### 1. 环境要求

- **[OpenClaw](https://github.com/nicepkg/openclaw)** 已安装并运行（Prism 依赖 OpenClaw 的 Agent 运行时、消息通道和 cron 调度）
- Python 3.10+
- LLM API（兼容 OpenAI 格式）

### 2. 配置 LLM

```bash
# 方式一：环境变量（推荐新用户）
export LLM_BASE_URL=https://your-api-endpoint/v1
export LLM_API_KEY=your-api-key
export LLM_MODEL=claude-haiku-4-5-20251001  # 可选

# 方式二：models.json（OpenClaw 用户自动读取）
# 如果 ~/.openclaw/agents/main/agent/models.json 已配好 litellm provider，无需额外配置
```

### 3. 看看你有什么数据

```bash
python3 src/services/data_sources.py --discover
```

输出示例（新用户只有对话数据）：
```
✅ chat — 对话记录（chat_messages.jsonl）
❌ audio — 录音数据（无数据，跳过）
❌ vision — 摄像头（无数据，跳过）
```

### 4. 跑一次试试

```bash
# Dry-run（不调 LLM，验证数据流通）
python3 src/services/pipeline.py --dry-run

# 真实运行（调 LLM 生成内容）
python3 src/services/pipeline.py --date 2026-03-12
```

### 5. 设置定时任务

```bash
# 一键安装所有定时任务（晨间Brief 8:30 / 每日管线 23:40 / 每周洞察 周日21:00）
bash setup_crons.sh
```

安装后每天 8:30 会自动收到晨间 Brief，无需手动操作。

### 6. 看看生成了什么

```bash
# 晨间 Brief
python3 src/services/generators/daily_brief.py --date 2026-03-12 --format

# 意图追踪
python3 src/services/generators/intent_tracker.py --date 2026-03-12

# 服务偏好菜单
python3 src/services/pipeline.py --check-prefs
```

## 文件结构

```
src/
├── services/                    # 🎯 服务闭环系统（核心）
│   ├── README.md                #    详细文档
│   ├── config.py                #    统一配置（路径自动检测）
│   ├── llm_client.py            #    LLM 调用（环境变量 / models.json）
│   ├── data_sources.py          #    多数据源适配器（插件注册制）
│   ├── preferences.py           #    用户服务偏好管理
│   ├── device_preferences.py    #    设备偏好（台灯等）
│   ├── pipeline.py              #    服务管线编排
│   └── generators/              #    服务生成器
│       ├── daily_brief.py       #      晨间简报
│       ├── meeting_insight.py   #      会议洞察
│       ├── intent_tracker.py    #      意图追踪与行动
│       ├── emotion_care.py      #      情绪关怀
│       └── social_insight.py    #      人际洞察
│
├── intelligence/                # 🧠 智能理解层
│   ├── perception.py            #    感知：提取实体/事件/意图
│   ├── understand.py            #    理解：画像/关系/模式
│   ├── refine.py                #    精炼：LLM 深度分析
│   └── weekly_refine.py         #    每周回顾
│
├── actions/                     # 🎬 执行层
│   ├── planning/                #    规划与调度
│   ├── monitoring/              #    监控（新闻/股票等）
│   └── integrations/            #    外部设备（米家台灯）
│
├── screen/                      # 📺 Prism 屏幕（可选，需树莓派）
│   ├── daemon.py                #    主 daemon
│   ├── display.py               #    渲染引擎
│   └── ...
│
└── infra/                       # ⚙️ 基础设施
    └── ...
```

## 扩展

### 新增数据源

```python
# src/services/data_sources.py 中添加

class CalendarDataSource(DataSource):
    name = "calendar"
    description = "日历数据"
    
    def is_available(self) -> bool:
        return (MEMORY_DIR / "calendar.json").exists()
    
    def get_today_data(self, date: str) -> Dict[str, Any]:
        # 实现数据读取...

# 注册到 ALL_SOURCES 列表
ALL_SOURCES.append(CalendarDataSource)
```

### 新增服务

在 `src/services/generators/` 下新建文件，实现 `generate_xxx()` 函数，然后在 `pipeline.py` 中注册。

详见 [src/services/README.md](src/services/README.md)。

## 设计理念

1. **不给建议，给结果** — 不是"你可能需要做XX"，而是"我已经帮你做了XX"
2. **个性化是相处，不是配置** — 没有设置界面，通过持续理解来适应你
3. **自己养自己** — 追踪每次反馈，自动调整策略，越用越准，不需要你"训练"
4. **插件化** — 有什么数据就用什么，缺了不崩溃，新数据源随时加
5. **宁缺毋滥** — 没有有价值内容时不推送，不凑数
6. **自驱力** — 理解你之后主动行动，不等指令

## 硬件（可选）

完整的 Prism 硬件终端需要：

| 组件 | 型号 | 用途 |
|------|------|------|
| 主板 | Raspberry Pi 5 | 计算核心 |
| 屏幕 | MHS35 3.5" SPI (ili9486) | 480×320 状态显示 |
| 摄像头 | IMX708 | 存在检测 + 视觉识别 |

没有硬件也能用——服务系统只需要数据源和 LLM API。

**设备联动（有人/无人触发设备）** 可通过 `prism_config.yaml` 配置，无需修改代码。
内置米家台灯插件，其他设备（Yeelight、智能插座等）可自行编写插件放入 `src/screen/plugins/`。
详见 SKILL.md 的"设备联动"章节。

## 产品文档

- [服务闭环设计](docs/service-loop-design.md)
- [智能理解系统设计](docs/intelligence-system-design.md)
- [完整产品书 (飞书)](https://ccnq3wnum0kr.feishu.cn/docx/YnGAd3FomoALdKx4n9McCQ7dnPd)

## License

Private project. All rights reserved.

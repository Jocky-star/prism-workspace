# Prism — 理解你，然后为你做事

> 从多源数据中理解用户，主动提供个性化服务。不需要配置，只需要相处。

Prism 不是一个需要你打开、操作、设置的应用。它通过录音、对话、摄像头等数据源持续理解你——你的工作节奏、社交关系、兴趣偏好、情绪状态——然后主动为你做事。

**不给建议，给结果。** 不说"建议你去做XX"，而是直接帮你做了。

## 它能做什么

### 🧠 理解你（多数据源 → 用户画像）

| 数据源 | 说明 | 提取内容 |
|--------|------|----------|
| 录音 | 日常录音转写（mf_scene_v2.x） | 事件、意图、情绪、人物关系 |
| 对话 | 与 AI 助手的聊天记录 | 需求、偏好、反馈 |
| 摄像头 | 桌面摄像头（可选） | 存在状态、姿态、表情 |
| 行为 | 习惯预测引擎 | 作息规律、行为模式 |
| 天气 | 实时天气 | 出行/穿衣建议 |
| 记忆 | 每日记忆日志 | 历史事件、长期偏好 |

**插件化架构**：有什么数据就用什么，缺少的自动跳过，不影响其他功能。新数据源只需继承 `DataSource` 类。

### 🎯 服务你（理解 → 行动）

| 服务 | 触发 | 做什么 |
|------|------|--------|
| **晨间 Brief** | 每天 8:30 | 昨天帮你做了什么 + 今天准备好的内容 |
| **会议洞察** | 有会议时 | 分歧点、你的角色、未决项、行动项 |
| **意图追踪** | 持续 | 你说"想去福州" → 自动查机票推方案 |
| **情绪关怀** | 多信号叠加 | 检测高压信号，像朋友一样关心 |
| **人际洞察** | 每周 | 本周人际动态 + 具体建议 |
| **设备偏好** | 对话触发 | "中午不开灯" → 台灯自动调整 |

**用户可选**：首次使用推送服务菜单，你选择订阅哪些，随时可调。

### 💡 设备控制（理解 → 自动化）

说一句"中午 13 到 14 点不开台灯"，完整链路自动运行：

```
对话捕捉 → LLM 意图分类(preference) → 解析为设备规则 → 写入偏好 → 立即执行 → 持续生效
```

不需要打开任何设置，不需要知道有配置文件存在。**个性化是相处，不是配置。**

### 📺 桌面屏幕（可选，需树莓派）

3.5 寸 SPI 屏幕，三种模式自动切换：
- **暗屏**：无人时显示时间 + 天气
- **状态板**：有人时显示当前任务 / 已完成 / 提醒
- **便签**：傍晚自动展示今日摘要

摄像头检测到你 → 屏幕亮起 → 显示你需要的信息。你离开 → 屏幕回归安静。

## 架构

```
┌────────────────────────────────────────────────────────┐
│                     数据源（可扩展）                       │
│  录音 │ 对话 │ 摄像头 │ 行为 │ 天气 │ 记忆 │ ...        │
└───────┬───────┬────────┬──────┬──────┬──────┬──────────┘
        │       │        │      │      │      │
        ▼       ▼        ▼      ▼      ▼      ▼
┌─────────────────────────────────────────────────────────┐
│                    感知层 (perception)                    │
│            提取实体、事件、意图、情境                        │
├─────────────────────────────────────────────────────────┤
│                    理解层 (understand)                    │
│            用户画像、社交图谱、行为模式                      │
├─────────────────────────────────────────────────────────┤
│                  服务生成层 (services)                    │
│  晨间Brief │ 会议洞察 │ 意图追踪 │ 情绪关怀 │ 设备偏好     │
├─────────────────────────────────────────────────────────┤
│                    推送 / 执行层                          │
│         飞书消息 │ Prism 屏幕 │ 米家台灯 │ ...           │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- [OpenClaw](https://github.com/openclaw/openclaw) 运行中
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

### 5. 看看生成了什么

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
3. **插件化** — 有什么数据就用什么，缺了不崩溃，新数据源随时加
4. **宁缺毋滥** — 没有有价值内容时不推送，不凑数
5. **自驱力** — 理解你之后主动行动，不等指令

## 硬件（可选）

完整的 Prism 硬件终端需要：

| 组件 | 型号 | 用途 |
|------|------|------|
| 主板 | Raspberry Pi 5 | 计算核心 |
| 屏幕 | MHS35 3.5" SPI (ili9486) | 480×320 状态显示 |
| 摄像头 | IMX708 | 存在检测 + 视觉识别 |

没有硬件也能用——服务系统只需要数据源和 LLM API。

## 产品文档

- [服务闭环设计](docs/service-loop-design.md)
- [智能理解系统设计](docs/intelligence-system-design.md)
- [完整产品书 (飞书)](https://ccnq3wnum0kr.feishu.cn/docx/YnGAd3FomoALdKx4n9McCQ7dnPd)

## License

Private project. All rights reserved.

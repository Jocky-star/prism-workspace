# Prism — 你的个人智能秘书

从多数据源理解用户，主动提供服务。基于 OpenClaw 平台。

---

## 🚀 Agent 必读：安装与配置指南

你（Agent）是用户的 OpenClaw Assistant。当用户让你安装 Prism 时，按以下步骤操作。
**用户不需要手动执行任何命令，全部由你来完成。**

### 阶段一：基础安装（5 分钟）

```bash
# 1. 进入项目目录（如果是 clone 来的）
cd prism-workspace

# 2. 初始化配置文件
python3 main.py setup
# → 自动复制 config.example.yaml → config.yaml

# 3. 向用户收集以下信息，填入 config.yaml：
#    必填：
#    - feishu.app_id        — 飞书应用 App ID
#    - feishu.app_secret    — 飞书应用 App Secret  
#    - feishu.target_user_open_id — 用户的飞书 Open ID
#    - llm.endpoint         — LLM API 地址（OpenAI 兼容格式）
#    - llm.api_key          — LLM API Key
#
#    获取飞书配置：https://open.feishu.cn → 创建自建应用 → 凭证与基础信息
#    飞书需要的权限：im:message:send_v2（发送消息）

# 4. 验证
python3 main.py status
# → 检查飞书和 LLM 是否都显示 ✅

# 5. 预览第一份 Brief
python3 main.py brief --dry-run
```

**基础安装完成后，用户每天 8:30 会收到一份个人简报。**

### 阶段二：数据源接入（按需）

运行 `python3 main.py guide` 查看所有可配置项。

Prism 的能力取决于接入的数据源。数据越多，服务越智能。

| 数据源 | 配置项 | 需要什么 | 能做什么 |
|--------|--------|----------|----------|
| 对话记录 | 自动 | 零配置，从 OpenClaw memory/ 读取 | 理解用户意图和偏好 |
| 录音转写 | `sources.audio.*` | 音频转写 API | 深度理解用户生活（会议/社交/想法） |
| 股票监控 | `sources.stock.*` | 关注列表 | 行情播报、技术信号 |
| 摄像头 | `features.camera.*` | 树莓派 + 摄像头 | 存在检测、健康关怀 |

**示例：开启录音数据源**
```yaml
# 编辑 config.yaml
sources:
  audio:
    enabled: true
    api_url: "https://用户的转写服务地址"
    api_key: "用户的 API Key"
```

### 阶段三：定时任务（一键完成）

```bash
python3 main.py cron-setup
```

自动设置以下定时任务（幂等，重复运行安全）：
- **22:45** — 拉取录音数据
- **23:10** — 每日智能管线（感知 → 理解 → 摘要）
- **23:20** — 服务管线（Brief 生成）
- **08:30** — 晨间 Brief 推送到飞书
- **周日 20:00** — 周精炼（人物合并/关系精判）

### 阶段四：硬件扩展（可选）

以下功能需要特定硬件，大多数用户可以跳过。

**米家智能家居**
```yaml
features:
  mijia:
    enabled: true
    username: "用户手机号"
    password: "用户密码"
    region: "cn"
```
开启后：根据用户存在状态自动控灯、根据对话偏好调整亮度色温。

**Prism 状态屏（树莓派 + SPI 屏）**
```yaml
features:
  screen:
    enabled: true
```
开启后：实时显示当前任务状态、天气、提醒。

**摄像头感知**
```yaml
features:
  camera:
    enabled: true
    rotation: 180  # 如果摄像头物理倒置
```
开启后：检测用户是否在桌前，联动灯和屏幕。

---

## 📋 日常使用命令

安装完成后，以下是你（Agent）日常会用到的命令：

### 核心命令

| 命令 | 说明 |
|------|------|
| `python3 main.py status` | 系统状态总览 |
| `python3 main.py brief` | 生成并推送今日 Brief |
| `python3 main.py brief --dry-run` | 预览 Brief 不推送 |
| `python3 main.py guide` | 查看配置引导 |
| `python3 main.py cron-setup` | 设置/更新定时任务 |

### 服务管线

```bash
# 完整管线（会调 LLM）
python3 src/services/pipeline.py --date YYYY-MM-DD

# Dry-run（不调 LLM，验证数据流）
python3 src/services/pipeline.py --date YYYY-MM-DD --dry-run

# 单独跑某条管线
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline daily
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline morning
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline weekly
```

### 单独调用服务生成器

```bash
# 晨间 Brief
python3 src/services/generators/daily_brief.py --date YYYY-MM-DD --format

# 意图追踪（从对话/录音中捕捉用户意图）
python3 src/services/generators/intent_tracker.py --date YYYY-MM-DD

# 情绪关怀（多信号叠加检测）
python3 src/services/generators/emotion_care.py --date YYYY-MM-DD

# 会议洞察（分歧/决策/行动项）
python3 src/services/generators/meeting_insight.py --date YYYY-MM-DD

# 人际洞察（本周社交动态）
python3 src/services/generators/social_insight.py --date YYYY-MM-DD
```

### 智能理解层

```bash
# 感知：从录音提取实体/事件/意图
python3 src/intelligence/perception.py --date YYYYMMDD

# 理解：生成用户画像/社交图谱
python3 src/intelligence/understand.py

# 周精炼：人物合并/关系精判/价值观提取
python3 src/intelligence/weekly_refine.py

# 冷启动：批量处理所有历史数据
python3 src/intelligence/bootstrap.py
```

### 数据源

```bash
# 发现可用数据源
python3 src/services/data_sources.py --discover

# 手动拉取录音数据
python3 src/sources/audio/fetch.py --date YYYY-MM-DD
```

### Prism 屏幕（需要硬件）

```bash
# 更新屏幕状态
python3 src/screen/update.py --task "正在做的事"
python3 src/screen/update.py --done "完成的事"
python3 src/screen/update.py --note "提醒内容"

# 事件闪屏
python3 src/screen/event.py --type info --text "有新消息"
```

### 设备偏好

```bash
# 查看当前规则
python3 src/services/device_preferences.py --list

# 用户说"中午不开灯"时，intent_tracker 会自动处理
# 手动添加也行：
python3 src/services/device_preferences.py --add-lamp "13" "off" "午休不开灯"
```

---

## 🔌 插件系统（开发者）

Prism 支持三类插件，新的数据源/设备/服务不需要改核心代码。

### 插件类型

| 类型 | 用途 | 接口 | 示例 |
|------|------|------|------|
| Source | 数据进来 | `setup()` `fetch()` `health_check()` | 录音、戒指、日历 |
| Pipeline | 数据加工 | `generate()` `format()` | Brief、健康报告 |
| Actuator | 动作出去 | `execute()` `get_capabilities()` | 台灯、空调、音箱 |

### 插件结构

```
plugins/sources/my-source/
├── manifest.yaml      # 声明配置项和输出格式
├── plugin.py          # 实现标准接口
├── README.md          # 给 Agent 看的说明
└── requirements.txt   # Python 依赖（可选）
```

### manifest.yaml 示例

```yaml
name: oura-ring
type: source
version: "1.0.0"
description: "Oura 智能戒指健康数据"

config:
  api_token:
    type: string
    required: true
    description: "Oura API Token"
    help_url: "https://cloud.ouraring.com/personal-access-tokens"

output:
  format: jsonl
  fields:
    - name: sleep_score
      type: number
    - name: heart_rate_avg
      type: number

schedule:
  cron: "0 6 * * *"
  description: "每天早上6点同步"

# 插件携带的能力（Agent 自动注册）
capabilities:
  # 引用已有的 OpenClaw Skill
  skills:
    - name: oura-health-skill
      source: clawhub
      description: "Oura 健康数据查询和分析"
  # 插件自带 MCP Server
  mcp_servers:
    - name: oura-mcp
      command: "python3 mcp_server.py"
      tools: [get_sleep, get_heart_rate, get_activity]
  # 插件自带 Skill 目录
  bundled_skills:
    - path: skills/health-alert
      description: "健康异常告警"
```

### 能力声明（capabilities）

插件可以携带三种能力，Agent 安装插件后**自动注册**，不需要用户手动配置：

| 能力类型 | 说明 | 安装后效果 |
|----------|------|------------|
| `skills` | 引用 clawhub 上已有的 Skill | 自动 `npx skills install` |
| `mcp_servers` | 插件自带 MCP Server | 自动注册到 OpenClaw MCP 配置 |
| `bundled_skills` | 插件目录下的 Skill | 自动复制到 `~/.openclaw/skills/` |

Agent 安装完插件后，可以运行 `python3 main.py capabilities` 查看所有已注册的能力。

### plugin.py 示例（Source）

```python
from prism.plugin_base import SourcePlugin

class OuraRingSource(SourcePlugin):
    def setup(self, config: dict) -> bool:
        """验证配置是否有效"""
        self.token = config.get("api_token")
        return bool(self.token)
    
    def fetch(self, date: str) -> list[dict]:
        """拉取指定日期的数据"""
        # 调 API，返回标准格式
        return [{"sleep_score": 85, "heart_rate_avg": 62}]
    
    def health_check(self) -> dict:
        return {"status": "ok", "last_sync": "2026-03-16"}
```

### Prism 屏幕插件（三层架构）

如果用户有树莓派，屏幕系统使用独立的插件配置 `prism_config.yaml`：

```yaml
sensors:
  - plugin: rpicam
    config:
      rotation: 180

detectors:
  - plugin: frame_diff
    config:
      threshold: 0.005
  - plugin: vision_api
    config:
      scene: "办公桌前"

devices:
  - plugin: spi_screen
    config:
      fb_path: "/dev/fb0"
  - plugin: mijia_lamp
```

写新插件只需实现对应接口，放到 `src/screen/plugins/` 目录，配置注册即可。

---

## 📁 项目结构

```
main.py                    # 统一入口
config.yaml                # 用户配置（不入 git）
config.example.yaml        # 配置模板

src/
├── services/              # 服务系统（Brief/意图/情绪/会议/社交）
│   ├── generators/        # 各服务生成器
│   ├── pipeline.py        # 管线调度
│   ├── morning_push.py    # 飞书推送
│   ├── config.py          # 配置读取
│   ├── llm_client.py      # LLM 调用
│   └── data_sources.py    # 数据源注册
├── intelligence/          # 智能理解（感知/理解/精炼）
├── sources/               # 数据源（录音/摄像头/对话/股票）
├── screen/                # Prism 屏幕（需硬件）
│   └── plugins/           # 三层插件（sensor/detector/device）
├── actions/               # 执行层（监控/规划/集成）
└── infra/                 # 基础设施

memory/                    # 数据存储（不入 git）
├── intelligence/          # 理解层输出（画像/关系/事件）
├── services/              # 服务输出（Brief）
├── action_log/            # 行动日志
├── visual/                # 摄像头记录
└── habits/                # 行为数据

plugins/                   # 插件目录（未来扩展）
├── sources/
├── pipelines/
└── actuators/
```

---

## ⚠️ 注意事项

- 所有脚本从**项目根目录**运行：`python3 src/services/xxx.py`
- LLM 默认使用轻量模型（省钱），可通过 config.yaml 的 `llm.default_model` 调整
- `--dry-run` 参数可在不调 LLM 的情况下验证数据流
- config.yaml 包含敏感信息，已在 .gitignore 中，不会被推到 GitHub
- 数据目录（memory/、data/）也不入 git

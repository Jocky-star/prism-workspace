# Prism — Personal Ambient Intelligence

> 一个运行在树莓派上的桌面智能终端，它认识你、记住你、预判你需要什么。

Prism 不是一个需要你打开、操作、设置的应用。它是一个安静存在于桌面的设备——通过摄像头感知你的存在，通过屏幕与你交流，通过 AI 理解你的习惯和需求，然后主动为你做事。

没有设置界面。没有配置文件。**个性化不是配置，是相处。**

## 它能做什么

### 🧠 理解你

从日常录音数据中提取你的行为模式、社交关系、兴趣意图：

- **感知层**：识别人物、地点、事件、意图（`pi_perception.py`）
- **理解层**：构建用户画像、社交图谱、行为模式（`pi_understand.py`）
- **精炼层**：LLM 每日/每周深度分析，持续修正理解（`pi_refine.py`, `pi_weekly_refine.py`）
- **行动层**：基于理解主动行动——运动提醒、社交关怀、待办跟进（`pi_action.py`）

### 📺 桌面屏幕

3.5 寸 SPI 屏幕（480×320），三种模式自动切换：

- **暗屏**：无人时显示时间 + 天气，低功耗
- **状态板**：有人时显示当前任务 / 已完成 / 提醒
- **便签**：傍晚自动展示今日摘要

摄像头检测到你坐下 → 屏幕亮起 → 显示你需要的信息。你离开 → 屏幕回归安静。

### 💡 智能联动

- **米家台灯**：根据时段和你的存在自动调节灯光场景
- **事件闪屏**：重要事件三色闪屏提醒（红/蓝/绿）
- **天气**：实时天气显示，出门前一目了然

### 🔔 推送（宁缺毋滥）

只推有价值的内容，绝不用垃圾信息骚扰你：

| 等级 | 内容 | 渠道 |
|------|------|------|
| S 级 | 经 LLM 精炼的周报 | 飞书 |
| A 级 | 高优待办跟进提醒 | Prism 屏幕 |
| B 级 | 股票/时效性提醒 | Prism 屏幕 |
| C/D 级 | 低置信度观察 | 仅记录，不推送 |

## 架构

```
录音数据 / 摄像头 / 传感器
        ↓
┌─────────────────────────────┐
│  感知层 (pi_perception)      │  提取实体、事件、意图、情境
├─────────────────────────────┤
│  理解层 (pi_understand)      │  画像、关系、模式
├─────────────────────────────┤
│  精炼层 (pi_refine)          │  LLM 深度分析 + 每周回顾
├─────────────────────────────┤
│  行动层 (pi_action)          │  自主行动 + 推送决策
└─────────────────────────────┘
        ↓
   Prism 屏幕 / 飞书 / 米家
```

每一层独立脚本，进程隔离，通过 JSON 文件通信。

## 硬件

| 组件 | 型号 | 用途 |
|------|------|------|
| 主板 | Raspberry Pi 5 | 计算核心 |
| 屏幕 | MHS35 3.5" SPI (ili9486) | 480×320 状态显示 |
| 摄像头 | IMX708 | 存在检测 + 视觉识别 |
| 存储 | 32GB SD（计划升级 SSD） | 系统 + 数据 |

总 BOM ≈ ¥975

## 文件结构

```
scripts/
├── pi_perception.py          # 感知：从录音提取实体/事件/意图/情境
├── pi_understand.py          # 理解：构建画像/关系/模式
├── pi_refine.py              # 精炼：LLM 每日分析
├── pi_weekly_refine.py       # 精炼：每周深度回顾
├── pi_daily_pipeline.py      # 管线：每日 感知→理解→精炼
├── pi_action.py              # 行动：自主行动规划与执行
├── pi_generate_insights.py   # 洞察：生成推送内容（含质量门控）
├── pi_insight_daemon.py      # 推送：后台 daemon，决定推送渠道
├── pi_bootstrap.py           # 冷启动：首次运行批量处理历史数据
├── pi_check_notifications.py # 通知：检查待推送队列
│
├── prism_daemon.py           # 屏幕主 daemon：刷新+存在检测+联动
├── prism_display.py          # 屏幕渲染：fb0 直写 + 2x 超采样
├── prism_update.py           # CLI：更新屏幕状态
├── prism_event.py            # 事件闪屏：三色提醒
├── prism_weather.py          # 天气模块
├── prism_transition.py       # 渐变过渡动画
├── prism_mijia.py            # 米家联动逻辑
├── prism_intelligence.py     # 屏幕智能内容生成
├── prism_auto_status.py      # 状态自动流转
├── prism_task.py             # 任务管理
│
├── camera_check.py           # 摄像头：定时拍照 + AI 识别
├── camera_lock.py            # 摄像头：flock 资源锁
├── wellness_check.py         # 健康关怀：姿态/疲劳检测
├── mijia_lamp.py             # 米家台灯控制
├── daily_digest.py           # 录音每日摘要
├── idea_capture.py           # 灵感捕捉（从录音提取）
├── weekly_review.py          # 每周行为回顾
├── stock_news_fetcher.py     # 财经消息面抓取
├── stock_news_monitor.py     # 股票异动监控
├── gateway_watchdog.sh       # OpenClaw 网关看门狗
└── post_update_restart.sh    # 更新后自动重启

docs/
├── intelligence-system-design.md  # 智能理解系统设计文档
├── data-loop-design.md            # 数据闭环设计
├── gateway-reliability.md         # 网关可靠性方案
├── service-evolution-design.md    # 服务演进设计
├── prism-ssd-knob-plan.md         # SSD + 旋钮扩展计划
└── xhs-content-upgrade-plan.md    # 小红书内容升级方案
```

## 快速开始

### 环境要求

- Raspberry Pi 5（4GB+ RAM）
- MHS35 SPI 屏幕（ili9486 驱动）
- IMX708 摄像头模块
- Python 3.11+
- [OpenClaw](https://github.com/openclaw/openclaw) 作为 Agent 框架
- LLM API（兼容 OpenAI 格式）

### 部署

```bash
# 1. 克隆代码
git clone git@github.com:Jocky-star/prism-workspace.git
cd prism-workspace

# 2. 安装依赖
pip install pillow requests

# 3. 配置 LLM API（在 OpenClaw 的 models.json 中配置）

# 4. 冷启动（首次运行，处理历史录音数据）
python3 scripts/pi_bootstrap.py

# 5. 启动屏幕 daemon
python3 scripts/prism_daemon.py --daemon

# 6. 启动洞察推送 daemon
python3 scripts/pi_insight_daemon.py --daemon

# 7. 设置定时任务
# 每日管线（23:40）
# 每周精炼（周日 21:00）
# 行动检查（9:00-22:00 每小时）
```

### systemd 服务（推荐）

```ini
# ~/.config/systemd/user/prism-display.service
[Unit]
Description=Prism Display Daemon
After=default.target

[Service]
ExecStart=/usr/bin/python3 /path/to/scripts/prism_daemon.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable prism-display.service
systemctl --user start prism-display.service
```

## 给 AI Agent 使用

本项目包含一份 [`SKILL.md`](./SKILL.md)，是面向 AI Agent 的操作手册。如果你使用 [OpenClaw](https://github.com/openclaw/openclaw) 或其他 Agent 框架，可以直接将 SKILL.md 注入到 Agent 的上下文中，Agent 就能自主操作整个系统。

### 方式一：OpenClaw Skill（推荐）

将本项目作为 OpenClaw skill 安装：

```bash
# 在 OpenClaw workspace 的 skills/ 目录下 clone
cd ~/.openclaw/workspace/skills/
git clone git@github.com:Jocky-star/prism-workspace.git prism

# OpenClaw 会自动扫描 skills/ 下的 SKILL.md，Agent 在需要时自动加载
```

或者在 `AGENTS.md` 中手动注册：

```markdown
## Available Skills
- prism: ~/.openclaw/workspace/skills/prism/SKILL.md
```

### 方式二：直接喂给任意 Agent

把 SKILL.md 内容作为 system prompt 或上下文注入：

```python
# 读取 SKILL.md 作为 Agent 的参考
with open("SKILL.md") as f:
    skill_context = f.read()

messages = [
    {"role": "system", "content": f"你可以使用以下工具操作 Prism 系统：\n\n{skill_context}"},
    {"role": "user", "content": "更新屏幕显示'正在开会'"}
]
```

### 方式三：作为 MCP / Tool Description

SKILL.md 中的每个命令都可以封装为 tool call：

```json
{
  "name": "prism_update_task",
  "description": "更新 Prism 屏幕当前任务",
  "parameters": {
    "task": { "type": "string", "description": "当前任务描述，12字以内" }
  },
  "command": "python3 scripts/prism_update.py --task '{task}'"
}
```

### Agent 能做什么

拿到 SKILL.md 后，Agent 可以：

- 🖥️ 控制屏幕显示（任务/完成/提醒/闪屏）
- 🧠 运行智能理解管线（感知→理解→精炼→行动）
- 📊 查询用户画像、行为模式、社交关系
- 💡 管理推送（遵守质量门控规则）
- 🔧 检查和重启后台服务
- 📷 调用摄像头拍照识别

## 设计理念

1. **个性化是相处，不是配置** — 没有设置页面，Agent 通过持续观察和理解来适应你
2. **宁缺毋滥** — 推送必须过质量门控，一条错误推送的伤害大于十条正确推送的价值
3. **进程隔离** — 每个脚本独立运行，通过 JSON 文件通信，任何一个崩溃不影响其他
4. **隐私优先** — 所有数据本地处理，不上传云端，代码仓库排除一切隐私数据
5. **自驱力** — 理解用户后主动行动，不是等指令的工具

## 产品文档

完整产品设计文档（飞书）：[Prism v3.1 产品书](https://ccnq3wnum0kr.feishu.cn/docx/YnGAd3FomoALdKx4n9McCQ7dnPd)

## License

Private project. All rights reserved.

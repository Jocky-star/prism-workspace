# src/services — 多数据源理解→服务闭环系统

基于录音、对话、摄像头等多路数据源，自动理解用户行为和状态，驱动晨间简报、会议洞察、情绪关怀等服务，并将用户意图转化为设备控制动作的闭环系统。

---

## 架构图

```
数据层                    理解层                    服务层                    执行层
──────                    ──────                    ──────                    ──────
录音 (mf_scene_v2.x)  ──┐
对话 (chat_messages)  ──┤                        ┌─ daily_brief    ──→ Feishu 消息推送
摄像头 (visual/*.jsonl)──┤→ DataSourceRegistry ──→─ meeting_insight ──→ Feishu 消息推送
行为 (behavior_rules)  ──┤  (data_sources.py)    ├─ intent_tracker ──→ 待办/意愿追踪
天气 (weather.json)   ──┤                        ├─ emotion_care   ──→ Feishu 关怀消息
记忆 (YYYY-MM-DD.md)  ──┘                        └─ social_insight ──→ Feishu 周报
                                                                              ↓
                                                   intent_tracker ──→ device_preferences ──→ device 插件（台灯/屏幕等）
                                                  (对话中提取意图)    (device_preferences.py)  (prism_config.yaml 配置)
```

Pipeline 调度（`pipeline.py`）：
- **每日**：meeting_insight → intent_tracker → emotion_care
- **晨间推送**：daily_brief（推送前一天数据）
- **每周**：social_insight

---

## 快速开始

### 前置要求

- Python 3.10+
- OpenClaw 正在运行（用于 Feishu 消息推送）
- 工作目录：`~/.openclaw/workspace`（或自定义 `WORKSPACE` 环境变量）

### LLM 配置

**方式一：models.json**（推荐，OpenClaw 已有配置时自动读取）

系统自动从 `~/.openclaw/agents/main/agent/models.json` 读取模型配置，无需额外设置。

**方式二：环境变量**

```bash
export LLM_API_KEY=your_api_key
export LLM_BASE_URL=https://api.openai.com/v1   # 或兼容 OpenAI 的端点
export LLM_MODEL=gpt-4o-mini                    # 任意支持的模型
```

### 检查有哪些数据源

```bash
cd ~/.openclaw/workspace
python3 src/services/data_sources.py --discover
```

输出示例：
```
=== 数据源发现 ===
  ✅ chat — 对话记录（chat_messages.jsonl）
  ❌ audio — 录音数据（需要 audio-daily-insight skill）
  ...
已注册: ['chat']
```

### 运行一次 dry-run

```bash
python3 src/services/pipeline.py --date 2026-03-12 --dry-run
```

输出：
```
🔄 Running DAILY pipeline for 2026-03-12
  [1/3] Meeting insight... ✓
  [2/3] Intent tracker...  ✓
  [3/3] Emotion care...    ✓
✅ daily: 3 steps, 0 errors
```

---

## 数据源

系统支持插件化数据源，只有 `is_available()` 返回 True 的才会被注册。不存在的数据源会被静默跳过，不影响其他服务运行。

### audio — 录音数据

- **来源**：`audio-daily-insight` skill 处理后的 JSON 文件
- **路径**：`{WORKSPACE}/skills/audio-daily-insight/raw_json/`
- **格式**：`mf_scene_v2.x` JSON（含 scenes、key_quotes、moods、activities）
- **如何获取**：安装并运行 `audio-daily-insight` skill

### chat — 对话记录

- **来源**：OpenClaw 对话记录导出
- **路径**：`{WORKSPACE}/memory/intelligence/chat_messages.jsonl`
- **格式**：每行一个 JSON
  ```json
  {"date": "2026-03-12", "text": "消息内容", "source": "chat", "timestamp": "2026-03-12T14:00:00"}
  ```
- **如何获取**：OpenClaw 主 session 自动写入；也可手动创建

### vision — 摄像头观察

- **来源**：`pi-camera-vision` skill 的识别结果
- **路径**：`{WORKSPACE}/memory/visual/YYYY-MM-DD.jsonl`
- **格式**：每行一条观察记录（人物、情绪、场景）
- **如何获取**：安装并运行 `pi-camera-vision` skill

### habit — 行为规律

- **来源**：`habit-predictor` skill 分析结果
- **路径**：`{WORKSPACE}/memory/habits/behavior_rules.json`
- **格式**：行为规则 + 习惯画像
- **如何获取**：安装并运行 `habit-predictor` skill

### weather — 天气数据

- **来源**：天气 skill / cron 抓取
- **路径**：`{WORKSPACE}/memory/prism_weather.json` 或 `memory/weather.json`
- **格式**：`{"temp": 22, "desc": "晴", ...}`
- **如何获取**：使用 `weather` skill 获取并写入

### memory — 每日记忆日志

- **来源**：OpenClaw 主 session 每日写入
- **路径**：`{WORKSPACE}/memory/YYYY-MM-DD.md`
- **格式**：Markdown 文本（事件、任务、对话摘要）
- **如何获取**：主 session 自动生成

---

## 服务列表

### daily_brief — 晨间简报

每天早上推送前一天的关键信息汇总。

```bash
# 查看格式化输出（dry-run）
python3 src/services/generators/daily_brief.py --date 2026-03-12 --dry-run --format
```

**示例输出**：
```
☀️ 晨间 Brief | 2026-03-12
📌 昨日完成：代码review、写文档
💭 今日提示：下午3点有会议
```

**配置**：`memory/service_preferences.json`
```json
"daily_brief": {"enabled": true, "time": "08:30", "channel": "feishu"}
```

---

### meeting_insight — 会议洞察

从录音数据中识别会议片段，提取分歧、决策和行动项。

```bash
python3 src/services/generators/meeting_insight.py --date 2026-03-12 --dry-run
```

**示例输出**：
```
🗓 Found 2 meeting(s)
Meeting 1: 产品评审 (45 min)
  → 行动项：下周前完成原型
```

**依赖**：`audio` 数据源（无录音数据时静默跳过）

---

### intent_tracker — 意图追踪

从对话和录音中提取待办、愿望、想法、计划。

```bash
python3 src/services/generators/intent_tracker.py --date 2026-03-12 --dry-run
```

**示例输出**：
```
🎯 Intents found: 3
  [todo] 明天开会前准备PPT (92%)
  [wish] 周末想去爬山 (85%)
```

**副作用**：自动写入 `device_preferences`（如识别到设备偏好意图）

---

### emotion_care — 情绪关怀

多信号叠加评分，超过阈值时发送关怀消息。

```bash
python3 src/services/generators/emotion_care.py --date 2026-03-12 --dry-run
```

**评分信号**：音频情绪 + 视觉状态 + 对话内容 + 行为异常

**示例输出**：
```
📊 Signal score: 0 / threshold: 2
✅ 情绪状态正常，无需关怀
```

---

### social_insight — 人际洞察

周度分析人际互动，识别关系变化和值得关注的动态。

```bash
python3 src/services/generators/social_insight.py --date 2026-03-12 --dry-run
```

**示例输出**：
```
📊 Events analyzed: 87
📋 本周人际互动正常
  💡 建议：许久未联系张三，可以发条消息
```

**频率**：每周一次（默认）

---

## 设备控制

### 台灯偏好系统

台灯通过 `src/screen/plugins/devices/mijia_lamp.py`（device 插件）驱动，
由 `prism_config.yaml` 中的 `devices` 配置启用。

**工作流程**：
```
用户对话："晚上8点后不要开灯了"
    ↓
intent_tracker 提取意图
    ↓
device_preferences.add_lamp_rule(hours=[20,21,22,23], scene="off")
    ↓
determine_scene() 读取规则覆盖默认逻辑
    ↓
台灯 device 插件在20点后保持关闭
```

**查看当前规则**：
```bash
python3 src/services/device_preferences.py --list
```

**手动添加规则**：
```python
from src.services.device_preferences import add_lamp_rule
add_lamp_rule(hours=[13, 14], scene="off", reason="午休不开灯", source="manual")
```

**规则优先级**：device_preferences 覆盖 determine_scene 的默认时间场景逻辑。

---

## 扩展指南

### 新增数据源

在 `data_sources.py` 中继承 `DataSource`：

```python
class MyDataSource(DataSource):
    name = "mydata"
    description = "我的数据（描述格式）"

    def is_available(self) -> bool:
        # 检查数据是否存在
        return Path("/some/path").exists()

    def load(self, date: str) -> Optional[Dict[str, Any]]:
        # 加载指定日期的数据
        # 返回 None 表示该日期无数据
        return {"key": "value"}
```

然后在 `DataSourceRegistry.__init__()` 中注册：
```python
self._register(MyDataSource())
```

---

### 新增服务生成器

在 `src/services/generators/` 创建新文件：

```python
# src/services/generators/my_service.py
from src.services.data_sources import DataSourceRegistry
from src.services.llm_client import call_llm

def generate(date: str, dry_run: bool = False) -> dict:
    """
    返回标准结果字典：
    {"success": bool, "data": {...}, "summary": "一行摘要"}
    """
    reg = DataSourceRegistry()
    data = reg.load_all(date)

    if dry_run:
        return {"success": True, "data": {}, "summary": "[DRY-RUN] 测试正常"}

    # 调用 LLM 处理
    prompt = f"基于数据：{data.get('chat', {})}，分析..."
    result = call_llm(prompt)
    return {"success": True, "data": {"raw": result}, "summary": result[:50]}
```

然后在 `pipeline.py` 的对应 pipeline 中添加调用。

---

## 配置参考

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WORKSPACE` | 工作目录根路径 | `~/.openclaw/workspace` |
| `OPENCLAW_WORKSPACE` | 同上（备用名） | — |
| `LLM_API_KEY` | LLM API Key | 从 models.json 读取 |
| `LLM_BASE_URL` | LLM API 端点 | 从 models.json 读取 |
| `LLM_MODEL` | 使用的模型名 | 从 models.json 读取 |

### 配置文件路径

| 文件 | 说明 |
|------|------|
| `memory/service_preferences.json` | 服务订阅偏好（enabled/disabled） |
| `memory/device_preferences.json` | 设备控制规则（台灯等） |
| `memory/services/` | 各服务输出缓存（JSON） |
| `~/.openclaw/agents/main/agent/models.json` | LLM 模型配置（OpenClaw 自动维护） |

---

## 文件结构

```
src/services/
├── README.md                  ← 本文件
├── __init__.py
├── config.py                  ← 统一路径配置（WORKSPACE 解析）
├── data_sources.py            ← 数据源适配器 + 注册表
├── device_preferences.py      ← 设备偏好 CRUD
├── llm_client.py              ← LLM 调用（支持 models.json + 环境变量）
├── pipeline.py                ← 调度编排（daily/morning/weekly）
├── preferences.py             ← 服务订阅偏好管理
└── generators/
    ├── __init__.py
    ├── daily_brief.py         ← 晨间简报
    ├── meeting_insight.py     ← 会议洞察
    ├── intent_tracker.py      ← 意图追踪 + 设备偏好提取
    ├── emotion_care.py        ← 情绪关怀
    └── social_insight.py      ← 人际洞察（周度）
```

---

## 常用命令速查

```bash
# 发现数据源
python3 src/services/data_sources.py --discover

# 查看某天数据详情
python3 src/services/data_sources.py --date 2026-03-12 --verbose

# 完整 pipeline dry-run
python3 src/services/pipeline.py --date 2026-03-12 --dry-run

# 查看/修改服务订阅
python3 src/services/pipeline.py --check-prefs

# 查看台灯规则
python3 src/services/device_preferences.py --list

# LLM 配置检查
python3 src/services/llm_client.py

# LLM 实际调用测试
python3 src/services/llm_client.py --test-call

# 新用户环境测试
WORKSPACE=/tmp/test_user python3 src/services/data_sources.py --discover
WORKSPACE=/tmp/test_user python3 src/services/pipeline.py --date 2026-03-12 --dry-run
```

# Brief 服务

每日晨间简报系统 — 汇聚多数据源，生成个人化 AI 秘书简报，推送到飞书。

## 系统架构

```
数据源层                    生成层                    推送层
─────────────────────      ──────────────────      ────────────────
AudioDataSource          ↘
ChatDataSource           →  DataSourceRegistry  →  generate_brief()
VisionDataSource         →  data_sources.py     →  daily_brief.py
HabitDataSource          →                      →
WeatherDataSource        →                      ↘  format_brief_message()
MemoryDataSource         →                               ↓
IntelligenceDataSource   →                         morning_push.py
ConversationDataSource   →                               ↓
ActionLogDataSource      ↗                         飞书 Interactive Card
```

### 核心原则

- **Brief 只汇报真正发生的事** — `action_log` 是唯一事实源
- **不给建议，给结论** — 每条都有具体数据（价格/时间/地址）
- **个人化** — 基于 `intelligence` 层对用户的长期理解

## 快速开始（新用户）

### 1. 配置

```bash
cp src/services/config.example.yaml src/services/config.yaml
```

编辑 `config.yaml`，至少填写：
- `brief.target_user_id`：你的飞书 open_id
- `feishu.tenant_domain`：你的飞书租户域名

### 2. 配置 LLM（选一种）

**方式 A：环境变量（推荐新用户）**
```bash
export LLM_BASE_URL=https://your-api/v1
export LLM_API_KEY=your-key
export LLM_MODEL=claude-haiku-4-5-20251001
```

**方式 B：OpenClaw 已安装**
自动读取 `~/.openclaw/agents/main/agent/models.json`，无需额外配置。

### 3. 配置飞书凭证（选一种）

**方式 A：OpenClaw 已安装**
自动读取 `~/.openclaw/openclaw.json` 中的 `channels.feishu.appSecret`，无需额外配置。

**方式 B：环境变量**
```bash
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
```

### 4. 运行

```bash
# 测试（不调 LLM，不发飞书）
python3 src/services/morning_push.py --dry-run

# 本地预览（不发飞书）
python3 src/services/morning_push.py --no-feishu

# 正式运行
python3 src/services/morning_push.py
```

### 5. 设置定时任务（OpenClaw cron）

在 OpenClaw 后台配置每天 08:30 执行：
```
python3 /path/to/workspace/src/services/morning_push.py
```

## 文件说明

| 文件 | 职责 |
|------|------|
| `config.py` | 所有配置的统一入口（路径、飞书、LLM、Brief 参数） |
| `config.example.yaml` | 配置模板（复制为 config.yaml 后使用） |
| `morning_push.py` | 主入口：生成 Brief → 格式化 → 推送飞书 |
| `generators/daily_brief.py` | Brief 生成逻辑（prompt + LLM 调用 + 格式化） |
| `data_sources.py` | 数据源适配器注册（插件化，可扩展） |
| `llm_client.py` | LLM API 调用封装（OpenAI 兼容接口） |
| `feedback_tracker.py` | 记录建议 → 用户反馈 → 偏好学习 |
| `action_log.py` | 系统实际执行的行动记录（Brief 唯一事实源） |

## 数据目录说明

所有数据存储在 `memory/` 目录下（通过 `WORKSPACE` 环境变量配置）：

```
memory/
├── YYYY-MM-DD.md        # 每日对话记忆日志
├── todo.md              # 待办事项
├── services/            # Brief 输出（JSON）
│   └── YYYY-MM-DD.json
├── action_log/          # 行动日志（Brief 事实源）
│   └── YYYY-MM-DD.jsonl
├── intelligence/        # 用户长期理解层
│   ├── profile.json     # 用户画像
│   ├── patterns.json    # 行为模式
│   ├── intents.json     # 历史意图
│   ├── insights.jsonl   # 洞察记录
│   └── chat_messages.jsonl  # 聊天消息
├── feedback/            # 用户反馈数据
│   ├── suggestions.jsonl
│   └── responses.jsonl
├── visual/              # 摄像头观察记录
│   └── YYYY-MM-DD.jsonl
└── habits/              # 行为预测数据
    └── behavior_rules.json
```

## 环境变量参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WORKSPACE` | 工作目录路径 | `~/.openclaw/workspace` |
| `BRIEF_TARGET_USER_ID` | 飞书推送目标 open_id（逗号分隔多个） | 未设置时只输出 stdout |
| `BRIEF_PUSH_TIME` | 推送时间（仅供参考） | `08:30` |
| `BRIEF_MAX_CHARS` | 内容字数限制（0=不限） | `0` |
| `FEISHU_TENANT_DOMAIN` | 飞书租户域名 | `open.feishu.cn` |
| `FEISHU_APP_ID` | 飞书应用 ID | 从 openclaw.json 读 |
| `FEISHU_APP_SECRET` | 飞书应用密钥 | 从 openclaw.json 读 |
| `LLM_BASE_URL` | LLM API 地址 | 从 models.json 读 |
| `LLM_API_KEY` | LLM API 密钥 | 从 models.json 读 |
| `LLM_MODEL` | LLM 模型名称 | `claude-haiku-4-5-20251001` |

## 扩展数据源

在 `data_sources.py` 中继承 `DataSource` 并注册到 `ALL_SOURCES`：

```python
class MyDataSource(DataSource):
    name = "my_source"
    description = "我的数据源"

    def is_available(self) -> bool:
        return Path("/my/data/dir").exists()

    def get_today_data(self, date: str) -> Dict[str, Any]:
        # 加载并返回数据
        return {"available": True, "data": ...}

# 注册
ALL_SOURCES.append(MyDataSource)
```

## 添加行动记录

让你的 proactive 服务记录到 action_log，Brief 才会汇报：

```python
from src.services.action_log import log_action

log_action(
    category="proactive",          # proactive / delivery / intent_followup
    title="查了北京→福州机票",
    detail="清明4/4厦航¥500晚班最便宜，已备好比价表",
    insight="你提到清明想去福州看演出",
)
```

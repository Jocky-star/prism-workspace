# 对话记录数据源

## 给 Agent 的说明

**默认启用**，零配置，无需任何 API Key。
自动从 OpenClaw 的 `memory/` 目录读取用户的聊天记录和记忆日志。

这是最核心的数据源，几乎所有管线都依赖它：
- **晨间 Brief**：读取昨日对话，理解用户关注的话题
- **意图追踪**：从对话中提取用户表达的意图（想去哪、想买什么、要做什么）
- **社交洞察**：分析一周内的对话，了解人际动态

## 配置方式

无需配置！在 `config.yaml` 中可选启用：

```yaml
sources:
  chat:
    enabled: true   # 默认即可，无其他配置项
```

## 验证

```bash
python3 main.py plugins verify chat
```

## 输出格式

```json
{
  "date": "2026-03-16",
  "available": true,
  "messages": [
    {"text": "我想去福州旅游", "timestamp": "2026-03-16T14:30:00", "source": "chat"}
  ],
  "recent_memories": [
    {"date": "2026-03-16", "content": "...记忆日志内容..."}
  ],
  "feedback": {
    "adopted_suggestions": [...],
    "ignored_suggestions": [...]
  }
}
```

## 相关命令

```bash
# 手动提取指定日期的对话记录
python3 src/sources/chat/extract.py --date 2026-03-16

# 插件详情
python3 main.py plugins info chat
```

## 读取的文件

| 路径 | 内容 |
|------|------|
| `memory/YYYY-MM-DD.md` | 每日记忆日志（Agent 自动写入） |
| `memory/intelligence/profile.json` | 用户画像 |
| `memory/intelligence/intents.json` | 意图追踪历史 |
| `memory/todo.md` | 待办事项 |

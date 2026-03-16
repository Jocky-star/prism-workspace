# 录音转写数据源

## 给 Agent 的说明

当用户有音频转写服务（如 Gemini 语音转写）时启用此插件。
启用后，系统每晚自动拉取用户当天的录音转写文本，用于：
- **晨间 Brief**：引用用户说过的话，让 Brief 更个性化
- **意图追踪**：捕捉用户在对话中表达的想法、计划和愿望
- **情绪关怀**：通过录音中的情绪标签检测用户状态
- **会议洞察**：从 activity=meeting 的场景中提炼决策和行动项

## 配置方式

在 `config.yaml` 中设置：

```yaml
sources:
  audio:
    enabled: true
    api_url: "https://your-audio-service.com/api"
    api_key: "your-api-key-here"
```

## 验证

```bash
python3 main.py plugins verify audio
```

## 输出格式

```json
{
  "date": "2026-03-16",
  "available": true,
  "scenes": [
    {
      "activity": "meeting",
      "start_time": "10:30",
      "summary": "与团队讨论产品方向",
      "key_quotes": [{"text": "我们下周要上线", "speaker": "user"}]
    }
  ],
  "key_quotes": [...],
  "moods": ["focused", "slightly_tired"],
  "macro_frames": [...]
}
```

## 相关命令

```bash
# 手动拉取指定日期的录音
python3 src/sources/audio/fetch.py --date 2026-03-16

# 插件详情
python3 main.py plugins info audio
```

## 何时启用

- 用户已接入音频转写服务（Gemini Audio、Whisper 等）
- 需要基于"用户说了什么"生成晨间 Brief 的场景
- 需要捕捉口头表达的意图（而非文字聊天）

## 不需要时

如果用户没有录音设备或转写服务，不需要配置此插件。
其他插件（daily-brief、intent-tracker）在 audio 不可用时会自动降级，不影响基本功能。

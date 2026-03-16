# 情绪关怀管线

## 给 Agent 的说明

当检测到用户情绪低落或状态异常时，自动发送温暖的关怀消息。

**检测来源**（多信号叠加）：
- 录音情绪标签（tired / anxious / sad 等）
- 摄像头观察到的面部状态
- 行为异常（睡眠时间异常、作息紊乱）

**灵敏度**：
- `high` — 任何一个负面信号就触发（容易误报）
- `normal` — 需要2个以上信号（默认，推荐）
- `low` — 需要3个以上信号（只在明显异常时触发）

## 配置方式

```yaml
pipelines:
  emotion-care:
    enabled: true
    sensitivity: normal    # low / normal / high
    dry_run: false
```

## 验证

```bash
python3 main.py plugins verify emotion-care
```

## 相关命令

```bash
# 手动运行
python3 src/services/generators/emotion_care.py --date 2026-03-16

# 调整灵敏度测试
python3 src/services/generators/emotion_care.py --date 2026-03-16 --sensitivity high --dry-run
```

## 输出格式

```json
{
  "triggered": true,
  "signal_score": 2,
  "signals": ["录音情绪: 疲惫", "摄像头观察: 低沉"],
  "care_message": "看起来今天挺累的，要不要休息一下？"
}
```

## 依赖

- `audio` 数据源（可选，无则跳过录音信号检测）
- `camera` 数据源（可选，无则跳过视觉信号检测）

两者都没有时，此管线实际上不会触发（没有信号可检测）。

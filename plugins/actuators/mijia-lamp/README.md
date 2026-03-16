# 米家台灯执行器

## 给 Agent 的说明

通过小米云端 API 控制米家台灯，根据用户的存在状态和时段偏好自动调整亮度和色温：
- **有人来了** → 根据当前时段选择合适的场景（专注/休闲/夜间）
- **人走了** → 自动关灯
- **时段偏好自动学习** → 用户说"中午不开灯"，intent-tracker 会自动更新偏好规则

**典型场景**：下午2点坐下来工作 → 台灯自动切到专注模式（高亮冷色）

## 配置方式

在 `config.yaml` 中设置：

```yaml
actuators:
  mijia-lamp:
    enabled: true
    username: "your-xiaomi-account@email.com"
    password: "your-password"
    region: "cn"    # cn / de / us / ru / tw / sg / in / i2
```

## 验证

```bash
python3 main.py plugins verify mijia-lamp
```

## 相关命令

```bash
# 直接控制台灯
python3 src/actions/integrations/mijia_lamp.py --scene focus
python3 src/actions/integrations/mijia_lamp.py --scene off

# 查看时段偏好规则
cat memory/intelligence/device_preferences.json

# 通过 Agent 对话控制
# 在聊天中说: "帮我把台灯调成专注模式"
# 或: "台灯关掉"
```

## 台灯场景说明

| 场景 | 亮度 | 色温 | 适用时段 |
|------|------|------|----------|
| `focus` | 高 | 冷白 | 工作/学习 |
| `relax` | 中 | 暖白 | 休息/阅读 |
| `night` | 低 | 最暖 | 夜间 22点+ |
| `normal` | 自动 | 自动 | 随时段调整 |
| `off` | — | — | 无人/睡觉 |

## 时段偏好自学习

对话中说出偏好后，intent-tracker 会自动解析并应用：
> "我中午12到14点不喜欢开灯"
> → 自动写入规则：hours=[12,13], scene=off

当前偏好规则：`memory/intelligence/device_preferences.json`

## 相关技能

使用 `mijia-device-manager` 技能可以查看所有米家设备、控制其他设备。

## 何时启用

- 用户有米家智能台灯
- 用户希望灯光随工作状态自动变化
- 配合 camera（存在检测）使用时效果最佳

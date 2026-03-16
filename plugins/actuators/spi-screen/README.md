# SPI 屏幕执行器

## 给 Agent 的说明

控制树莓派上的 SPI 接口小屏幕（MHS35 480×320 ili9486 等）。
屏幕会根据用户的存在状态自动切换显示模式：
- **有人在** → 显示当前任务状态（NOW/DONE/NOTE）
- **18-20点** → 显示便签摘要（粘性提醒）
- **无人** → 暗屏显示时间

**需要硬件**：Raspberry Pi + SPI 接口小屏幕 + `/dev/fb0`

## 配置方式

在 `config.yaml` 中设置：

```yaml
actuators:
  spi-screen:
    enabled: true
    fb_path: "/dev/fb0"        # framebuffer 设备路径
    display_interval: 10       # 刷新间隔秒数（默认10秒）
```

## 验证

```bash
python3 main.py plugins verify spi-screen
```

## 相关命令

```bash
# 更新屏幕上的当前任务
python3 src/screen/update.py --task "写代码"
python3 src/screen/update.py --task "开会中" --note "有重要邮件"

# 插件详情
python3 main.py plugins info spi-screen

# 查看 Prism 屏幕技能文档
# 详见 ~/.openclaw/skills/prism-screen/SKILL.md
```

## 显示内容控制

| 状态 | 显示内容 |
|------|----------|
| `--task "XXX"` | NOW: XXX |
| 任务完成 | DONE: XXX（自动流转） |
| `--note "XXX"` | NOTE: XXX（替换随机诗句） |
| 无人检测到 | 暗屏：时间 + 日期 |
| 18-20点 | 便签摘要 |

## 事件闪屏

当 `memory/prism_events.json` 中有未处理事件时，屏幕会闪屏显示：
- `alert` — 红色背景
- `info` — 蓝色背景
- `done` — 绿色背景

## 何时启用

- 用户有树莓派 + SPI 小屏
- 需要物理显示当前工作状态
- 配合 camera（存在检测）使用时效果最佳

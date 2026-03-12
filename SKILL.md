# Prism — Personal Ambient Intelligence

桌面智能终端：摄像头感知 + SPI 屏幕显示 + 录音数据理解 + 自主行动。运行在树莓派上。

## 什么时候使用这个 skill

- 需要更新 Prism 屏幕内容（任务/完成/提醒）
- 需要运行智能理解管线（感知/理解/精炼/行动）
- 需要查询用户画像、行为模式、社交关系
- 需要控制米家台灯联动
- 需要检查摄像头/屏幕/推送 daemon 状态

## 核心命令

### 屏幕控制（最常用）

```bash
# 更新当前任务（旧任务自动转为"已完成"）
python3 src/screen/update.py --task "正在做的事"

# 标记完成
python3 src/screen/update.py --done "做完的事"

# 添加提醒（最多3条，多了自动挤掉最旧的）
python3 src/screen/update.py --note "要提醒用户的话"

# 清除提醒（会自动换一句随机诗词）
python3 src/screen/update.py --clear-notes

# 触发事件闪屏（alert=红/info=蓝/done=绿，屏幕闪3次）
python3 src/screen/update.py --event "alert:紧急消息"
python3 src/screen/update.py --event "info:普通通知"
python3 src/screen/update.py --event "done:任务完成"

# 查看当前屏幕状态
python3 src/screen/update.py --show
```

### 智能理解管线

```bash
# 每日全量管线（感知→理解→精炼），通常由 cron 在 23:40 自动跑
python3 src/intelligence/daily_pipeline.py
python3 src/intelligence/daily_pipeline.py --date 20260312    # 指定日期
python3 src/intelligence/daily_pipeline.py --force             # 强制重跑

# 单独运行各层
python3 src/intelligence/perception.py              # 感知：提取实体/事件/意图/情境
python3 src/intelligence/perception.py --stats      # 查看感知统计
python3 src/intelligence/understand.py              # 理解：生成画像/关系/模式
python3 src/intelligence/refine.py                  # 精炼：LLM 每日分析
python3 src/intelligence/weekly_refine.py           # 每周深度回顾（cron 周日 21:00）

# 冷启动（首次部署，批量处理历史数据）
python3 src/intelligence/bootstrap.py
```

### 行动系统

```bash
# 检查并执行待处理行动（cron 每小时 9-22 点）
python3 src/intelligence/action.py

# 只看行动计划，不执行
python3 src/intelligence/action.py --plan

# 执行指定行动
python3 src/intelligence/action.py --execute <action_id>

# 查看历史统计
python3 src/intelligence/action.py --stats

# 记录用户反馈（正面/负面）
python3 src/intelligence/action.py --feedback <action_id> positive
python3 src/intelligence/action.py --feedback <action_id> negative
```

### 洞察生成

```bash
# 生成今日洞察（由管线自动调用）
python3 src/intelligence/generate_insights.py

# 只检查特定类型
python3 src/intelligence/generate_insights.py --check-intents
python3 src/intelligence/generate_insights.py --check-patterns
python3 src/intelligence/generate_insights.py --check-relationships
```

### 数据采集（src/sources/）

所有外部数据源统一在 `src/sources/` 下，每种数据一个子目录。接入新数据源只需加子目录。

```bash
# 摄像头：拍照 + AI 识别（用户身份判定）
python3 src/sources/camera/capture.py

# 摄像头：健康关怀检测（姿态/疲劳/水杯）
python3 src/sources/camera/wellness.py

# 摄像头：延时摄影（每小时一张 + 每晚拼视频）
python3 src/sources/camera/timelapse.py

# 录音数据：拉取最新录音转写
python3 src/sources/audio/fetch.py

# 股票消息面：抓取财经新闻
python3 src/sources/stock/news_fetcher.py

# 股票监控：异动检测
python3 src/sources/stock/news_monitor.py
```

### 米家台灯

```bash
# 台灯由 prism_daemon.py 自动控制：
# - 检测到人 → 按时段切换灯光场景
# - 无人 → 关灯
# - 手动操作保护：检测到用户手动调灯后 30 分钟不覆盖
# 如需手动控制，使用 mijia CLI
```

## 数据文件（memory/intelligence/）

| 文件 | 内容 | 读写 |
|------|------|------|
| `entities.json` | 人物/地点/话题实体库 | 感知层写，全局读 |
| `events.jsonl` | 时间线事件流 | 感知层写 |
| `intents.json` | 用户意图（todo/wish/idea/plan） | 感知层写，行动层读 |
| `contexts.jsonl` | 场景记录（会议/通勤/运动等） | 感知层写 |
| `profile.json` | 用户画像（性格/习惯/偏好） | 理解层写，行动层读 |
| `relationships.json` | 社交关系图谱 | 理解层写 |
| `patterns.json` | 行为模式（作息/运动日等） | 理解层写，行动层读 |
| `insights.jsonl` | 生成的洞察（含推送状态） | 洞察层写，daemon 读 |
| `actions.jsonl` | 行动历史记录 | 行动层读写 |
| `refine_log.jsonl` | LLM 精炼日志 | 精炼层写 |
| `pipeline_state.json` | 管线执行状态 | 管线写 |
| `feishu_queue.jsonl` | 飞书推送队列 | daemon 读写 |

## 屏幕状态文件（memory/）

| 文件 | 内容 |
|------|------|
| `prism_state.json` | 屏幕显示内容（task/done/notes） |
| `prism_presence.json` | 摄像头存在检测结果 |
| `prism_events.json` | 闪屏事件队列 |
| `prism_weather.json` | 天气缓存 |

## 后台服务

```bash
# 屏幕 daemon（刷新 + 摄像头检测 + 米家联动）
systemctl --user status prism-display.service
systemctl --user restart prism-display.service

# 洞察推送 daemon（每5分钟检查 insights.jsonl）
systemctl --user status pi-insight-daemon.service
systemctl --user restart pi-insight-daemon.service
```

## 推送规则（重要！）

**宁可不推也不要推错。** 推送经过 `is_pushworthy()` 质量门控：

- ✅ 推：周报（S级）、高优待办跟进（A级）、股票提醒（B级）
- ❌ 不推：录音碎片推断、低置信度观察、unknown 类型意图
- 推送渠道：安静时间（23:00-08:00）只推 Prism 屏幕，不推飞书
- 飞书每日上限 3 条

## Cron 任务

| 时间 | 任务 | 脚本 |
|------|------|------|
| 9-22 每小时 | 行动检查 | `pi_action.py` |
| 23:40 | 每日管线 | `pi_daily_pipeline.py` |
| 周日 21:00 | 每周精炼 | `pi_weekly_refine.py` |

## 依赖

- Python 3.11+、Pillow、requests
- OpenClaw（Agent 框架 + Gateway）
- LLM API（OpenAI 兼容格式，配置在 `~/.openclaw/agents/main/agent/models.json`）
- 硬件：Raspberry Pi 5 + MHS35 SPI 屏幕 + IMX708 摄像头

## 注意事项

- 摄像头使用 flock 锁（`camera_lock.py`），避免多进程抢占
- 摄像头已硬件旋转 180°（`--rotation 180`），不需要软件旋转
- 屏幕 fb0 颜色映射：`pixel = ((b>>3)<<11) | ((r>>2)<<5) | (g>>3)` big-endian
- 中文字体用 DroidSansFallbackFull，英文/数字用 DejaVuSans-Bold
- 所有脚本从 `models.json` 动态读取 API key，不硬编码

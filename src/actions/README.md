# src/actions/ — 行动执行层

监控、分析、规划、设备集成脚本的汇总目录。

## 子目录说明

### monitoring/ — 实时监控
外部信号的实时监控脚本，可被 cron 直接调用。

| 文件 | 说明 | cron 引用 |
|------|------|----------|
| `ai_news_radar.py` | AI 新闻雷达（RSS 聚合） | ✅ AI新闻日报 |
| `dual_factor_signal.py` | 双因子月度调仓信号 | |
| `forex_monitor.py` | 外汇监控（CNY/HKD） | |
| `hk_extended_monitor.py` | 港股监控（中烟香港） | |
| `xhs_comments.py` | 小红书评论监控（selenium） | |
| `xhs_competitor_monitor.py` | 小红书竞品监控 | |
| `xialiao_heartbeat.py` | 虾聊社区心跳 | |

### analysis/ — 数据分析
离线数据分析工具，手动运行或定期执行。

| 文件 | 说明 |
|------|------|
| `api_usage_tracker.py` | API 用量追踪（自动写入） |
| `api_usage_report.py` | API 用量报告（手动运行） |
| `daily_report_analyze.py` | 每日报告分析 |
| `daily_report_deep_insight.py` | 深度洞察分析 |
| `price_compare_poc.py` | 电商价格对比 PoC（selenium，实验性） |

### planning/ — 智能规划（旧版 pi_* 系列）
> ⚠️ **被 cron 引用，请勿移动这些文件！**

基于洞察/意图的自动规划和执行，是 `src/intelligence/` 的"行动"端。

| 文件 | 说明 | cron 引用 |
|------|------|----------|
| `action.py` | 行动层主程序 | ✅ PI行动检查 |
| `daily_pipeline.py` | 每日智能管线 | ✅ PI每日管线 |
| `generate_insights.py` | 洞察生成器 | |
| `insight_daemon.py` | 洞察推送后台 daemon | |
| `check_notifications.py` | 通知检查 | |

### integrations/ — 设备集成
> ⚠️ **被 screen/plugins 引用，请勿移动！**

直接控制硬件设备的接口层。

| 文件 | 说明 |
|------|------|
| `mijia_lamp.py` | 米家台灯控制（screen 插件依赖此模块） |

---

## 与其他目录的边界

- `monitoring/` vs `sources/`：monitoring 是**主动拉取+告警**，sources 是**被动采集+存储**
- `planning/` vs `services/`：planning 是旧版自主规划系统（面向 intelligence 层），services 是新版服务闭环（面向用户推送）
- `integrations/` vs `screen/plugins/devices/`：integrations 是底层设备驱动，screen 插件是上层调度接口

# src/ — 代码架构说明

## 目录分层

```
src/
├── sources/          # 🔌 数据采集层 — 外部数据源接入
│   ├── audio/        #   录音转写数据（API 拉取）
│   ├── camera/       #   摄像头图像采集历史
│   ├── chat/         #   对话记录提取
│   └── stock/        #   股票/财经消息（东方财富 API）
│
├── intelligence/     # 🧠 智能理解层 — 感知→理解→精炼→行动
│   ├── perception.py       #   感知层（从原始数据提取结构化信息）
│   ├── understand.py       #   理解层（行为分析、模式识别）
│   ├── refine.py           #   精炼层（LLM 精炼，生成洞察）
│   ├── weekly_refine.py    #   周度精炼
│   ├── bootstrap.py        #   初始化引导
│   ├── daily_digest.py     #   每日录音分析，生成理解笔记
│   ├── idea_capture.py     #   从对话/录音中捕捉灵感
│   └── weekly_review.py    #   每周行为回顾生成
│
├── services/         # 🔄 服务闭环层 — 数据→生成→推送的完整闭环
│   ├── data_sources.py     #   数据源适配器注册表（统一接入 sources/）
│   ├── pipeline.py         #   服务调度编排（daily/morning/weekly）
│   ├── morning_push.py     #   晨间推送主程序
│   ├── llm_client.py       #   LLM 调用封装
│   ├── config.py           #   统一路径配置
│   ├── action_log.py       #   行动记录
│   ├── preferences.py      #   服务订阅偏好
│   ├── preference_learner.py #  偏好学习
│   ├── feedback_tracker.py #   反馈追踪
│   ├── device_preferences.py # 设备控制偏好
│   └── generators/         #   内容生成器
│       ├── daily_brief.py  #   晨间简报
│       ├── meeting_insight.py # 会议洞察
│       ├── intent_tracker.py  # 意图追踪
│       ├── emotion_care.py    # 情绪关怀
│       └── social_insight.py  # 人际洞察
│
├── actions/          # ⚡ 行动执行层 — 监控+分析+规划+集成
│   ├── monitoring/   #   实时监控（股票/外汇/新闻/社区）
│   │   ├── ai_news_radar.py       #   AI 新闻雷达（cron 引用）
│   │   ├── dual_factor_signal.py  #   双因子月度调仓信号
│   │   ├── forex_monitor.py       #   外汇监控（CNY/HKD）
│   │   ├── hk_extended_monitor.py #   港股监控
│   │   ├── xhs_comments.py        #   小红书评论监控
│   │   ├── xhs_competitor_monitor.py # 小红书竞品监控
│   │   └── xialiao_heartbeat.py   #   虾聊社区心跳
│   ├── analysis/     #   数据分析工具（离线运行）
│   │   ├── api_usage_tracker.py   #   API 用量追踪
│   │   ├── api_usage_report.py    #   API 用量报告
│   │   ├── daily_report_analyze.py #  每日报告分析
│   │   ├── daily_report_deep_insight.py # 深度洞察
│   │   └── price_compare_poc.py   #   价格对比 PoC（selenium）
│   ├── planning/     #   智能规划（旧版 pi_* 系列，cron 引用）
│   │   ├── action.py              #   行动层（cron 引用）
│   │   ├── daily_pipeline.py      #   每日管线（cron 引用）
│   │   ├── generate_insights.py   #   洞察生成
│   │   ├── insight_daemon.py      #   洞察推送 daemon
│   │   └── check_notifications.py #   通知检查
│   └── integrations/ #   设备集成
│       └── mijia_lamp.py          #   米家台灯控制（screen 插件依赖）
│
├── screen/           # 🖥  Prism 屏幕系统 — daemon + 插件体系
│   ├── daemon.py           #   主 daemon（调度器）
│   ├── update.py           #   状态更新入口（各 session 调用）
│   ├── display.py          #   渲染引擎
│   ├── plugin_loader.py    #   插件加载器
│   ├── plugins/            #   插件体系
│   │   ├── sensors/        #     感知插件（摄像头等）
│   │   ├── detectors/      #     检测插件（帧差、视觉 AI）
│   │   └── devices/        #     执行插件（SPI 屏幕、台灯）
│   └── ...
│
├── infra/            # 🔧 基础设施 — shell 脚本 + 运维工具
│   ├── gateway_watchdog.sh  #   Gateway 看门狗
│   ├── auto_update.sh       #   自动更新
│   ├── security_healthcheck.py # 安全巡检
│   └── ...
│
├── tools/            # 🛠  工具脚本 — 独立可运行的实用工具
│   └── content_idea_formatter.py # 选题→文案框架格式化
│
└── data/             # ⚠️  仅用于运行时数据（gitignored！）
    # 不要在这里放 .py 脚本！
    # Python 代码放到对应的功能目录
```

## 数据流向

```
外部世界                数据采集              智能理解              服务输出
─────                  ────────              ────────              ────────
录音 API           ──→ sources/audio/    ──→ intelligence/    ──→ services/generators/
摄像头             ──→ sources/camera/       perception.py        daily_brief.py
聊天记录           ──→ sources/chat/         understand.py        meeting_insight.py
股票 API           ──→ sources/stock/        refine.py            intent_tracker.py
新闻/外汇          ──→ actions/monitoring/   weekly_refine.py     emotion_care.py
                                                                  social_insight.py
                                                                       ↓
                                                              services/pipeline.py
                                                                       ↓
                                                              Feishu / Prism / 台灯
```

## 命名约定

| 场景 | 位置 | 说明 |
|------|------|------|
| 新的外部数据源 | `src/sources/<name>/` | 只采集，不分析 |
| 新的分析/理解脚本 | `src/intelligence/` | 处理 sources 数据 |
| 新的服务/推送 | `src/services/generators/` | 继承现有 pipeline |
| 实时监控脚本 | `src/actions/monitoring/` | 可被 cron 直接调用 |
| 设备控制脚本 | `src/actions/integrations/` 或 `src/screen/plugins/devices/` | |
| 独立实用工具 | `src/tools/` | 不依赖 src.services 的工具 |
| Shell 脚本/运维 | `src/infra/` | 系统级运维 |

## 注意事项

1. **`src/data/` 是 gitignored 的运行时目录**，不要在这里放代码
2. **`src/actions/planning/` 里的旧版 pi_* 脚本被 cron 引用**，不要移动它们
3. **`src/actions/integrations/mijia_lamp.py` 被 screen 插件依赖**，不要移动
4. `sources/` 负责采集，`intelligence/` 负责理解，职责不混用

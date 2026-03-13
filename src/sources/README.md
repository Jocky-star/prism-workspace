# Sources — 外部数据源

所有外部数据采集的统一入口。每种数据源一个子目录。

## 现有数据源

| 目录 | 数据类型 | 采集方式 |
|------|----------|----------|
| `audio/` | 录音转写数据 | API 拉取（郭宁申 Gemini 转写服务） |
| `camera/` | 摄像头画面 | 通过 sensor 插件采集（默认 rpicam） |
| `stock/` | 股票/财经消息 | 东方财富 JSONP API |

## 如何接入新数据源

1. 在 `src/sources/` 下创建新子目录，比如 `src/sources/wearable/`
2. 写采集脚本，输出标准化 JSON/JSONL 到 `memory/intelligence/` 或 `memory/` 下
3. 在 `__init__.py` 中暴露主要函数（可选）
4. 配置 cron 定时采集，或在 daemon 中集成
5. 更新 SKILL.md 的命令列表

## sensor 插件架构 vs sources 目录

`sources/camera/` 存放的是历史摄像头图像和分析结果（属于数据层），而图像的**实时采集**
已迁移到 `src/screen/plugins/sensors/` 的插件体系中统一管理。

两者关系：

```
src/screen/plugins/sensors/rpicam.py   ← 负责实时拍摄（sensor 插件）
         ↓
src/sources/camera/                    ← 存放原始图像（数据层，可选）
         ↓
src/intelligence/                      ← 感知/理解/精炼
```

如果你只关心数据分析，直接读 `sources/camera/` 即可，无需了解 sensor 插件。
如果你想换摄像头硬件或接入其他图像来源，修改/新增 sensor 插件，sources 目录不需要动。

## 数据流向

```
sources/          采集原始数据
    ↓
intelligence/     感知 → 理解 → 精炼 → 行动
    ↓
screen/           推送到屏幕/飞书
```

## 设计原则

- 每个数据源独立运行，互不依赖
- 采集脚本只负责拿数据 + 格式化，不做分析
- 分析和理解交给 intelligence/ 层
- 新数据源不需要改 intelligence/ 的代码，只要输出格式兼容

# Prism — 理解用户，主动服务

从多数据源理解用户（录音/对话/摄像头/行为），生成个性化服务（晨间 Brief/意图追踪/情绪关怀/设备控制）。

## 什么时候使用

- 需要生成用户的晨间简报、会议洞察、意图追踪
- 需要从对话/录音中提取用户偏好并自动执行（如控制台灯）
- 需要运行智能理解管线（感知→理解→服务）
- 需要查询用户画像、行为模式、社交关系
- 需要控制 Prism 屏幕显示或米家设备

## 快速开始

```bash
# 1. 看看有什么数据源可用
python3 src/services/data_sources.py --discover

# 2. 跑一次管线（dry-run 不调 LLM）
python3 src/services/pipeline.py --dry-run

# 3. 生成晨间 Brief（用昨天的数据）
python3 src/services/generators/daily_brief.py --date 2026-03-12 --format
```

## LLM 配置

```bash
# 方式一：环境变量
export LLM_BASE_URL=https://your-api-endpoint/v1
export LLM_API_KEY=your-api-key

# 方式二：自动读取 ~/.openclaw/agents/main/agent/models.json 中的 litellm provider
```

## 初始化定时任务

```bash
# 一键安装所有 cron（晨间Brief / 每日管线 / 每周洞察）
bash setup_crons.sh
```

安装后自动生效：
- **每天 8:30** — 晨间 Brief 推送给用户
- **每天 23:40** — 跑 daily pipeline（会议/意图/情绪）
- **每周日 21:00** — 人际洞察推送

## 核心命令

### 服务系统

```bash
# 数据源发现
python3 src/services/data_sources.py --discover

# 完整管线（daily + morning + weekly）
python3 src/services/pipeline.py --date YYYY-MM-DD
python3 src/services/pipeline.py --date YYYY-MM-DD --dry-run

# 单独跑某条管线
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline daily
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline morning
python3 src/services/pipeline.py --date YYYY-MM-DD --pipeline weekly

# 查看服务偏好
python3 src/services/pipeline.py --check-prefs
```

### 服务生成器（单独调用）

```bash
# 晨间 Brief — 给结果不给建议
python3 src/services/generators/daily_brief.py --date YYYY-MM-DD --format

# 会议洞察 — 分歧/决策/行动项
python3 src/services/generators/meeting_insight.py --date YYYY-MM-DD

# 意图追踪 — wish/todo/idea/plan/preference 自动分类
python3 src/services/generators/intent_tracker.py --date YYYY-MM-DD

# 情绪关怀 — 多信号叠加检测
python3 src/services/generators/emotion_care.py --date YYYY-MM-DD

# 人际洞察 — 本周社交动态
python3 src/services/generators/social_insight.py --date YYYY-MM-DD
```

### 设备偏好（对话→设备控制）

```bash
# 查看当前规则
python3 src/services/device_preferences.py --list

# 手动添加（通常由 intent_tracker 自动处理）
python3 src/services/device_preferences.py --add-lamp "13" "off" "午休不开灯"

# 删除规则
python3 src/services/device_preferences.py --remove-lamp "13"
```

用户说"中午13到14点不开灯"时，intent_tracker 会自动：
1. LLM 分类为 preference（置信度 95%）
2. 解析为结构化规则 → 写入 device_preferences.json
3. 如果当前在时间范围内 → 立即执行台灯关闭
4. 之后 daemon 每次检测时自动按偏好执行

### 智能理解层

```bash
# 感知：从录音数据提取实体/事件/意图
python3 src/intelligence/perception.py --date YYYYMMDD

# 理解：生成用户画像/社交图谱/行为模式
python3 src/intelligence/understand.py

# 每周精炼：人物合并/关系精判/价值观提取
python3 src/intelligence/weekly_refine.py

# 冷启动：批量处理历史数据
python3 src/intelligence/bootstrap.py
```

### Prism 屏幕（需树莓派 + SPI 屏幕）

```bash
# 更新当前任务
python3 src/screen/update.py --task "正在做的事"

# 标记完成
python3 src/screen/update.py --done "做完的事"

# 添加提醒
python3 src/screen/update.py --note "提醒内容"

# 事件闪屏（alert=红/info=蓝/done=绿）
python3 src/screen/event.py --type info --text "有新消息"
```

### 米家台灯

```bash
# 查看状态
python3 -c "
import sys; sys.path.insert(0, 'src/actions/integrations')
from mijia_lamp import get_status
print(get_status())
"

# 手动切换场景
python3 -c "
import sys; sys.path.insert(0, 'src/actions/integrations')
from mijia_lamp import set_scene
set_scene('focus')   # focus/normal/relax/night/off
"
```

## 数据源

系统自动发现可用数据源，缺少的会优雅跳过：

| 数据源 | 路径 | 说明 |
|--------|------|------|
| audio | skills/audio-daily-insight/raw_json/ | 录音转写 JSON（mf_scene_v2.x） |
| chat | memory/intelligence/chat_messages.jsonl | 对话记录 |
| vision | memory/visual/YYYY-MM-DD.jsonl | 摄像头观察 |
| habit | memory/habits/behavior_rules.json | 行为预测 |
| weather | memory/weather.json | 天气 |
| memory | memory/YYYY-MM-DD.md | 每日记忆 |

### 新增数据源

继承 `DataSource` 类，实现 `get_today_data()` 和 `is_available()`，加到 `ALL_SOURCES` 列表：

```python
# src/services/data_sources.py

class MyDataSource(DataSource):
    name = "mydata"
    description = "我的数据"
    
    def is_available(self) -> bool:
        return Path("my_data.json").exists()
    
    def get_today_data(self, date: str) -> Dict[str, Any]:
        # 读取并返回数据...

ALL_SOURCES.append(MyDataSource)
```

## 文件结构

```
src/services/          # 服务闭环系统（核心）
src/intelligence/      # 智能理解层
src/actions/           # 执行层（规划/监控/设备）
src/screen/            # Prism 屏幕（需硬件）
src/infra/             # 基础设施

memory/                # 数据存储
memory/intelligence/   # 理解层输出
memory/services/       # 服务生成输出
memory/visual/         # 摄像头记录
memory/habits/         # 行为数据
```

## 注意事项

- 所有脚本从项目根目录运行：`python3 src/services/xxx.py`
- LLM 默认用 Haiku（便宜快速），可通过 `LLM_MODEL` 环境变量覆盖
- 路径通过 `WORKSPACE` 环境变量自动检测，不硬编码
- `--dry-run` 参数可在不调 LLM 的情况下验证数据流
- `--format` 参数输出人类可读的格式化文本

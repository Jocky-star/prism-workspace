# Prism — 理解用户，主动服务

从多数据源理解用户（录音/对话/摄像头/行为），生成个性化服务（晨间 Brief/意图追踪/情绪关怀/设备控制）。

## 首次安装（Agent 执行）

如果是全新安装，按以下步骤操作：

```bash
# 1. clone 项目
git clone https://github.com/Jocky-star/prism-workspace.git
cd prism-workspace

# 2. 初始化配置
python3 main.py setup
# → 会自动复制 config.example.yaml → config.yaml
# → 告知需要填写的字段

# 3. 编辑 config.yaml，填入飞书和 LLM 配置

# 4. 验证配置
python3 main.py status

# 5. 预览第一份 Brief
python3 main.py brief --dry-run
```

## 进阶配置

基础 Brief 跑通后，引导用户配置更多功能：

### 数据源

```bash
# 查看配置引导
python3 main.py guide
```

引导用户提供：
- 录音转写 API 地址和 Key（如有）
- 股票关注列表（如需）
- 摄像头/米家/屏幕 等硬件配置（如有）

### 定时任务

```bash
python3 main.py cron-setup
```

自动设置所有定时任务，无需手动编辑 crontab。
幂等操作，重复运行不会重复添加。

---

## 什么时候使用（已安装后）

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

屏幕是一个 **device 插件**（`spi_screen.py`），和台灯平等。不需要屏幕的用户在 `prism_config.yaml` 里不配 `spi_screen` 就行，daemon 不会报错。

**默认零配置**：启动 daemon 后，屏幕会自动监听 OpenClaw gateway 的 session 活动，推断并显示当前状态。不需要手动调用任何命令。

**想手动控制？** 手动设置后 5 分钟内不会被自动推断覆盖：

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

**也可以直接写文件**（任何语言/脚本都行）：
```bash
echo '{"current_task": "我的任务", "auto_inferred": false}' > memory/prism_state.json
```

详细协议见 [STATE_PROTOCOL.md](src/screen/STATE_PROTOCOL.md)。

### 存在检测 + 设备联动（全插件化）

daemon 是**纯调度器**，不知道有什么摄像头、什么检测算法、什么设备。三层管线全部通过 `prism_config.yaml` 配置：

```yaml
# prism_config.yaml — 三层管线配置

# 感知层：怎么拍照
sensors:
  - plugin: rpicam           # 内置：树莓派摄像头
    enabled: true
    config:
      rotation: 180          # 摄像头旋转角度
      width: 640
      height: 480
  # - plugin: usb_camera     # 换 USB 摄像头？写个插件注册就行

# 检测层：怎么判断有没有人
detectors:
  - plugin: frame_diff       # 内置：帧差预筛（零成本，毫秒级）
    enabled: true
    config:
      threshold: 0.005
      skip_vision_below: 0.005  # 帧差极低时跳过 Vision API
  - plugin: vision_api       # 内置：LLM Vision 检测（准但贵）
    enabled: true
    config:
      scene: "办公桌前"       # 改成你的场景描述
  # - plugin: local_yolo     # 不想花 API 钱？写个本地检测器

# 执行层：检测到人/没人后做什么
devices:
  - plugin: spi_screen       # 内置：SPI 屏幕（有人显示状态板，无人暗屏）
    enabled: true
    config:
      fb_path: "/dev/fb0"
      display_interval: 10
  - plugin: mijia_lamp       # 内置：米家台灯（有人开灯，无人关灯）
    enabled: true
  # - plugin: homeassistant  # 用 HA 的？写个插件
  # - plugin: yeelight       # Yeelight 台灯？写个插件

# 存在判定参数
presence:
  scene: "办公桌前"
  absent_timeout: 300        # 5 分钟没检测到人算离开
  camera_interval: 30        # 每 30 秒检测一次
```

**没有摄像头？** 去掉 sensors 和 detectors，只保留 devices — 屏幕照常显示。
**没有屏幕？** devices 里不配 spi_screen 就行。
**没有台灯？** 不配 mijia_lamp 就行。
**什么硬件都没有？** 不需要 prism_config.yaml，只用服务系统就行。

#### 写新的感知插件（Sensor）

```python
# src/screen/plugins/sensors/your_camera.py
from .. import SensorPlugin

class Plugin(SensorPlugin):
    def capture(self) -> "PIL.Image.Image | None":
        # 拍一张照片，返回 PIL Image
        pass
```

配置注册 → 重启 daemon 生效。

#### 写新的检测插件（Detector）

```python
# src/screen/plugins/detectors/your_detector.py
from .. import DetectorPlugin

class Plugin(DetectorPlugin):
    def detect(self, image, context: dict) -> dict:
        # 输入图片，返回 {"detected": bool, "confidence": float, "skip": bool}
        pass
```

检测器按配置顺序执行。上一个返回 `skip=True` 时后续检测器跳过。

#### 写新的执行插件（Device）

```python
# src/screen/plugins/devices/your_device.py
from .. import DevicePlugin

class Plugin(DevicePlugin):
    def on_init(self):
        # daemon 启动时调用（可选，屏幕在这里启动显示线程）
        pass
    
    def on_present(self, hour: int):
        # 有人来了
        pass
    
    def on_absent(self):
        # 人走了
        pass
```

配置注册 → 重启 daemon 生效。示例见 `src/screen/plugins/` 目录。

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

# Prism 硬件升级方案 — SSD 扩容 + 旋钮控制

更新时间：2026-03-12

---

## 一、SSD 扩容方案

### 当前状况
- SD 卡 29G，已用 76%（剩 ~7G）
- 摄像头照片、日志、模型数据持续增长
- SD 卡 IO 性能瓶颈

### 方案对比

| 方案 | 接口 | 速度 | 价格 | 安装难度 | 与 SPI 屏兼容 |
|------|------|------|------|----------|---------------|
| **A. 官方 M.2 HAT+** | PCIe 2.0 x1 | ~450MB/s | HAT ¥80-100 + SSD ¥150-250 | 中 | ✅ 底部安装，不冲突 |
| **B. Geekworm X1001** | PCIe M.2 | ~450MB/s | ¥60-80 + SSD | 中 | ✅ 底部安装 |
| **C. USB 3.0 外接盒** | USB 3.0 | ~350MB/s | 盒 ¥30-50 + SSD | 低 | ✅ 完全不占 GPIO |
| **D. Pimoroni NVMe Base** | PCIe M.2 | ~450MB/s | ¥100-120 + SSD | 中 | ✅ 底部安装 |

### SSD 推荐型号
- **256GB**（够用）：西数 SN580 / 致态 TiPlus 5000 ¥130-160
- **512GB**（充裕）：三星 980 / 致态 TiPlus 7100 ¥200-280
- 注意：必须是 **M.2 2230 或 2242** 尺寸（Pi 5 HAT 支持的）

### 推荐方案：A. 官方 M.2 HAT+ + 致态 256G

**理由**：
- 官方出品，驱动兼容性最好，Pi OS 原生支持
- PCIe 直连，比 USB 快 30%
- 底部安装，MHS35 屏在顶部，物理不冲突
- 总预算 ¥250-350

**安装为数据盘（推荐）**：
1. 装好 HAT，插 SSD
2. `sudo fdisk /dev/nvme0n1` 分区
3. `sudo mkfs.ext4 /dev/nvme0n1p1`
4. 挂载到 `/data`，把 workspace/memory、照片、日志 symlink 过去
5. fstab 写开机自动挂载
6. SD 卡继续做系统盘（稳定，SSD 坏了不影响启动）

**安装为系统盘（进阶）**：
- 用 `rpi-imager` 直接烧到 NVMe
- 改 EEPROM boot order：`sudo rpi-eeprom-config --edit`，设 `BOOT_ORDER=0xf416`
- 优点：全面提速；缺点：SSD 故障无法启动

### GPIO 不冲突说明
M.2 HAT+ 通过底部 FPC 排线连接 Pi 5 的 PCIe 接口，**不占用任何 GPIO pin**。MHS35 用的 SPI0 + GPIO 7/8/9/10/11/24/25 完全不受影响。

---

## 二、旋钮控制方案

### 方案对比

| 方案 | 类型 | 功能 | 价格 | GPIO 占用 |
|------|------|------|------|-----------|
| **A. EC11 旋转编码器** | 机械旋钮 | 旋转+按压 | ¥3-8 | 3 pin (CLK/DT/SW) |
| **B. KY-040 编码器模块** | 带板编码器 | 旋转+按压，带上拉电阻 | ¥5-10 | 3 pin |
| **C. 3按钮组** | 轻触按钮 | 上/下/确认 | ¥2-5 | 3 pin |
| **D. RGB 旋钮 (SparkFun)** | 带灯编码器 | 旋转+按压+RGB | ¥40-60 | 3pin + I2C |

### 推荐方案：B. KY-040 编码器模块

**理由**：
- 集成上拉电阻，接线最简单
- 旋转切模式（状态板/便签/暗屏/天气），按下确认/关灯
- 淘宝/京东 ¥5-10，随处可买
- 有现成 Python 库 `RPi.GPIO` 或 `gpiozero`

### GPIO 分配

**MHS35 已占用**：
| Pin | GPIO | 用途 |
|-----|------|------|
| 19 | GPIO 10 | SPI MOSI |
| 21 | GPIO 9 | SPI MISO |
| 23 | GPIO 11 | SPI SCLK |
| 24 | GPIO 8 | SPI CE0 |
| 26 | GPIO 7 | SPI CE1 |
| 22 | GPIO 25 | DC |
| 18 | GPIO 24 | RST |
| 28 | GPIO 1 | Touch IRQ |

**旋钮新增**（选空闲 GPIO）：
| Pin | GPIO | 用途 |
|-----|------|------|
| 29 | GPIO 5 | 编码器 CLK |
| 31 | GPIO 6 | 编码器 DT |
| 33 | GPIO 13 | 编码器 SW（按键） |
| 34 | GND | 公共地 |

### 代码实现思路

```python
# prism_knob.py — 旋钮事件监听
from gpiozero import RotaryEncoder, Button
import subprocess

encoder = RotaryEncoder(5, 6, max_steps=0)  # CLK=GPIO5, DT=GPIO6
button = Button(13, bounce_time=0.1)         # SW=GPIO13

MODES = ["normal", "summary", "dim", "weather"]
current_mode = 0

def on_rotate(direction):
    global current_mode
    if direction > 0:
        current_mode = (current_mode + 1) % len(MODES)
    else:
        current_mode = (current_mode - 1) % len(MODES)
    # 通知 daemon 切换模式
    ...

def on_press():
    # 确认/关灯/清除通知
    ...

encoder.when_rotated = on_rotate
button.when_pressed = on_press
```

---

## 三、采购清单

| 物品 | 参考价 | 购买渠道 |
|------|--------|----------|
| 官方 Pi 5 M.2 HAT+ | ¥80-100 | 淘宝搜"树莓派5 M.2 HAT" |
| 致态 TiPlus 5000 256G (2242) | ¥130-160 | 京东 |
| KY-040 旋转编码器模块 | ¥5-10 | 淘宝 |
| 杜邦线母对母 x4 | ¥2 | 淘宝 |
| **总计** | **¥220-270** | |

---

## 四、下一步行动

1. **饭团确认方案** → 下单采购（到货约 2-3 天）
2. **SSD 到货后**：
   - 安装 HAT，格式化 SSD
   - 挂载 /data，迁移照片/日志/模型
   - 验证读写速度
3. **旋钮到货后**：
   - 接线（GPIO 5/6/13 + GND）
   - 写 `prism_knob.py` 监听脚本
   - 集成到 daemon，支持手动切换模式
4. **后续**：3D 打印/亚克力外壳，把旋钮固定在合适位置

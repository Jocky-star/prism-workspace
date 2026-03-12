# Gateway 可靠性方案

## 现状问题

### 1. 两套 service 同时存在（定时炸弹💣）
- `/etc/systemd/system/openclaw-gateway.service`（system-level）→ enabled + active
- `~/.config/systemd/user/openclaw-gateway.service`（user-level）→ enabled + active
- 目前碰巧只有 user-level 的进程在跑（pid 13181），但 **重启后两个都会启动**，抢端口冲突！

### 2. user-level service 没有 bind lan
- ExecStart: `openclaw gateway --port 18789`（默认 loopback）
- system-level: `openclaw gateway run --bind lan --port 18789`
- 实际端口绑定在 `127.0.0.1`（只有本地能访问）

### 3. 无 watchdog / 健康检查
- `Restart=always` 只管进程退出重启
- 进程活着但假死（比如 Node.js event loop 卡住）→ 不会触发重启

### 4. node service 也在跑（残留）
- `openclaw-node.service` still active，连 Mac Gateway
- 但树莓派已改为独立 Gateway 模式，node service 应该停掉

---

## 修复方案

### 第一步：清理冲突（立即执行）

```bash
# 1. 停掉 system-level service（保留 user-level）
sudo systemctl stop openclaw-gateway.service
sudo systemctl disable openclaw-gateway.service

# 2. 停掉残留的 node service
systemctl --user stop openclaw-node.service
systemctl --user disable openclaw-node.service

# 3. 确认只剩 user-level gateway
systemctl --user status openclaw-gateway.service
```

**为什么保留 user-level？** 因为 `openclaw gateway install` 生成的就是 user-level，跟 OpenClaw 升级流程一致。linger=yes 已配好，开机自启没问题。

### 第二步：修复 user-level service（加 bind + watchdog）

```ini
[Unit]
Description=OpenClaw Gateway (v2026.3.2)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/node /usr/lib/node_modules/openclaw/dist/index.js gateway --port 18789 --bind lan
Restart=always
RestartSec=5
KillMode=process
WatchdogSec=120
Environment=HOME=/home/mi
Environment=PATH=/home/mi/.local/bin:/usr/bin:/usr/local/bin:/bin
Environment=NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
Environment=OPENCLAW_NO_RESPAWN=1
Environment=OPENCLAW_SERVICE_KIND=gateway
Environment=OPENCLAW_SYSTEMD_UNIT=openclaw-gateway

[Install]
WantedBy=default.target
```

变更点：
- `--bind lan`：对外可访问
- `WatchdogSec=120`：如果 120 秒内进程没有发 sd_notify，systemd 杀掉重启（需要 OpenClaw 支持 sd_notify，如不支持则删掉这行）

### 第三步：外部健康检查脚本

不依赖 systemd watchdog，自己写一个独立的健康检查 + 自动恢复：

```bash
#!/bin/bash
# /home/mi/.openclaw/workspace/src/infra/gateway_watchdog.sh
# cron: */2 * * * * （每2分钟跑一次）

LOG="/home/mi/.openclaw/workspace/logs/watchdog.log"
mkdir -p "$(dirname "$LOG")"

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 检查1: 进程存在
if ! pgrep -f "openclaw.*gateway" > /dev/null; then
    echo "$TIMESTAMP [ALERT] Gateway process not found, restarting..." >> "$LOG"
    systemctl --user restart openclaw-gateway.service
    sleep 10
    if pgrep -f "openclaw.*gateway" > /dev/null; then
        echo "$TIMESTAMP [OK] Gateway restarted successfully" >> "$LOG"
    else
        echo "$TIMESTAMP [CRITICAL] Gateway restart FAILED" >> "$LOG"
    fi
    exit 0
fi

# 检查2: 端口监听
if ! ss -tlnp | grep -q ":18789"; then
    echo "$TIMESTAMP [ALERT] Port 18789 not listening, restarting..." >> "$LOG"
    systemctl --user restart openclaw-gateway.service
    sleep 10
    echo "$TIMESTAMP [RESTARTED] After port check failure" >> "$LOG"
    exit 0
fi

# 检查3: HTTP 健康响应（RPC）
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:18789/ 2>/dev/null)
if [ "$HTTP_CODE" = "000" ] || [ -z "$HTTP_CODE" ]; then
    echo "$TIMESTAMP [ALERT] Gateway not responding (HTTP=$HTTP_CODE), restarting..." >> "$LOG"
    systemctl --user restart openclaw-gateway.service
    sleep 10
    echo "$TIMESTAMP [RESTARTED] After HTTP check failure" >> "$LOG"
    exit 0
fi

# 一切正常，静默
```

### 第四步：用系统 crontab 而不是 OpenClaw cron

关键点：**watchdog 不能靠 OpenClaw cron 跑！** Gateway 挂了 cron 也跑不了。

```bash
# 用系统 crontab
crontab -e
# 添加：
*/2 * * * * /home/mi/.openclaw/workspace/src/infra/gateway_watchdog.sh
```

### 第五步：开机启动验证链

开机后的启动顺序：
1. systemd 启动 → user-level `openclaw-gateway.service`（linger=yes 保证 user session 开机就启动）
2. 2 分钟后 → crontab watchdog 首次检查
3. 如果 service 启动失败 → watchdog 检测到无进程/端口 → `systemctl --user restart`
4. 如果仍然失败 → watchdog 日志记录 CRITICAL

### 第六步：重启前的安全检查清单

**在执行任何可能导致 Gateway 重启的操作前，必须确认：**

1. ✅ systemd service 文件语法正确：`systemd-analyze verify ~/.config/systemd/user/openclaw-gateway.service`
2. ✅ ExecStart 路径存在：`ls -la /usr/bin/node /usr/lib/node_modules/openclaw/dist/index.js`
3. ✅ 配置文件有效：`openclaw doctor`
4. ✅ 端口未被占用：`ss -tlnp | grep 18789`（如果要重启，先确认不会冲突）
5. ✅ watchdog cron 已安装：`crontab -l | grep watchdog`

**重启操作的标准流程：**
```bash
# 永远不要直接 kill，用 systemctl
systemctl --user restart openclaw-gateway.service

# 等 15 秒确认
sleep 15
systemctl --user status openclaw-gateway.service
ss -tlnp | grep 18789
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18789/
```

---

## 防护层级总结

| 层 | 机制 | 防什么 |
|---|---|---|
| L0 | systemd `Restart=always` | 进程崩溃自动重启 |
| L1 | crontab watchdog（每2分钟） | 进程假死/端口丢失/HTTP不响应 |
| L2 | linger=yes + enabled | 开机自启 |
| L3 | 只保留一套 service | 防端口冲突 |
| L4 | 重启前检查清单 | 防人为操作失误 |
| L5 | watchdog 日志 | 事后排查 |

---

## Agent 行为规则（写入 AGENTS.md）

### Gateway 操作红线
1. **永远不要在 session 中执行 `openclaw gateway restart`** — 会断掉自己的连接，无法确认结果
2. **需要重启时，走 systemctl** — `systemctl --user restart openclaw-gateway.service`，systemd 会管好进程生命周期
3. **重启前必须跑安全检查清单**（见第六步）
4. **不要同时启动两个 Gateway 进程** — 端口冲突 = 全挂
5. **任何 service 文件修改后**：`systemctl --user daemon-reload` → verify → restart
6. **升级 OpenClaw 后**：`openclaw gateway install --force` 重新生成 service 文件，然后 `systemctl --user daemon-reload && systemctl --user restart openclaw-gateway.service`

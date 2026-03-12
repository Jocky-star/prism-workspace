#!/usr/bin/env python3
"""
security_healthcheck.py - 树莓派安全巡检
纯 Python，不需要 pip install
"""

import json
import os
import subprocess
import sys
from datetime import datetime


def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""


def check_disk():
    lines = run_cmd("df -h --output=target,pcent,size,used,avail -x tmpfs -x devtmpfs").split("\n")[1:]
    disks = []
    alerts = []
    for l in lines:
        parts = l.split()
        if len(parts) >= 5:
            mount, pct = parts[0], parts[1].replace("%", "")
            d = {"mount": mount, "usage_pct": int(pct), "size": parts[2], "used": parts[3], "avail": parts[4]}
            disks.append(d)
            if int(pct) > 80:
                alerts.append(f"磁盘 {mount} 使用率 {pct}%")
    return disks, alerts


def check_memory():
    info = {}
    out = run_cmd("free -m")
    lines = out.split("\n")
    for l in lines:
        if l.startswith("Mem:"):
            parts = l.split()
            info = {"total_mb": int(parts[1]), "used_mb": int(parts[2]), "free_mb": int(parts[3]), "available_mb": int(parts[6])}
    alerts = []
    if info.get("total_mb", 0) > 0:
        pct = info["used_mb"] / info["total_mb"] * 100
        info["usage_pct"] = round(pct, 1)
        if pct > 90:
            alerts.append(f"内存使用率 {pct:.0f}%")
    return info, alerts


def check_cpu_temp():
    temp_str = run_cmd("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    alerts = []
    try:
        temp = int(temp_str) / 1000
    except:
        temp = -1
    if temp > 70:
        alerts.append(f"CPU 温度 {temp}°C 过高")
    return round(temp, 1), alerts


def check_load():
    out = run_cmd("cat /proc/loadavg")
    parts = out.split()
    load = {"1min": float(parts[0]), "5min": float(parts[1]), "15min": float(parts[2])}
    cpus = os.cpu_count() or 4
    alerts = []
    if load["1min"] > cpus * 2:
        alerts.append(f"系统负载过高 {load['1min']} (CPU核数 {cpus})")
    return load, alerts


def check_failed_logins():
    out = run_cmd("grep 'Failed password' /var/log/auth.log 2>/dev/null | tail -10")
    lines = [l.strip() for l in out.split("\n") if l.strip()]
    count = len(lines)
    alerts = []
    if count >= 5:
        alerts.append(f"最近 {count} 次 SSH 登录失败尝试")
    return {"count": count, "recent": lines[-3:]}, alerts


def check_ssh_config():
    # 读取主配置 + config.d 下所有文件（后者优先级更高）
    cfg = run_cmd("cat /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null")
    root_login = "unknown"
    password_auth = "unknown"
    for l in cfg.split("\n"):
        l = l.strip()
        if l.startswith("#"):
            continue
        if l.startswith("PermitRootLogin"):
            root_login = l.split()[-1]
        if l.startswith("PasswordAuthentication"):
            password_auth = l.split()[-1]
    alerts = []
    if root_login not in ("no", "prohibit-password"):
        alerts.append(f"SSH root 登录未禁用 ({root_login})")
    if password_auth not in ("no",):
        alerts.append(f"SSH 密码认证未禁用 ({password_auth})")
    return {"root_login": root_login, "password_auth": password_auth}, alerts


def check_updates():
    count = run_cmd("apt list --upgradable 2>/dev/null | grep -c upgradable || echo 0")
    try:
        n = int(count)
    except:
        n = 0
    alerts = []
    if n > 20:
        alerts.append(f"有 {n} 个系统更新待安装")
    return n, alerts


def check_openclaw():
    status = run_cmd("systemctl is-active openclaw-node.service 2>/dev/null") or "unknown"
    alerts = []
    if status != "active":
        alerts.append(f"OpenClaw 服务状态异常: {status}")
    version = run_cmd("openclaw --version 2>/dev/null") or "unknown"
    return {"status": status, "version": version}, alerts


def check_top_processes():
    out = run_cmd("ps aux --sort=-%mem | head -6")
    procs = []
    for l in out.split("\n")[1:]:
        parts = l.split(None, 10)
        if len(parts) >= 11:
            procs.append({"user": parts[0], "cpu": parts[2], "mem": parts[3], "cmd": parts[10][:60]})
    return procs, []


def check_network():
    out = run_cmd("ss -tunp | grep ESTAB | grep -v '127.0.0.1' | head -10")
    conns = len([l for l in out.split("\n") if l.strip()])
    return {"established_external": conns}, []


def run_all():
    all_alerts = []
    disk, a = check_disk(); all_alerts.extend(a)
    mem, a = check_memory(); all_alerts.extend(a)
    temp, a = check_cpu_temp(); all_alerts.extend(a)
    load, a = check_load(); all_alerts.extend(a)
    logins, a = check_failed_logins(); all_alerts.extend(a)
    ssh, a = check_ssh_config(); all_alerts.extend(a)
    updates, a = check_updates(); all_alerts.extend(a)
    oc, a = check_openclaw(); all_alerts.extend(a)
    procs, a = check_top_processes(); all_alerts.extend(a)
    net, a = check_network(); all_alerts.extend(a)

    status = "healthy"
    if len(all_alerts) > 0:
        status = "warning"
    if any("过高" in a or "异常" in a for a in all_alerts):
        status = "critical"

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "hostname": run_cmd("hostname"),
        "status": status,
        "alerts": all_alerts,
        "details": {
            "disk": disk, "memory": mem, "cpu_temp_c": temp, "load": load,
            "failed_logins": logins, "ssh_config": ssh, "updates_available": updates,
            "openclaw": oc, "top_processes": procs, "network": net,
        }
    }


def human_output(data):
    status_icon = {"healthy": "✅", "warning": "⚠️", "critical": "🔴"}.get(data["status"], "❓")
    print(f"{'='*45}")
    print(f"  🛡️ 树莓派安全巡检  |  {status_icon} {data['status'].upper()}")
    print(f"  {data['timestamp']}")
    print(f"{'='*45}")
    d = data["details"]
    print(f"\n  🌡️ CPU 温度: {d['cpu_temp_c']}°C")
    print(f"  📊 负载: {d['load']['1min']}/{d['load']['5min']}/{d['load']['15min']}")
    m = d["memory"]
    print(f"  🧠 内存: {m.get('used_mb',0)}MB / {m.get('total_mb',0)}MB ({m.get('usage_pct',0)}%)")
    for disk in d["disk"]:
        print(f"  💾 {disk['mount']}: {disk['usage_pct']}% ({disk['used']}/{disk['size']})")
    print(f"  🔐 SSH: root={d['ssh_config']['root_login']}, 密码={d['ssh_config']['password_auth']}")
    print(f"  🔑 登录失败: {d['failed_logins']['count']} 次")
    print(f"  📦 可用更新: {d['updates_available']} 个")
    oc = d["openclaw"]
    print(f"  🦞 OpenClaw: {oc['status']} ({oc['version']})")
    print(f"  🌐 外部连接: {d['network']['established_external']} 个")
    if data["alerts"]:
        print(f"\n  ⚠️ 告警 ({len(data['alerts'])}):")
        for a in data["alerts"]:
            print(f"    • {a}")
    else:
        print(f"\n  ✅ 无告警，一切正常")
    print(f"{'='*45}")


if __name__ == "__main__":
    data = run_all()
    if "--human" in sys.argv:
        human_output(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))

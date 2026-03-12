"""Prism 米家联动模块 — 摄像头感知 → 台灯控制"""

import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("prism.mijia")

_tz = timezone(timedelta(hours=8))

def on_presence_change(present: bool):
    """摄像头检测到存在状态变化时调用"""
    from mijia_lamp import set_scene, determine_scene
    
    hour = datetime.now(_tz).hour
    scene = determine_scene(present, hour)
    
    log.info(f"存在状态变化 → {'有人' if present else '无人'}, 时段={hour}:00, 场景={scene}")
    
    success = set_scene(scene)
    if success:
        log.info(f"台灯已切换: {scene}")
    else:
        log.warning(f"台灯切换失败: {scene}")

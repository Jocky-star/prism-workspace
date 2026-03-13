"""米家台灯控制模块 — Prism 环境编排的第一个执行器"""

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("prism.lamp")

DID = "941551405"  # 台灯 did
# 台灯规格: xiaomi.light.lamp31
# siid=2 Light服务: piid=1 开关, piid=2 亮度(1-100), piid=3 色温(2700-5100)

# 场景预设
SCENES = {
    "focus": {"on": True, "brightness": 100, "color_temp": 5100},   # 专注：冷白高亮
    "normal": {"on": True, "brightness": 80, "color_temp": 3900},   # 日常：中性
    "relax": {"on": True, "brightness": 40, "color_temp": 2700},    # 休息：暖光低亮
    "night": {"on": True, "brightness": 15, "color_temp": 2700},    # 深夜：极暖极暗
    "off": {"on": False},                                            # 离开：关灯
}

_api = None
_last_scene = None
_last_set_time = 0
_last_set_props = {}       # 上次自动设的属性（on/brightness/color_temp）
_manual_override_until = 0  # 手动操作保护截止时间（timestamp）
MIN_INTERVAL = 30           # 同一场景最少间隔30秒，避免频繁调用
MANUAL_PROTECT_SECS = 1800  # 手动保护期30分钟


def _get_api():
    """懒加载 mijiaAPI，避免 import 时就连接"""
    global _api
    if _api is None:
        try:
            from mijiaAPI import mijiaAPI
            _api = mijiaAPI()
            log.info("米家 API 初始化成功")
        except Exception as e:
            log.error(f"米家 API 初始化失败: {e}")
            return None
    return _api


def _check_manual_override() -> bool:
    """检查台灯当前状态是否被手动改过，如果是则进入保护期"""
    global _manual_override_until, _last_set_props
    
    now = time.time()
    
    # 已在保护期内
    if now < _manual_override_until:
        return True
    
    # 没有上次自动设置的记录，无法判断
    if not _last_set_props:
        return False
    
    # 查询当前台灯状态
    current = get_status()
    if not current:
        return False
    
    # 对比：如果跟上次自动设的不一样 → 有人手动调了
    for key in ("on", "brightness", "color_temp"):
        if key in _last_set_props and key in current:
            if _last_set_props[key] != current[key]:
                _manual_override_until = now + MANUAL_PROTECT_SECS
                log.info(f"🖐️ 检测到手动操作（{key}: {_last_set_props[key]}→{current[key]}），保护 {MANUAL_PROTECT_SECS//60} 分钟")
                return True
    
    return False


def set_scene(scene_name: str, force: bool = False) -> bool:
    """设置台灯场景
    
    Args:
        scene_name: 场景名（focus/normal/relax/night/off）
        force: 强制设置，忽略去重、间隔和手动保护
    
    Returns:
        是否成功
    """
    global _last_scene, _last_set_time, _last_set_props
    
    if scene_name not in SCENES:
        log.warning(f"未知场景: {scene_name}")
        return False
    
    now = time.time()
    
    # 去重：同一场景不重复设置
    if not force and scene_name == _last_scene and (now - _last_set_time) < MIN_INTERVAL:
        return True
    
    # 手动保护：检测到手动操作后 30 分钟内不自动覆盖
    if not force and _check_manual_override():
        remaining = int((_manual_override_until - now) / 60)
        log.info(f"🛡️ 手动保护期内（剩 {remaining} 分钟），跳过自动场景: {scene_name}")
        return True  # 返回 True 不算失败
    
    api = _get_api()
    if api is None:
        return False
    
    scene = SCENES[scene_name]
    props = []
    
    # 构建属性列表
    props.append({"did": DID, "siid": 2, "piid": 1, "value": scene["on"]})
    if scene["on"] and "brightness" in scene:
        props.append({"did": DID, "siid": 2, "piid": 2, "value": scene["brightness"]})
    if scene["on"] and "color_temp" in scene:
        props.append({"did": DID, "siid": 2, "piid": 3, "value": scene["color_temp"]})
    
    try:
        result = api.set_devices_prop(props)
        success = all(item.get("code") == 0 for item in result)
        if success:
            _last_scene = scene_name
            _last_set_time = now
            # 记录本次自动设置的属性，用于后续检测手动操作
            _last_set_props = dict(scene)
            log.info(f"台灯场景切换: {scene_name}")
        else:
            log.warning(f"台灯设置部分失败: {result}")
        return success
    except Exception as e:
        log.error(f"台灯控制异常: {e}")
        return False


def get_status() -> dict:
    """获取台灯当前状态"""
    api = _get_api()
    if api is None:
        return {}
    
    try:
        result = api.get_devices_prop([
            {"did": DID, "siid": 2, "piid": 1},  # 开关
            {"did": DID, "siid": 2, "piid": 2},  # 亮度
            {"did": DID, "siid": 2, "piid": 3},  # 色温
        ])
        status = {}
        for item in result:
            if item["piid"] == 1:
                status["on"] = item.get("value", False)
            elif item["piid"] == 2:
                status["brightness"] = item.get("value", 0)
            elif item["piid"] == 3:
                status["color_temp"] = item.get("value", 0)
        return status
    except Exception as e:
        log.error(f"获取台灯状态失败: {e}")
        return {}


def determine_scene(present: bool, hour: int) -> str:
    """根据在场状态和时间决定场景
    
    优先级：
    1. 用户偏好覆盖（device_preferences.json）
    2. 默认时段逻辑
    
    Args:
        present: 是否在场
        hour: 当前小时(0-23)
    
    Returns:
        场景名
    """
    if not present:
        return "off"
    
    # 1. 检查用户偏好覆盖
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        from src.services.device_preferences import get_lamp_scene_override
        override = get_lamp_scene_override(hour)
        if override is not None:
            log.debug(f"用户偏好覆盖: {hour}:00 → {override}")
            return override
    except Exception:
        pass  # 偏好模块不可用时 fallback 到默认
    
    # 2. 默认时段逻辑
    if 8 <= hour < 12:
        return "focus"      # 上午：专注模式
    elif 12 <= hour < 14:
        return "normal"     # 午间：日常
    elif 14 <= hour < 18:
        return "focus"      # 下午：专注模式
    elif 18 <= hour < 22:
        return "relax"      # 晚间：休息
    else:
        return "night"      # 深夜：极暗

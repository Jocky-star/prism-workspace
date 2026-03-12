#!/usr/bin/env python3
"""
test_transition.py — 测试渐变过渡效果

用法：
  cd /home/mi/.openclaw/workspace/scripts
  python3 test_transition.py
"""
import os
import sys
import time

# 确保 scripts 目录在 path 中
_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

from display import render_frame, render_dim_frame, write_to_framebuffer
from transition import fade_transition, fade_to_black, fade_from_black

print("═" * 50)
print("  Prism 渐变过渡测试")
print("═" * 50)

print("\n[1/4] 渲染正常帧...")
normal = render_frame()
print(f"      正常帧: {normal.size} {normal.mode}")

print("[2/4] 渲染暗屏帧...")
dim = render_dim_frame()
print(f"      暗屏帧: {dim.size} {dim.mode}")

print("\n[3/4] 正常 → 暗屏 渐变（8帧 / 0.5s）...")
t0 = time.monotonic()
fade_transition(normal, dim, "/dev/fb0", steps=8, duration=0.5)
elapsed = time.monotonic() - t0
print(f"      完成，耗时 {elapsed:.2f}s")

print("      停留 2 秒...")
time.sleep(2)

print("\n[4/4] 暗屏 → 正常 渐变（8帧 / 0.5s）...")
t0 = time.monotonic()
fade_transition(dim, normal, "/dev/fb0", steps=8, duration=0.5)
elapsed = time.monotonic() - t0
print(f"      完成，耗时 {elapsed:.2f}s")

print("\n─" * 50)
print("  额外测试：fade_to_black + fade_from_black")
print("─" * 50)
print("\n渐隐到黑（6帧 / 0.3s）...")
fade_to_black(normal, "/dev/fb0", steps=6, duration=0.3)
time.sleep(0.5)

print("从黑渐入（6帧 / 0.3s）...")
fade_from_black(normal, "/dev/fb0", steps=6, duration=0.3)

print("\n✅ 全部测试完成")

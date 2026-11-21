"""生成 assets/app.ico：深色圆角方块 + 橙色 RSS 波纹。"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def draw(size: int) -> Image.Image:
    scale = 4  # 超采样后缩小，边缘更顺
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 背景：竖向渐变 + 圆角（用遮罩实现圆角）
    bg = Image.new("RGBA", (s, s))
    bd = ImageDraw.Draw(bg)
    top, bottom = (32, 36, 44), (17, 19, 24)
    for y in range(s):
        t = y / max(1, s - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) + (255,)
        bd.line([(0, y), (s, y)], fill=color)

    radius = int(s * 0.22)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)
    img.paste(bg, (0, 0), mask)

    accent = (255, 138, 61)
    # RSS 波纹：左下角为圆心，向右上张开的三层圆弧 + 一个圆点
    cx, cy = int(s * 0.26), int(s * 0.74)
    dot_r = int(s * 0.075)
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=accent)
    for i, frac in enumerate((0.20, 0.34, 0.48)):
        r = int(s * frac)
        width = max(2, int(s * 0.055))
        d.arc([cx - r, cy - r, cx + r, cy + r], start=270, end=360, fill=accent, width=width)

    return img.resize((size, size), Image.LANCZOS)


sizes = [16, 24, 32, 48, 64, 128, 256]
frames = [draw(n) for n in sizes]
frames[-1].save(OUT / "app.ico", format="ICO", sizes=[(n, n) for n in sizes])
frames[-1].save(OUT / "app-256.png")
print("wrote", OUT / "app.ico", frames[-1].size)

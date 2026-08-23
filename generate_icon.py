# -*- coding: utf-8 -*-
"""生成 Android 模拟器启动器图标

设计理念：
  - 圆角方形背景：Android 绿渐变（#3DDC84 → #0F9D58）
  - 上方：白色 Android 机器人头部（半圆头 + 天线 + 双眼），代表 Android
  - 下方：白色圆形播放按钮内嵌绿色 ▶ 三角，代表"启动器"
"""
from PIL import Image, ImageDraw


def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def make_icon(size=512):
    SS = 4  # 超采样倍数，用于抗锯齿
    S = size * SS

    # ---- 1. 渐变背景 ----
    c_top = (0x3D, 0xDC, 0x84)   # Android 绿（背景顶部）
    c_bot = (0x0F, 0x9D, 0x58)   # 深绿（背景底部 / 眼睛 / 三角形）
    grad = Image.new('RGB', (1, S))
    for y in range(S):
        grad.putpixel((0, y), lerp(c_top, c_bot, y / (S - 1)))
    grad = grad.resize((S, S))

    # 圆角遮罩
    mask = Image.new('L', (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(100 * SS), fill=255)

    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(img)
    k = SS  # 坐标缩放因子

    # ---- 2. 天线 ----
    aw = int(10 * k)
    # 左天线
    draw.line([(205*k, 165*k), (170*k, 120*k)], fill='white', width=aw)
    draw.ellipse([170*k - aw//2, 120*k - aw//2, 170*k + aw//2, 120*k + aw//2], fill='white')
    # 右天线
    draw.line([(307*k, 165*k), (342*k, 120*k)], fill='white', width=aw)
    draw.ellipse([342*k - aw//2, 120*k - aw//2, 342*k + aw//2, 120*k + aw//2], fill='white')

    # ---- 3. 半圆头（白色）----
    cx, cy, r = 256*k, 250*k, 120*k
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill='white')

    # ---- 4. 眼睛（深绿圆点）----
    er = int(12 * k)
    draw.ellipse([221*k - er, 220*k - er, 221*k + er, 220*k + er], fill=c_bot)
    draw.ellipse([291*k - er, 220*k - er, 291*k + er, 220*k + er], fill=c_bot)

    # ---- 5. 播放按钮圆（白色）----
    pcx, pcy, pr = 256*k, 335*k, 60*k
    draw.ellipse([pcx - pr, pcy - pr, pcx + pr, pcy + pr], fill='white')

    # ---- 6. 播放三角形（深绿）----
    tri = [(234*k, 310*k), (234*k, 360*k), (278*k, 335*k)]
    draw.polygon(tri, fill=c_bot)

    # 缩小到目标尺寸（LANCZOS 抗锯齿）
    return img.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    import os
    out_dir = os.path.dirname(os.path.abspath(__file__))
    icon = make_icon(512)
    icon.save(os.path.join(out_dir, 'icon_512.png'))
    icon.save(
        os.path.join(out_dir, 'app.ico'),
        format='ICO',
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print('图标已生成: app.ico, icon_512.png')

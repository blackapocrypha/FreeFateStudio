# -*- coding: utf-8 -*-
"""从 FreeFateStudio.png 生成 exe 图标 FreeFateStudio.ico。

原图 1254×1254，透明背景，上方是圆形主体标志，下方是「FreeFateStudio」字标。
exe 图标最小要显示到 16×16，字标在那个尺寸下必然糊成一团，所以这里**只取主体标志**：
按 alpha 通道找出标志的包围盒（限定在字标上方），居中放进正方形画布，再导出多尺寸 ICO。

用法：python make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "FreeFateStudio.png"
DST = ROOT / "FreeFateStudio.ico"

# 字标位于图片下方，取主体时把这一带排除掉（按整图高度的比例）
MARK_MAX_Y_RATIO = 0.80
# 标志在正方形画布中的占比，留出图标常见的呼吸边距
MARK_FILL = 0.88
ALPHA_THRESHOLD = 120

SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]


def mark_bbox(img: Image.Image) -> tuple[int, int, int, int]:
    alpha = img.split()[3]
    region = alpha.crop((0, 0, img.width, int(img.height * MARK_MAX_Y_RATIO)))
    mask = region.point(lambda v: 255 if v >= ALPHA_THRESHOLD else 0)
    box = mask.getbbox()
    if box is None:
        raise SystemExit("未能从 FreeFateStudio.png 中找到标志主体")
    return box


def build_master(img: Image.Image) -> Image.Image:
    box = mark_bbox(img)
    mark = img.crop(box)
    side = int(max(mark.size) / MARK_FILL)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(mark, ((side - mark.width) // 2, (side - mark.height) // 2))
    return canvas.resize((1024, 1024), Image.LANCZOS)


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"缺少源图 {SRC.name}")
    src = Image.open(SRC).convert("RGBA")
    master = build_master(src)

    master.save(DST, format="ICO", sizes=SIZES)
    master.resize((256, 256), Image.LANCZOS).save(ROOT / "icon_preview.png")

    print(f"标志包围盒 {mark_bbox(src)}  源图 {src.size}")
    print(f"已生成 {DST.name}（{DST.stat().st_size / 1024:.1f} KB），尺寸 "
          + "、".join(f"{w}×{h}" for w, h in SIZES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

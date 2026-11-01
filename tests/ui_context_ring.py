# -*- coding: utf-8 -*-
"""上下文进度环的渲染自检：不同占用率下的环，以及它在输入框右下角的位置。

不联网、不调模型，只构造窗口并直接喂状态。
用法：python tests/ui_context_ring.py [输出目录]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.context_ring import DIAMETER, ContextRing  # noqa: E402
from app.ui.theme import QSS  # noqa: E402
from app.ui.window import MainWindow  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ffs_ring_"))
OUT.mkdir(parents=True, exist_ok=True)

WINDOW, THRESHOLD = 128_000, 112_000


def snapshot(percent: float) -> dict:
    return {
        "tokens": int(WINDOW * percent / 100),
        "window": WINDOW,
        "threshold": THRESHOLD,
        "threshold_percent": round(THRESHOLD * 100 / WINDOW, 1),
        "reserve": 16_384,
        "keep_recent": 20_000,
        "percent": percent,
        "enabled": True,
        "over": percent > 87.5,
    }


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)

    # ---- 1. 单环放大对比 ----
    cases = [("12%", snapshot(12)), ("55%", snapshot(55)), ("82%", snapshot(82)), ("93%", snapshot(93))]
    scale = 6
    pad = 24
    cell = DIAMETER * scale + pad
    canvas = QPixmap(cell * len(cases), cell)
    canvas.fill(QColor("#FAFAF9"))
    painter = QPainter(canvas)
    for i, (_label, snap) in enumerate(cases):
        ring = ContextRing()
        ring.set_state(snap)
        app.processEvents()
        big = ring.grab().scaled(
            DIAMETER * scale, DIAMETER * scale,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        painter.drawPixmap(i * cell + pad // 2, pad // 2, big)
    painter.end()
    canvas.save(str(OUT / "ring_states.png"))

    # ---- 2. 压缩中（转圈）----
    busy = ContextRing()
    busy.set_state(snapshot(90))
    busy.set_busy(True)
    app.processEvents()
    busy.grab().scaled(DIAMETER * scale, DIAMETER * scale,
                       Qt.KeepAspectRatio, Qt.SmoothTransformation
                       ).save(str(OUT / "ring_busy.png"))

    # ---- 3. 整窗位置 ----
    win = MainWindow("http://127.0.0.1:1", {"model": "deepseek-v4-flash",
                                            "api_key_ready": True,
                                            "profile_ready": True})
    win.resize(1120, 780)
    win.show()
    app.processEvents()
    win.ctx_ring.set_state(snapshot(46))
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)
    win.grab().save(str(OUT / "window_ring.png"))

    print("环中心:", win.ctx_ring.mapTo(win, win.ctx_ring.rect().center()))
    print("输入框右下:", win.composer.mapTo(win, win.composer.rect().bottomRight()))
    print("提示:", win.ctx_ring.toolTip().replace("\n", " | "))
    print("输出目录:", OUT)
    for f in sorted(OUT.glob("*.png")):
        print(" -", f.name, f.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

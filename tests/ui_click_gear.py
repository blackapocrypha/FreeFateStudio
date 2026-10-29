# -*- coding: utf-8 -*-
"""用真实鼠标事件连点左下角齿轮，复现「多次点击后格式错乱」。

QTest 的事件是直接投递给控件的，绕过了 Qt.Popup 的鼠标抓取，
所以必须用系统级鼠标事件才能还原真实交互。
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.server import server  # noqa: E402
from app.ui.theme import QSS  # noqa: E402


def pump(app: QApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def click_at(x: int, y: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.04)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def foreground(win) -> None:
    try:
        user32 = ctypes.windll.user32
        hwnd = int(win.winId())
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception as exc:
        print("置前失败:", exc)


def main() -> int:
    out = ROOT / "shots"
    out.mkdir(exist_ok=True)

    base = server.start()
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(QSS)

    from app.ui.window import MainWindow

    health = httpx.get(f"{base}/api/health", timeout=5).json()
    win = MainWindow(base, health)
    win.resize(1120, 780)
    win.show()
    pump(app, 1.2)
    foreground(win)
    pump(app, 0.6)

    gear = win.gear_btn
    gpos = gear.mapToGlobal(QPoint(gear.width() // 2, gear.height() // 2))
    print("齿轮中心:", gpos.toTuple(), "窗口尺寸:", win.width(), win.height())

    for i in range(1, 7):
        click_at(gpos.x(), gpos.y())
        pump(app, 0.7)
        pop = win.settings_popup
        if pop is None:
            print(f"[{i}] 无浮层")
            continue
        vis = pop.isVisible()
        origin = pop.mapToGlobal(QPoint(0, 0))
        print(
            f"[{i}] 可见={vis} 尺寸={pop.width()}x{pop.height()} "
            f"位置=({origin.x()},{origin.y()}) 表单={pop.form.isVisible()}"
        )
        if vis:
            pop.grab().save(str(out / f"click_{i}.png"))

    # 整窗合成：浮层贴到窗口图上，便于看清相对位置
    pop = win.settings_popup
    if pop is not None and pop.isVisible():
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter

        base_pm = win.grab()
        panel = pop.grab()
        off = pop.mapTo(win, QPoint(0, 0))
        painter = QPainter(base_pm)
        painter.drawPixmap(
            QRectF(off.x(), off.y(), pop.width(), pop.height()),
            panel,
            QRectF(panel.rect()),
        )
        painter.end()
        base_pm.save(str(out / "click_full.png"))

    pump(app, 0.3)
    server.stop()
    print("截图:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

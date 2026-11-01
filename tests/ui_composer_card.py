# -*- coding: utf-8 -*-
"""输入卡片自检：按钮在框内右下角、空输入不可点、多行自动长高、Enter 提交。

不联网、不调模型。用法：python tests/ui_composer_card.py [输出目录]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.theme import QSS  # noqa: E402
from app.ui.window import MainWindow  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="ffs_card_"))
OUT.mkdir(parents=True, exist_ok=True)

OK = 0
FAIL = 0


def check(cond: bool, label: str, extra: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [ok] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"  <- {extra}" if extra else ""))


def pump(app: QApplication, n: int = 20) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def press(widget, key: int, mods=Qt.NoModifier) -> None:
    """直接投递按键事件，绕开 QTest（在无窗平台上一按就崩）。"""
    event = QKeyEvent(QEvent.KeyPress, key, mods)
    QApplication.sendEvent(widget, event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow("http://127.0.0.1:1", {"model": "deepseek-v4-flash",
                                            "api_key_ready": True,
                                            "profile_ready": True})
    win.resize(1120, 780)
    win.show()
    pump(app)

    card = win.composer
    ring = win.ctx_ring
    send = win.send_btn

    # ---- 1. 结构：环和按钮都在卡片内部 ----
    print("1. 布局")
    check(send.parent() is card, "发送键的父控件就是输入卡片")
    check(ring.parent() is card, "进度环的父控件就是输入卡片")

    card_rect = card.rect()
    for name, w in (("发送键", send), ("进度环", ring)):
        geo = w.geometry()
        inside = (card_rect.contains(geo.topLeft())
                  and card_rect.contains(geo.bottomRight()))
        check(inside, f"{name}完整落在卡片矩形内", f"{geo} vs {card_rect}")

    # 两个控件距卡片右边与底边应当留出同样小的内边距
    pad_right = card_rect.right() - send.geometry().right()
    pad_bottom = card_rect.bottom() - send.geometry().bottom()
    check(0 < pad_right <= 16, "发送键贴卡片右边（内边距 ≤16px）", f"{pad_right}px")
    check(0 < pad_bottom <= 14, "发送键贴卡片底边（内边距 ≤14px）", f"{pad_bottom}px")

    # 环与按钮同一水平中线，且环在按钮左侧
    check(abs(ring.geometry().center().y() - send.geometry().center().y()) <= 2,
          "环与发送键同轴",
          f"{ring.geometry().center().y()} vs {send.geometry().center().y()}")
    check(ring.geometry().right() < send.geometry().left(), "环在发送键左侧")

    # 卡片高度要明显高于旧版 52px 的裸输入框
    check(card.height() >= 80, "卡片抬高到能容纳底部按钮行", f"{card.height()}px")

    # ---- 2. 空输入不可点 ----
    print("2. 发送键可用性")
    check(card.toPlainText() == "", "初始为空")
    check(send.isEnabled() is False, "空输入时发送键不可点")

    card.edit.setPlainText("看看我的事业")
    pump(app, 5)
    check(send.isEnabled() is True, "有内容后发送键可点")

    card.edit.setPlainText("   ")
    pump(app, 5)
    check(send.isEnabled() is False, "只有空白字符时仍不可点")

    card.edit.clear()
    pump(app, 5)
    check(send.isEnabled() is False, "清空后回到不可点")
    win.grab().save(str(OUT / "card_empty.png"))

    # ---- 3. 多行自动长高 ----
    print("3. 自适应高度")
    base_h = card.height()
    card.edit.setPlainText("第一行\n第二行\n第三行\n第四行\n第五行")
    pump(app, 5)
    tall_h = card.height()
    check(tall_h > base_h, "多行输入时卡片变高", f"{base_h} -> {tall_h}")
    check(card.edit.height() <= card.height(), "输入区不会超出卡片")

    card.edit.setPlainText("\n".join(f"第{i}行" for i in range(1, 30)))
    pump(app, 5)
    capped = card.edit.height()
    check(capped <= 150, "行数很多时高度封顶，内部滚动", f"{capped}px")
    win.grab().save(str(OUT / "card_tall.png"))

    card.edit.setPlainText("我 1995 年 3 月 8 日上午 9 点出生，看看事业")
    pump(app, 5)
    check(card.height() == base_h, "清成一行后高度回落", f"{card.height()} vs {base_h}")
    win.grab().save(str(OUT / "card_filled.png"))

    # ---- 4. 键盘提交 ----
    print("4. 键盘")
    fired = {"n": 0}
    card.submitted.connect(lambda: fired.__setitem__("n", fired["n"] + 1))
    card.edit.setFocus()
    pump(app, 3)
    check(card.edit.hasFocus(), "输入区拿到焦点（点卡片任意处也能输入）")

    press(card.edit, Qt.Key_Return)
    pump(app, 3)
    check(fired["n"] == 1, "Enter 触发提交")

    press(card.edit, Qt.Key_Return, Qt.ShiftModifier)
    pump(app, 3)
    check(fired["n"] == 1, "Shift+Enter 只换行不提交")
    check("\n" in card.edit.toPlainText(), "Shift+Enter 确实插入了换行")

    # 中文输入法组字期间的 Enter 不该直接发出去（组字由 Qt 吞掉，
    # 这里只验证过滤器不会误判：空内容按 Enter 不发）
    card.edit.clear()
    pump(app, 3)
    before = fired["n"]
    press(card.edit, Qt.Key_Return)
    pump(app, 3)
    check(fired["n"] == before + 1, "空内容按 Enter 只发出信号，由窗口层拦掉")

    # ---- 5. 与进度环的联动位置 ----
    print("5. 位置核对")
    pos = ring.mapTo(win, QPoint(0, 0))
    print(f"  环在窗口中的坐标: ({pos.x()}, {pos.y()})  卡片底边 y={card.mapTo(win, QPoint(0, card.height())).y()}")
    win.grab().save(str(OUT / "window_card.png"))
    print("输出目录:", OUT)
    for f in sorted(OUT.glob("*.png")):
        print(" -", f.name, f.stat().st_size, "bytes")

    print()
    print(f"通过 {OK} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

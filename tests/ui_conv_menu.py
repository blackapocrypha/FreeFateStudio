# -*- coding: utf-8 -*-
"""会话列表交互自检：悬浮出「⋯」→ 点开删除入口 → 删除该会话。

用法：python tests/ui_conv_menu.py [输出目录]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402


def pump(app, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def gray_dots(pixmap, rect) -> int:
    """统计矩形内接近 #8C8C86 的像素数，用来判断三个点到底画没画。"""
    img = pixmap.toImage()
    dpr = pixmap.devicePixelRatio() or 1.0
    hits = 0
    for y in range(int(rect.top() * dpr), int(rect.bottom() * dpr)):
        for x in range(int(rect.left() * dpr), int(rect.right() * dpr)):
            c = img.pixelColor(x, y)
            if abs(c.red() - 0x8C) < 26 and abs(c.green() - 0x8C) < 26 and abs(c.blue() - 0x86) < 26:
                hits += 1
    return hits


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = server.start()

    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from app.ui.conv_list import dots_rect
    from app.ui.theme import QSS
    from app.ui.window import MainWindow

    # 清掉上一次跑挂留下的测试会话（只删标题以「测试会话」开头的，不碰真实数据）
    for conv in httpx.get(f"{base}/api/conversations", timeout=5).json():
        if str(conv.get("title") or "").startswith("测试会话"):
            httpx.delete(f"{base}/api/conversations/{conv['id']}", timeout=5)

    # 造三条会话
    made = []
    for title in ("测试会话一", "测试会话二", "测试会话三"):
        r = httpx.post(f"{base}/api/conversations", json={"title": title}, timeout=5)
        made.append(r.json()["id"])

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(QSS)

    health = httpx.get(f"{base}/api/health", timeout=5).json()
    win = MainWindow(base, health)
    win.resize(1120, 780)
    win.show()
    pump(app, 1.0)

    cl = win.conv_list
    print("列表条数:", cl.count())
    assert cl.count() >= 3

    # 悬浮行固定取我们自己造的那条（避免误伤真实会话）
    index = next(
        cl.model().index(i, 0) for i in range(cl.count())
        if str(cl.model().index(i, 0).data(Qt.UserRole)) in made
    )
    print("右上角还有删除按钮:", hasattr(win, "del_btn"))
    assert not hasattr(win, "del_btn"), "右上角的删除会话按钮应已移除"

    rect = cl.visualRect(index)
    dot_rect = dots_rect(rect)
    row_center = QPoint(60, rect.center().y())

    # 先把鼠标挪开，确保没有残留的 hover 态
    QTest.mouseMove(win.scroll.viewport(), QPoint(30, 30))
    pump(app, 0.4)
    before = gray_dots(cl.viewport().grab(), dot_rect)
    print("未悬浮时点区域灰色像素:", before)
    assert before == 0, "鼠标没悬浮时不应画三个点"

    # 悬浮到第二行
    QTest.mouseMove(cl.viewport(), row_center)
    pump(app, 0.5)
    after = gray_dots(cl.viewport().grab(), dot_rect)
    print("悬浮后点区域灰色像素:", after)
    assert after > 0, "悬浮后应画出三个点"
    cl.grab().save(str(out_dir / "10_hover_dots.png"))
    # 悬浮态底图要在点开浮层之前抓：浮层一出现，列表的 hover 就没了，三个点会消失
    hover_base = win.grab()

    # 选中项不应被点三个点改变
    current_before = cl.currentRow()
    QTest.mouseClick(cl.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(dot_rect.center().x(), dot_rect.center().y()))
    pump(app, 0.5)
    menu = cl._menu
    print("弹出菜单可见:", bool(menu and menu.isVisible()))
    assert menu is not None and menu.isVisible(), "点三个点应弹出删除入口"
    print("当前行是否被改动:", current_before, "->", cl.currentRow())
    assert cl.currentRow() == current_before, "点三个点不应切换当前会话"
    menu.grab().save(str(out_dir / "11_menu.png"))

    # 合成图：窗口 + 浮层（逻辑尺寸画布，绕开 dpr 换算）
    from PySide6.QtGui import QPainter, QPixmap

    base_pm = hover_base
    panel_pm = menu.grab()
    win_origin = win.mapToGlobal(QPoint(0, 0))
    menu_origin = menu.mapToGlobal(QPoint(0, 0))
    canvas = QPixmap(win.width(), win.height())
    canvas.fill(win.palette().window().color())
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(0, 0, win.width(), win.height(),
                       base_pm, 0, 0, base_pm.width(), base_pm.height())
    painter.drawPixmap(menu_origin.x() - win_origin.x(), menu_origin.y() - win_origin.y(),
                       menu.width(), menu.height(),
                       panel_pm, 0, 0, panel_pm.width(), panel_pm.height())
    painter.end()
    canvas.save(str(out_dir / "13_menu_in_window.png"))

    # 点删除
    target = str(index.data(Qt.UserRole))  # 就是悬浮这一行自己的 id
    before_count = cl.count()
    menu.btn.click()
    pump(app, 0.8)
    print("删除后条数:", before_count, "->", cl.count())
    assert cl.count() == before_count - 1, "删除后列表应少一条"
    ids = [c["id"] for c in httpx.get(f"{base}/api/conversations", timeout=5).json()]
    print("服务端剩余会话:", len(ids), "| 被删的还在吗:", target in ids)
    assert target not in ids, "服务端会话未被删除"
    others = [cid for cid in made if cid != target]
    assert all(cid in ids for cid in others), "误删了其它会话"

    # 删掉「当前正在看」的会话：界面要回到空状态
    rest = [
        i for i in range(cl.count())
        if str(cl.model().index(i, 0).data(Qt.UserRole)) in made
    ]
    assert rest, "还剩测试会话才对"
    row = rest[0]
    cl.setCurrentRow(row)
    win._on_conv_clicked(cl.item(row))
    pump(app, 0.8)
    print("已载入会话:", bool(win.current_id))
    assert win.current_id, "应已载入一个会话"
    rect2 = cl.visualRect(cl.model().index(row, 0))
    QTest.mouseMove(cl.viewport(), QPoint(60, rect2.center().y()))
    pump(app, 0.3)
    dr2 = dots_rect(rect2)
    QTest.mouseClick(cl.viewport(), Qt.LeftButton, Qt.NoModifier,
                     QPoint(dr2.center().x(), dr2.center().y()))
    pump(app, 0.4)
    cl._menu.btn.click()
    pump(app, 0.8)
    print("删当前会话后 current_id:", win.current_id, "| 标题:", win.title_label.text())
    assert win.current_id is None, "删掉当前会话后应清空 current_id"
    assert win.title_label.text() == "新对话"

    # 整窗合成图（含悬浮行与三个点）
    QTest.mouseMove(cl.viewport(), row_center)
    pump(app, 0.4)
    win.grab().save(str(out_dir / "12_window.png"))

    # 清理：只删本次造的会话
    left = httpx.get(f"{base}/api/conversations", timeout=5).json()
    for conv in left:
        if conv["id"] in made:
            httpx.delete(f"{base}/api/conversations/{conv['id']}", timeout=5)

    print("截图目录:", out_dir)
    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

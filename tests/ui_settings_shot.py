# -*- coding: utf-8 -*-
"""界面自检：齿轮 → 设置浮层 → 展开表单 → 保存，并截图核对。

用法：python tests/ui_settings_shot.py [输出目录]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import model_name  # noqa: E402
from app.server import server  # noqa: E402


def pump(app, seconds: float = 0.8) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = server.start()

    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtGui import QFont, QPainter
    from PySide6.QtWidgets import QApplication

    from app.ui.theme import QSS
    from app.ui.window import MainWindow

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(QSS)

    health = httpx.get(f"{base}/api/health", timeout=5).json()
    win = MainWindow(base, health)
    win.resize(1120, 780)
    win.show()
    pump(app, 1.0)

    print("齿轮提示:", win.gear_btn.toolTip().replace("\n", " / "))
    print("警告可见:", win.key_warn.isVisible())
    win.grab().save(str(out_dir / "01_window.png"))

    # 点齿轮 → 浮层出现，初始只有一项
    win.gear_btn.click()
    pump(app, 0.5)
    popup = win.settings_popup
    assert popup is not None and popup.isVisible(), "设置浮层未弹出"
    print("表单初始可见:", popup.form.isVisible())
    assert not popup.form.isVisible()
    popup.grab().save(str(out_dir / "02_popup.png"))

    collapsed_h = popup.height()
    anchor_bottom = win.gear_btn.mapToGlobal(QPoint(0, 0)).y()

    # 展开模型配置
    popup.item.clicked.emit()
    pump(app, 0.4)
    expanded_h = popup.height()
    print("表单展开:", popup.form.isVisible(), "| 高度", collapsed_h, "→", expanded_h)
    assert popup.form.isVisible()
    assert expanded_h > collapsed_h, "展开后高度应增大"
    print("回填模型:", popup.model_edit.text())
    popup.grab().save(str(out_dir / "03_form.png"))

    # 回归：收起后高度必须回落到初始值（顶层窗口 adjustSize 只增不减的老问题）
    popup.item.clicked.emit()
    pump(app, 0.4)
    print("收起后高度:", popup.height(), "| 应等于", collapsed_h)
    assert popup.height() == collapsed_h, f"收起后高度未回落：{popup.height()} != {collapsed_h}"
    popup.grab().save(str(out_dir / "03b_collapsed.png"))

    # 回归：反复开关 5 轮，每轮尺寸与贴边位置都必须一致（多次点击后格式错乱）
    for i in range(1, 6):
        win.gear_btn.click()  # 收起
        pump(app, 0.4)
        assert not popup.isVisible(), f"第 {i} 轮：再次点击齿轮应收起面板"
        win.gear_btn.click()  # 再打开
        pump(app, 0.4)
        assert popup.isVisible(), f"第 {i} 轮：点击齿轮应重新弹出"
        bottom = popup.mapToGlobal(QPoint(0, 0)).y() + popup.height()
        print(
            f"  第{i}轮 尺寸={popup.width()}x{popup.height()} "
            f"底边={bottom} 齿轮顶={anchor_bottom} 表单={popup._form_open}"
        )
        assert popup.height() == collapsed_h, f"第 {i} 轮高度漂移：{popup.height()}"
        assert not popup._form_open, f"第 {i} 轮重开后表单应处于收起状态"
        assert bottom == anchor_bottom - 8, f"第 {i} 轮浮层未贴住齿轮：{bottom}"
    popup.grab().save(str(out_dir / "03c_reopen.png"))

    # 保存（模型名不变，验证读写链路与提示文案）
    popup.item.clicked.emit()
    pump(app, 0.4)
    popup.model_edit.setText(model_name())
    popup.save_btn.click()
    pump(app, 0.8)
    print("保存提示:", popup.status.text())
    assert "已保存" in popup.status.text(), popup.status.text()
    popup.grab().save(str(out_dir / "04_saved.png"))

    # 空模型名必须拦截
    popup.model_edit.setText("   ")
    popup.save_btn.click()
    pump(app, 0.3)
    print("空值提示:", popup.status.text())
    assert "不能为空" in popup.status.text()

    # 合成图：窗口截图 + 浮层截图按逻辑坐标叠加（避免桌面截图受其它窗口/DPI 影响）
    p = win.settings_popup
    if not p._form_open:
        popup.item.clicked.emit()
        pump(app, 0.6)
    # 把测试留下的空值与红字清掉，截图才是正常态
    p.model_edit.setText(model_name())
    p._message("")
    pump(app, 0.2)

    base = win.grab()
    panel = p.grab()
    # mapTo(顶层窗口) 返回的是屏幕坐标，必须自行减去窗口客户区原点
    win_origin = win.mapToGlobal(QPoint(0, 0))
    pop_origin = p.mapToGlobal(QPoint(0, 0))
    ox = pop_origin.x() - win_origin.x()
    oy = pop_origin.y() - win_origin.y()
    print("浮层相对窗口:", ox, oy, "| 齿轮顶:", win.gear_btn.mapTo(win, QPoint(0, 0)).y())
    # 在逻辑尺寸画布上合成：目标坐标用逻辑像素，源矩形用位图设备像素，
    # 这样不必操心 DPR 换算（高 DPI 下 win.grab() 是 1.5 倍图）。
    from PySide6.QtGui import QPixmap

    canvas = QPixmap(win.width(), win.height())
    canvas.fill(win.palette().window().color())
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(
        0, 0, win.width(), win.height(), base, 0, 0, base.width(), base.height()
    )
    painter.drawPixmap(
        ox, oy, p.width(), p.height(), panel, 0, 0, panel.width(), panel.height()
    )
    painter.end()
    canvas.save(str(out_dir / "05_desktop.png"))
    print("浮层尺寸:", p.size().toTuple(), "| 合成图:", canvas.size().toTuple())

    print("截图目录:", out_dir)
    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

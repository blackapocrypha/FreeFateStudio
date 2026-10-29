# -*- coding: utf-8 -*-
"""界面自检：齿轮 → 个人信息 → 填写保存 → 回填与手风琴切换，并截图核对。

用法：python tests/ui_profile_shot.py [输出目录]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402
from app.storage import store  # noqa: E402


def pump(app, seconds: float = 0.6) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = server.start()
    backup = store.get_profile()

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont
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
    pump(app, 0.8)

    try:
        win.gear_btn.click()
        pump(app, 0.5)
        pop = win.settings_popup
        assert pop is not None and pop.isVisible(), "设置浮层未弹出"
        collapsed_h = pop.height()
        anchor_top = win.gear_btn.mapToGlobal(QPoint(0, 0)).y()
        print("收起高度:", collapsed_h, "| 两个入口都在:",
              pop.item.isVisible(), pop.profile_item.isVisible())
        assert not pop.form.isVisible() and not pop.profile_form.isVisible()
        pop.grab().save(str(out_dir / "p01_collapsed.png"))

        # 展开个人信息
        pop.profile_item.clicked.emit()
        pump(app, 0.5)
        print("档案表单展开:", pop.profile_form.isVisible(),
              "| 高度", collapsed_h, "→", pop.height())
        assert pop.profile_form.isVisible() and not pop.form.isVisible()
        assert pop.height() > collapsed_h
        bottom = pop.mapToGlobal(QPoint(0, 0)).y() + pop.height()
        assert bottom == anchor_top - 8, f"浮层未贴住齿轮：{bottom}"
        pop.grab().save(str(out_dir / "p02_profile_empty.png"))

        # 手风琴：开模型配置应自动收起个人信息
        pop.item.clicked.emit()
        pump(app, 0.4)
        print("切到模型配置:", pop.form.isVisible(), pop.profile_form.isVisible())
        assert pop.form.isVisible() and not pop.profile_form.isVisible()
        model_h = pop.height()
        pop.grab().save(str(out_dir / "p03_model.png"))

        # 再切回个人信息
        pop.profile_item.clicked.emit()
        pump(app, 0.4)
        assert pop.profile_form.isVisible() and not pop.form.isVisible()
        print("高度 模型/档案:", model_h, pop.height())

        # 非法日期必须被服务端拒绝并显示红字
        pop.date_edit.setText("1990-02-30")
        pop.time_edit.setText("14:30")
        pop.male_btn.click()
        pop.profile_save_btn.click()
        pump(app, 0.5)
        print("非法日期提示:", pop.profile_status.text())
        assert pop.profile_status.property("state") == "err", pop.profile_status.text()
        pop.grab().save(str(out_dir / "p04_invalid.png"))

        # 正常保存（带出生地）
        pop.date_edit.setText("1990-05-12")
        pop.time_edit.setText("14:30")
        pop.place_edit.setText("临沂")
        pop.profile_save_btn.click()
        pump(app, 0.6)
        print("保存提示:", pop.profile_status.text())
        print("地点提示:", pop.place_hint.text())
        print("行值:", pop.profile_item._value.text())
        assert pop.profile_status.property("state") == "ok"
        assert "已填写" in pop.profile_item._value.text() or "1990" in pop.profile_item._value.text()
        assert "已启用真太阳时" in pop.place_hint.text()
        pop.grab().save(str(out_dir / "p05_profile_saved.png"))

        # 服务端确认落库
        saved = httpx.get(f"{base}/api/profile", timeout=5).json()
        assert saved["configured"] and saved["birth_place"] == "临沂"
        assert saved["solar_time"]["enabled"] is True

        # 齿轮提示同步
        print("齿轮提示:", win.gear_btn.toolTip().replace("\n", " / "))
        assert "本人档案 已填写" in win.gear_btn.toolTip()

        # 重开浮层：表单收起、字段回填
        pop.hide()
        time.sleep(0.3)
        win.gear_btn.click()
        pump(app, 0.5)
        print("重开:", pop.height(), "| 面板:", pop._open_panel,
              "| 日期回填:", pop.date_edit.text())
        assert pop.height() == collapsed_h and pop._open_panel is None
        assert pop.date_edit.text() == "1990-05-12"
        assert pop.place_edit.text() == "临沂"
        assert pop.male_btn.isChecked()

        # 清空出生地：真太阳时应关闭
        pop.profile_item.clicked.emit()
        pump(app, 0.4)
        pop.place_edit.setText("")
        pop.profile_save_btn.click()
        pump(app, 0.6)
        print("留空后提示:", pop.profile_status.text(), "|", pop.place_hint.text())
        assert "未启用真太阳时" in pop.profile_status.text()
        assert httpx.get(f"{base}/api/profile", timeout=5).json()["solar_time"]["enabled"] is False
        pop.grab().save(str(out_dir / "p06_no_place.png"))

        # 空状态文案随档案切换
        win.current_id = None
        win._show_empty()
        pump(app, 0.3)
        win.grab().save(str(out_dir / "p07_window.png"))
        print("截图目录:", out_dir)
    finally:
        if backup:
            httpx.put(
                f"{base}/api/profile",
                json={
                    "birth_date": backup["birth_date"],
                    "birth_time": backup["birth_time"],
                    "gender": backup["gender"],
                    "birth_place": backup["birth_place"],
                },
                timeout=10,
            )
            print("已还原原档案")
        else:
            httpx.delete(f"{base}/api/profile", timeout=10)
            print("原无档案，保持为空")
        server.stop()

    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

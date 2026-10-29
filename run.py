# -*- coding: utf-8 -*-
"""程序入口：启动本地 FastAPI 服务，再拉起 PySide6 窗口。

打包后由 PyInstaller 直接执行本文件；服务与界面同进程，端口自动选择。
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_path() -> None:
    """打包后保证 app 包可被导入（onedir/onefile 都在 exe 同级或 _MEIPASS）。"""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        for p in (str(base), str(Path(sys.executable).parent)):
            if p not in sys.path:
                sys.path.insert(0, p)


def _ensure_std_streams() -> None:
    """pythonw / 无控制台模式下 sys.stdout 与 sys.stderr 均为 None。

    任何 isatty()、write() 调用都会炸，必须先替换成 devnull。
    """
    import os

    if sys.stdout is None or sys.stderr is None:
        try:
            devnull = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            return
        if sys.stdout is None:
            sys.stdout = devnull
        if sys.stderr is None:
            sys.stderr = devnull


def main() -> int:
    _ensure_path()
    _ensure_std_streams()

    from app.diagnostics import install_global_hooks, write_log
    install_global_hooks()

    try:
        return _run_gui()
    except BaseException:
        import traceback
        write_log("启动失败", traceback.format_exc())
        raise


def _run_gui() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

    from app.diagnostics import log_path, write_log

    from app.config import APP_NAME, APP_SUBTITLE, icon_path

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    icon_file = icon_path()
    if icon_file is not None:
        app.setWindowIcon(QIcon(str(icon_file)))

    from app.ui.theme import QSS
    app.setStyleSheet(QSS)

    # 启动占位：服务初始化会加载 LangGraph，需要几秒
    splash = QLabel(f"{APP_NAME}\n{APP_SUBTITLE}\n\n正在启动本地服务…")
    splash.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint)
    splash.setAlignment(Qt.AlignCenter)
    splash.setStyleSheet(
        "background:#111111; color:#F5F5F2; font-size:13px;"
        "border-radius:12px; padding:24px;"
    )
    splash.resize(320, 160)
    splash.show()
    app.processEvents()

    from app.server import server

    try:
        base_url = server.start()
    except Exception as exc:
        import traceback
        write_log("本地服务启动失败", traceback.format_exc())
        splash.close()
        QMessageBox.critical(
            None, "启动失败",
            f"本地服务启动失败：\n{exc}\n\n详细日志：{log_path()}",
        )
        return 1

    from app.ui.window import MainWindow

    health = {}
    try:
        import httpx
        health = httpx.get(f"{base_url}/api/health", timeout=5).json()
    except Exception:
        pass

    window = MainWindow(base_url, health)
    splash.close()
    window.show()

    code = app.exec()
    server.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())

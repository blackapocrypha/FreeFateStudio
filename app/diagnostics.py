# -*- coding: utf-8 -*-
"""错误落盘：打包成窗口程序后没有控制台，异常必须写文件才看得到。"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime

from .config import data_dir


def log_path():
    return data_dir() / "error.log"


def write_log(tag: str, text: str) -> None:
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} {tag} =====\n")
            f.write(text.rstrip() + "\n")
    except OSError:
        pass


def install_global_hooks() -> None:
    """把未捕获异常与线程异常统一写进 error.log。"""

    def _hook(exc_type, exc, tb) -> None:
        write_log("未捕获异常", "".join(traceback.format_exception(exc_type, exc, tb)))

    def _thread_hook(args) -> None:
        write_log(
            f"线程异常 {getattr(args.thread, 'name', '?')}",
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook

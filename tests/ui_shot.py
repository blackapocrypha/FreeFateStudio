# -*- coding: utf-8 -*-
"""界面冒烟：起服务 → 跑一段真实对话 → 打开窗口 → 截图。

用法：python tests/ui_shot.py [输出图片路径]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402


def run_turn(base: str, cid: str, message: str) -> str:
    text = []
    with httpx.Client(timeout=httpx.Timeout(30, read=None)) as client:
        with client.stream("POST", f"{base}/api/chat",
                           json={"conversation_id": cid, "message": message}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    if ev["type"] == "token":
                        text.append(ev["text"])
                    elif ev["type"] == "error":
                        print("错误:", ev["message"])
    return "".join(text)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "preview.png"
    base = server.start()
    conv = httpx.post(f"{base}/api/conversations", json={}, timeout=5).json()
    cid = conv["id"]
    print("对话中…")
    answer = run_turn(base, cid, "男，1990年5月12日下午两点半，山东临沂。看看事业和财运")
    print("回答长度:", len(answer))

    from PySide6.QtWidgets import QApplication
    from app.ui.theme import QSS
    from app.ui.window import MainWindow

    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    health = httpx.get(f"{base}/api/health", timeout=5).json()
    win = MainWindow(base, health)
    win.resize(1180, 820)
    win.show()
    app.processEvents()
    win.load_conversation(cid)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)

    win.grab().save(str(out))
    print("截图已保存:", out)

    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

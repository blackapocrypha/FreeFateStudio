# -*- coding: utf-8 -*-
"""打包产物里的上下文接口与进度环检查。

只做只读探活 + 截屏，不写设置、不发对话请求（避免动用户的 .env 与 Key）。
用法：python tests/smoke_exe_context.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "FreeFateStudio" / "FreeFateStudio.exe"

sys.path.insert(0, str(ROOT / "tests"))

import httpx  # noqa: E402

from smoke_exe import bring_to_front, find_base, screenshot  # noqa: E402

OK = 0
FAIL = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"[OK] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label} {detail}")


def main() -> int:
    if not EXE.exists():
        print("未找到 exe:", EXE)
        return 1

    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    try:
        base = find_base()
        health = httpx.get(f"{base}/api/health", timeout=5).json()
        print("健康检查:", health)
        check(health["version"] == "1.2.0", "版本号 1.2.0", health.get("version"))

        conv = httpx.post(f"{base}/api/conversations", json={"title": "[探活] 上下文"}, timeout=5).json()
        cid = conv["id"]

        ctx = httpx.get(f"{base}/api/conversations/{cid}/context", timeout=10)
        check(ctx.status_code == 200, "context 接口可用", str(ctx.status_code))
        snap = ctx.json() if ctx.status_code == 200 else {}
        print("新会话上下文:", snap)
        check(snap.get("window") == 128_000, "窗口按模型推断为 128K", str(snap.get("window")))
        check(snap.get("threshold") == 128_000 - 16_384, "阈值 = 窗口 - 16384",
              str(snap.get("threshold")))
        check(snap.get("keep_recent") == 20_000, "保留原文 20000", str(snap.get("keep_recent")))
        check(snap.get("enabled") is True, "自动压缩默认开启")
        check(0 < snap.get("tokens", 0) < 10_000, "空会话只剩系统提示开销",
              str(snap.get("tokens")))

        # 历史会话也应能取到占用
        convs = httpx.get(f"{base}/api/conversations", timeout=5).json()
        others = [c for c in convs if c["id"] != cid]
        if others:
            oc = httpx.get(f"{base}/api/conversations/{others[0]['id']}/context", timeout=10).json()
            check("tokens" in oc, "历史会话可读上下文", str(oc.get("tokens")))

        bad = httpx.get(f"{base}/api/conversations/deadbeef/context", timeout=5)
        check(bad.status_code == 404, "不存在的会话返回 404", str(bad.status_code))

        httpx.delete(f"{base}/api/conversations/{cid}", timeout=5)

        time.sleep(1.5)
        bring_to_front(proc.pid)
        time.sleep(1.5)
        screenshot(ROOT / "exe_context_ring.png")
    finally:
        time.sleep(0.5)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    print(f"通过 {OK} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

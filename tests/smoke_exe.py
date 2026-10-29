# -*- coding: utf-8 -*-
"""打包产物冒烟：启动 exe → 探活 → 真实对话 → 抓屏截图 → 关闭。

用法：python tests/smoke_exe.py
"""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "FreeFateStudio" / "FreeFateStudio.exe"

import httpx  # noqa: E402


def find_base(timeout: float = 90.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for port in range(8765, 8776):
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
                if r.status_code == 200:
                    return f"http://127.0.0.1:{port}"
            except httpx.HTTPError:
                continue
        time.sleep(0.6)
    raise RuntimeError("exe 启动后未能在 90 秒内提供健康检查")


def bring_to_front(pid: int) -> None:
    """把 exe 的主窗口提到最前（后台进程调 SetForegroundWindow 常被系统忽略，
    改用 SetWindowPos 短暂置顶）。"""
    try:
        user32 = ctypes.windll.user32
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum(hwnd, _lparam):
            owner = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(_enum, 0)
        if not found:
            print("未找到窗口")
            return
        hwnd = found[0]
        SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(
            hwnd, -1, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
        )  # HWND_TOPMOST
        user32.SetForegroundWindow(hwnd)
    except Exception as exc:  # 截图失败不影响功能判定
        print("窗口前置失败:", exc)


def screenshot(path: Path) -> None:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen()
    pix = screen.grabWindow(0)
    pix.save(str(path))
    print("桌面截图:", path)


def main() -> int:
    if not EXE.exists():
        print("未找到 exe:", EXE)
        return 1

    print("启动:", EXE)
    proc = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    profile_backup = None
    try:
        base = find_base()
        health = httpx.get(f"{base}/api/health", timeout=5).json()
        print("健康检查:", health)

        # 个人信息：确认打包后 SQLite 单行表可读写，且地名解析生效
        profile_backup = httpx.get(f"{base}/api/profile", timeout=5).json()
        prof = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "男",
                "birth_place": "临沂",
            },
            timeout=5,
        )
        print("写入个人信息:", prof.status_code, prof.json().get("solar_time"))
        assert prof.status_code == 200 and prof.json()["solar_time"]["enabled"]
        assert httpx.get(f"{base}/api/health", timeout=5).json()["profile_ready"] is True

        conv = httpx.post(f"{base}/api/conversations", json={}, timeout=5).json()
        cid = conv["id"]
        tokens, tools = 0, []
        with httpx.Client(timeout=httpx.Timeout(30, read=None)) as client:
            with client.stream("POST", f"{base}/api/chat",
                               json={"conversation_id": cid,
                                     "message": "1990年5月12日14:30出生的男生，临沂，简单说说性格"}) as resp:
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        ev = json.loads(line[6:])
                        if ev["type"] == "token":
                            tokens += 1
                        elif ev["type"] == "tool":
                            tools.append(ev["label"])
                        elif ev["type"] == "error":
                            print("对话错误:", ev["message"])
        msgs = httpx.get(f"{base}/api/conversations/{cid}/messages", timeout=5).json()
        print(f"增量 {tokens} 片；工具 {tools}；落库 {len(msgs)} 条")
        print("回答开头:", (msgs[-1]["content"][:80].replace(chr(10), " ") if msgs else "空"))

        httpx.delete(f"{base}/api/conversations/{cid}", timeout=5)

        # 设置读写：确认打包后 .env 定位与热重建可用
        st = httpx.get(f"{base}/api/settings", timeout=5).json()
        print("设置:", st)
        saved = httpx.put(
            f"{base}/api/settings",
            json={"model": st["model"], "api_key": "sk-exe-smoke-0000"},
            timeout=5,
        )
        print("保存设置:", saved.status_code, saved.json().get("api_key_masked"))
        assert saved.status_code == 200 and saved.json()["ok"]
        env_file = Path(st["env_path"])
        assert env_file.exists(), f"未生成 .env: {env_file}"
        text = env_file.read_text(encoding="utf-8")
        assert "sk-exe-smoke-0000" in text, text
        print(".env 已写入:", env_file)

        # 截图要在进程还活着的时候做
        time.sleep(2.0)
        bring_to_front(proc.pid)
        time.sleep(1.5)
        screenshot(ROOT / "exe_running.png")
    finally:
        # 还原个人信息，别把测试档案留在用户库里
        try:
            if profile_backup and profile_backup.get("configured"):
                httpx.put(
                    f"{base}/api/profile",
                    json={
                        "birth_date": profile_backup["birth_date"],
                        "birth_time": profile_backup["birth_time"],
                        "gender": profile_backup["gender"],
                        "birth_place": profile_backup["birth_place"],
                    },
                    timeout=5,
                )
            else:
                httpx.delete(f"{base}/api/profile", timeout=5)
            print("个人信息已还原")
        except Exception as exc:  # exe 已退出时忽略
            print("个人信息还原失败:", exc)
        time.sleep(1.0)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        # 还原产物里的 .env，避免把测试 Key 留在 dist
        src = ROOT / ".env"
        dst = EXE.parent / ".env"
        if src.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print("已还原 dist/.env")
        print("进程已退出")

    return 0


if __name__ == "__main__":
    sys.exit(main())

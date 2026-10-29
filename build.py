# -*- coding: utf-8 -*-
"""一键打包：pyinstaller FreeFateStudio.spec --noconfirm，并把 .env 复制到产物目录。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "FreeFateStudio"
DIST = ROOT / "dist" / NAME


def _park_previous() -> None:
    """把上一次的产物目录改名挪开。

    PyInstaller 在覆盖 COLLECT 目录时会递归删除几千个文件，
    一步 rm -rf 式的删除在某些安全策略下会被直接拦掉；改名是纯元数据操作，
    不产生删除动作，既快又稳。旧目录留待人工清理。
    """
    if not DIST.exists():
        return
    parked = DIST.parent / f"{DIST.name}.prev-{time.strftime('%m%d%H%M%S')}"
    try:
        DIST.rename(parked)
        print(f"旧产物已挪到 {parked.name}（可自行删除）")
    except OSError as exc:
        print("旧产物改名失败：", exc)


def main() -> int:
    _park_previous()
    cmd = [sys.executable, "-m", "PyInstaller", f"{NAME}.spec", "--noconfirm"]
    print(">", " ".join(cmd))
    code = subprocess.call(cmd, cwd=ROOT)
    if code != 0:
        print("打包失败，退出码", code)
        return code

    env_src = ROOT / ".env"
    if env_src.exists() and DIST.exists():
        shutil.copy2(env_src, DIST / ".env")
        print("已复制 .env ->", DIST / ".env")

    exe = DIST / f"{NAME}.exe"
    print("完成：", exe, "存在" if exe.exists() else "缺失")
    return 0


if __name__ == "__main__":
    sys.exit(main())

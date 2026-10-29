# -*- coding: utf-8 -*-
"""全局配置：路径、模型、密钥、端口。

目录约定：
  安装目录（只读）   exe 所在目录 / 源码根目录 —— 放 .env、图标等静态资源
  数据目录（可写）   %LOCALAPPDATA%\\FreeFateStudio —— 放 SQLite 与会话存档

配置优先级（低 → 高）：进程环境变量 < .env
保存设置时优先改写安装目录的 .env（用户可见），不可写则回落到数据目录。

程序在 1.1.0 由 FateStudio 更名为 FreeFateStudio，数据目录随之改名；
首次启动会把旧目录里的库文件整体搬过来，用户的个人信息与历史会话不受影响。
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

APP_NAME = "FreeFateStudio"
APP_TITLE = "FreeFateStudio"
APP_SUBTITLE = "命理工作台"
APP_VERSION = "1.1.0"

# 更名前的数据目录，仅用于首次启动时搬迁
LEGACY_APP_NAMES = ("FateStudio",)

DEFAULT_MODEL = "deepseek-v4-flash"

# 配置版本号：每次保存设置自增，agent 用它判断是否需要重建模型与图
_REV_LOCK = threading.Lock()
_CONFIG_REV = 0


def is_frozen() -> bool:
    """是否为 PyInstaller 打包后的运行态。"""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    """安装目录：打包后是 exe 同级的 _internal 上层。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _adopt_legacy_data(base: Path, target: Path) -> None:
    """把旧版 FateStudio 数据目录里的文件搬到新目录。

    只搬目标端不存在的文件，不覆盖；任何一步失败都静默跳过——
    实在搬不动也不该拦着程序启动，用户重新填一次个人信息即可。
    """
    import shutil

    for name in LEGACY_APP_NAMES:
        old = base / name
        if not old.is_dir():
            continue
        try:
            if old.resolve() == target.resolve():
                continue
            target.mkdir(parents=True, exist_ok=True)
            for item in old.iterdir():
                dest = target / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            if not any(old.iterdir()):
                old.rmdir()
        except OSError:
            continue


def data_dir() -> Path:
    """可写数据目录，打包后仍可写。"""
    base = Path(os.getenv("LOCALAPPDATA") or str(Path.home()))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    _adopt_legacy_data(base, d)
    return d


DB_PATH = data_dir() / "fate.db"
CKPT_PATH = data_dir() / "checkpoint.db"

ICON_NAME = "FreeFateStudio.ico"


def icon_path() -> Optional[Path]:
    """窗口 / 任务栏图标。打包后优先取解包目录，其次取 exe 同级。"""
    roots = []
    if hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    roots.append(install_dir())
    for root in roots:
        p = root / ICON_NAME
        if p.exists():
            return p
    return None


# ------------------------------------------------------------
# .env 读写
# ------------------------------------------------------------
def _load_env_files() -> None:
    """从 .env 读取配置（不覆盖已存在的环境变量）。

    先读数据目录、再读安装目录：数据目录是用户保存的覆盖值，优先级更高。
    """
    for path in (data_dir() / ".env", install_dir() / ".env"):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and not os.getenv(k):
                    os.environ[k] = v
        except OSError:
            continue


_load_env_files()


def _writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
        return True
    except OSError:
        return False


def env_path() -> Path:
    """当前生效的 .env 路径（也是保存设置时的写入目标）。"""
    override = data_dir() / ".env"
    if override.exists():
        return override
    shipped = install_dir() / ".env"
    if shipped.exists() and _writable(shipped):
        return shipped
    if not shipped.exists() and _writable(shipped):
        return shipped
    return override


def _patch_env_file(path: Path, updates: Dict[str, str]) -> None:
    """只改指定键，保留其它行与注释。"""
    lines = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            lines = []

    pending = dict(updates)
    out = []
    for line in lines:
        raw = line.strip()
        key = raw.split("=", 1)[0].strip() if ("=" in raw and not raw.startswith("#")) else None
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    for key, value in pending.items():
        out.append(f"{key}={value}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


# ------------------------------------------------------------
# 读取当前配置
# ------------------------------------------------------------
def model_name() -> str:
    return (os.getenv("FATE_MODEL") or DEFAULT_MODEL).strip()


def thinking_enabled() -> bool:
    return os.getenv("FATE_THINKING", "0").strip() in ("1", "true", "True", "yes")


# 仓库里的 .env 是模板，值写的是占位符。这类值必须当成"未配置"，
# 否则界面会显示已配置，实际请求却直接 401。
_PLACEHOLDER_KEYS = {
    "xxx", "xxxx", "todo", "changeme", "your-key", "your_key",
    "your-api-key", "your_api_key", "sk-xxx", "sk-xxxx",
}


def _is_placeholder(value: str) -> bool:
    low = value.strip().lower()
    if not low:
        return True
    if low in _PLACEHOLDER_KEYS:
        return True
    # 去掉 sk- 前缀后纯由 x / - / * / . 组成的（xxx、sk-xxxx、sk-xxxxxxxx 等）
    core = low[3:] if low.startswith("sk-") else low
    return set(core) <= {"x", "-", "*", "."} if core else True


def api_key() -> str:
    k = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return "" if _is_placeholder(k) else k


def api_key_ready() -> bool:
    return bool(api_key())


def mask_key(key: Optional[str] = None) -> str:
    k = (key if key is not None else api_key()) or ""
    if not k:
        return ""
    if len(k) <= 10:
        return k[:2] + "***"
    return f"{k[:6]}…{k[-4:]}"


def config_revision() -> int:
    return _CONFIG_REV


def settings_snapshot() -> Dict[str, Any]:
    return {
        "model": model_name(),
        "thinking": thinking_enabled(),
        "api_key_set": api_key_ready(),
        "api_key_masked": mask_key(),
        "env_path": str(env_path()),
        "provider": "deepseek",
    }


def save_settings(
    model: Optional[str] = None,
    api_key_value: Optional[str] = None,
    thinking: Optional[bool] = None,
) -> Dict[str, Any]:
    """写入 .env 并立即生效（更新进程环境变量 + 递增版本号触发重建）。"""
    global _CONFIG_REV

    updates: Dict[str, str] = {}
    if model is not None and model.strip():
        updates["FATE_MODEL"] = model.strip()
    if api_key_value is not None and api_key_value.strip():
        updates["DEEPSEEK_API_KEY"] = api_key_value.strip()
    if thinking is not None:
        updates["FATE_THINKING"] = "1" if thinking else "0"

    if updates:
        _patch_env_file(env_path(), updates)
        for key, value in updates.items():
            os.environ[key] = value
        with _REV_LOCK:
            _CONFIG_REV += 1

    return settings_snapshot()


# 本地服务端口：优先固定端口，被占用时自动换空闲端口
PREFERRED_PORT = int(os.getenv("FATE_PORT", "8765"))
HOST = "127.0.0.1"

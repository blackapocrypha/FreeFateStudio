# -*- coding: utf-8 -*-
"""本地服务生命周期：在同进程的守护线程里跑 uvicorn。"""

from __future__ import annotations

import socket
import threading
import time
import traceback
from typing import Optional

import httpx
import uvicorn

from .config import HOST, PREFERRED_PORT
from .api import app
from .diagnostics import write_log


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    if _port_available(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


class LocalServer:
    """进程内 uvicorn。start() 阻塞到健康检查通过为止。"""

    def __init__(self) -> None:
        self.port: Optional[int] = None
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def start(self, timeout: float = 40.0) -> str:
        port = _pick_port()
        # 显式钉死 loop/http/ws 实现：uvicorn 默认用 "auto"，
        # 那三处是运行时按字符串动态 import，打包后极易断链（本项目不用 WebSocket）。
        # log_config=None：窗口程序里 sys.stdout 是 None，uvicorn 自带的日志格式化器
        # 会调 sys.stdout.isatty() 直接抛 AttributeError，必须关掉它的日志配置。
        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            loop="asyncio",
            http="h11",
            ws="none",
            log_config=None,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        # 关闭 uvicorn 自己的信号处理，否则会抢主线程
        self._server.install_signal_handlers = lambda: None  # type: ignore[assignment]

        errors = []

        def _run() -> None:
            try:
                self._server.run()
            except BaseException:
                tb = traceback.format_exc()
                errors.append(tb)
                write_log("uvicorn 启动异常", tb)

        self._thread = threading.Thread(target=_run, name="fate-api", daemon=True)
        self._thread.start()
        self.port = port

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._server.started:
                break
            if errors:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("本地服务启动超时" + (f"：{errors[-1]}" if errors else ""))

        if errors:
            raise RuntimeError(f"本地服务启动失败：{errors[-1]}")

        # 健康检查，确保依赖加载完成
        while time.time() < deadline:
            try:
                resp = httpx.get(f"{self.base_url}/api/health", timeout=2.0)
                if resp.status_code == 200:
                    return self.base_url
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError("本地服务健康检查失败")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


server = LocalServer()

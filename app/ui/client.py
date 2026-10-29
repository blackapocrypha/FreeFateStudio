# -*- coding: utf-8 -*-
"""后端 HTTP 客户端（界面线程用同步 CRUD，流式对话用 QThread）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PySide6.QtCore import QThread, Signal


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(20.0, connect=5.0)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def health(self) -> Dict[str, Any]:
        try:
            r = httpx.get(self._url("/api/health"), timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}

    def list_conversations(self) -> List[Dict[str, Any]]:
        try:
            r = httpx.get(self._url("/api/conversations"), timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return []

    def create_conversation(self, title: str = "新对话") -> Optional[Dict[str, Any]]:
        try:
            r = httpx.post(self._url("/api/conversations"), json={"title": title},
                           timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return None

    def delete_conversation(self, cid: str) -> bool:
        try:
            r = httpx.delete(self._url(f"/api/conversations/{cid}"), timeout=self._timeout)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def messages(self, cid: str) -> List[Dict[str, Any]]:
        try:
            r = httpx.get(self._url(f"/api/conversations/{cid}/messages"),
                          timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return []

    # ---- 设置（模型 / API Key，落盘 .env）----
    def settings(self) -> Dict[str, Any]:
        try:
            r = httpx.get(self._url("/api/settings"), timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}

    def save_settings(self, model: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": model}
        if api_key:
            payload["api_key"] = api_key
        try:
            r = httpx.put(self._url("/api/settings"), json=payload,
                          timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}

    # ---- 个人信息（出生信息，落盘 SQLite）----
    def profile(self) -> Dict[str, Any]:
        try:
            r = httpx.get(self._url("/api/profile"), timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}

    def save_profile(
        self,
        birth_date: str,
        birth_time: str,
        gender: str,
        birth_place: str = "",
    ) -> Tuple[Dict[str, Any], str]:
        """返回 (档案快照, 错误信息)；成功时错误信息为空串。"""
        payload = {
            "birth_date": birth_date,
            "birth_time": birth_time,
            "gender": gender,
            "birth_place": birth_place,
        }
        try:
            r = httpx.put(self._url("/api/profile"), json=payload, timeout=self._timeout)
        except httpx.HTTPError:
            return {}, "保存失败：本地服务未响应"
        if r.status_code == 400:
            try:
                return {}, str(r.json().get("detail") or "输入有误")
            except ValueError:
                return {}, "输入有误"
        if r.status_code != 200:
            return {}, f"保存失败：HTTP {r.status_code}"
        return r.json(), ""

    def clear_profile(self) -> Dict[str, Any]:
        try:
            r = httpx.delete(self._url("/api/profile"), timeout=self._timeout)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return {}


class ChatWorker(QThread):
    """在子线程里读 SSE，通过信号把增量送回界面。"""

    token = Signal(str)
    tool = Signal(str)
    reset = Signal()
    meta = Signal(dict)
    error = Signal(str)
    saved = Signal()
    done = Signal()

    def __init__(self, base_url: str, conversation_id: str, message: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.conversation_id = conversation_id
        self.message = message
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        payload = {"conversation_id": self.conversation_id, "message": self.message}
        timeout = httpx.Timeout(30.0, connect=10.0, read=None)
        try:
            with httpx.Client(timeout=timeout) as client:
                with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
                    if resp.status_code != 200:
                        self.error.emit(f"服务返回 HTTP {resp.status_code}")
                        return
                    for line in resp.iter_lines():
                        if self._stop:
                            return
                        if not line or not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        kind = event.get("type")
                        if kind == "token":
                            self.token.emit(event.get("text", ""))
                        elif kind == "tool":
                            self.tool.emit(event.get("label") or event.get("name", ""))
                        elif kind == "reset":
                            self.reset.emit()
                        elif kind == "meta":
                            self.meta.emit(event)
                        elif kind == "saved":
                            self.saved.emit()
                        elif kind == "error":
                            self.error.emit(event.get("message", "未知错误"))
                        elif kind == "done":
                            break
        except httpx.HTTPError as exc:
            if not self._stop:
                self.error.emit(f"连接本地服务失败：{exc}")
        finally:
            self.done.emit()

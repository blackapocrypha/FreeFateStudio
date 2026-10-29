# -*- coding: utf-8 -*-
"""FastAPI 本地服务：会话 CRUD + SSE 流式对话。

界面与 Agent 之间只通过 HTTP 通信，因此后续把服务搬到远端，
桌面端只需换 base_url，不用改界面逻辑。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import agent as agent_mod
from . import profile as profile_mod
from .config import (
    APP_VERSION,
    api_key_ready,
    model_name,
    save_settings,
    settings_snapshot,
    thinking_enabled,
)
from .storage import store

app = FastAPI(title="FreeFateStudio Local API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# 数据模型
# ------------------------------------------------------------
class CreateConversation(BaseModel):
    title: str = "新对话"


class RenameConversation(BaseModel):
    title: str


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(min_length=1)


class SettingsRequest(BaseModel):
    """只支持 DeepSeek：模型名称 + API Key，落盘到 .env。"""

    model: Optional[str] = None
    api_key: Optional[str] = None
    thinking: Optional[bool] = None


class ProfileRequest(BaseModel):
    """本人出生信息：日期 + 时刻 + 性别，出生地可空（空则不启用真太阳时）。"""

    birth_date: str = ""
    birth_time: str = ""
    gender: str = ""
    birth_place: str = ""


# ------------------------------------------------------------
# 基础接口
# ------------------------------------------------------------
@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "version": APP_VERSION,
        "model": model_name(),
        "thinking": thinking_enabled(),
        "api_key_ready": api_key_ready(),
        "profile_ready": profile_mod.state()["configured"],
        "env_path": settings_snapshot()["env_path"],
        "stats": store.stats(),
    }


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    return settings_snapshot()


@app.put("/api/settings")
def put_settings(body: SettingsRequest) -> Dict[str, Any]:
    if body.model is not None and not body.model.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    snapshot = save_settings(body.model, body.api_key, body.thinking)
    snapshot["ok"] = True
    return snapshot


# ------------------------------------------------------------
# 个人信息（长期记忆）
# ------------------------------------------------------------
@app.get("/api/profile")
def get_profile() -> Dict[str, Any]:
    return profile_mod.state()


@app.put("/api/profile")
def put_profile(body: ProfileRequest) -> Dict[str, Any]:
    try:
        info = profile_mod.save(
            body.birth_date, body.birth_time, body.gender, body.birth_place
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    info["ok"] = True
    return info


@app.delete("/api/profile")
def delete_profile() -> Dict[str, Any]:
    store.clear_profile()
    info = profile_mod.state()
    info["ok"] = True
    return info


@app.get("/api/conversations")
def list_conversations() -> List[Dict[str, Any]]:
    return store.list_conversations()

@app.post("/api/conversations")
def create_conversation(body: Optional[CreateConversation] = None) -> Dict[str, Any]:
    return store.create_conversation((body.title if body else "新对话") or "新对话")


@app.patch("/api/conversations/{cid}")
def rename_conversation(cid: str, body: RenameConversation) -> Dict[str, Any]:
    if not store.get_conversation(cid):
        raise HTTPException(status_code=404, detail="会话不存在")
    store.rename_conversation(cid, body.title)
    return store.get_conversation(cid)


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> Dict[str, Any]:
    ok = store.delete_conversation(cid)
    agent_mod.clear_thread(cid)
    return {"deleted": ok, "id": cid}


@app.get("/api/conversations/{cid}/messages")
def get_messages(cid: str) -> List[Dict[str, Any]]:
    return store.get_messages(cid)


# ------------------------------------------------------------
# SSE 对话
# ------------------------------------------------------------
def _sse(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    conv = store.get_conversation(req.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="消息不能为空")

    cid = req.conversation_id
    store.add_message(cid, "user", text)
    new_title = store.maybe_auto_title(cid, text)

    async def gen() -> AsyncIterator[str]:
        yield _sse({
            "type": "meta",
            "conversation_id": cid,
            "title": new_title or conv["title"],
        })

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            try:
                for event in agent_mod.stream_chat(cid, text):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:  # 兜底，避免线程静默死掉
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "__end__"})

        threading.Thread(target=worker, daemon=True).start()

        parts: List[str] = []
        error: Optional[str] = None
        while True:
            event = await queue.get()
            if event.get("type") == "__end__":
                break
            if event["type"] == "token":
                parts.append(event["text"])
            elif event["type"] == "reset":
                parts.clear()
            elif event["type"] == "error":
                error = event["message"]
            yield _sse(event)

        content = "".join(parts).strip()
        if not content and error:
            content = f"（请求失败：{error}）"
        if content:
            saved = store.add_message(cid, "assistant", content)
            yield _sse({"type": "saved", "message_id": saved["id"]})
        yield _sse({"type": "done"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

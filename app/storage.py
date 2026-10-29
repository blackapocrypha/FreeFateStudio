# -*- coding: utf-8 -*-
"""会话存储：SQLite。

对话内容存在两张表里：
  conversations  会话元信息（标题、时间）
  messages       每一轮消息（role + content），用于界面回放与历史检索
  profile        本人出生信息（单行，id=1），作为「我」的长期记忆

Agent 自己的对话记忆不在这里——由 LangGraph 的 SqliteSaver 按 thread_id
（即 conversation_id）单独存 checkpoint.db，职责分离：
  fate.db       用户可见的历史记录
  checkpoint.db Agent 的图状态（可随时丢弃重建）
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import DB_PATH

_LOCK = threading.RLock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '新对话',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    tool        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at DESC);
CREATE TABLE IF NOT EXISTS profile (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    birth_date  TEXT NOT NULL DEFAULT '',
    birth_time  TEXT NOT NULL DEFAULT '',
    gender      TEXT NOT NULL DEFAULT '',
    birth_place TEXT NOT NULL DEFAULT '',
    updated_at  TEXT
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path=DB_PATH) -> None:
        self.path = str(path)
        with _LOCK:
            conn = self._connect()
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ---------------- 会话 ----------------
    def create_conversation(self, title: str = "新对话") -> Dict[str, Any]:
        cid = uuid.uuid4().hex
        ts = _now()
        with _LOCK:
            conn = self._connect()
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES(?,?,?,?)",
                (cid, title, ts, ts),
            )
            conn.commit()
            conn.close()
        return {"id": cid, "title": title, "created_at": ts, "updated_at": ts}

    def list_conversations(self, limit: int = 300) -> List[Dict[str, Any]]:
        with _LOCK:
            conn = self._connect()
            rows = conn.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at,"
                " (SELECT COUNT(*) FROM messages m WHERE m.conv_id=c.id) AS msg_count"
                " FROM conversations c ORDER BY c.updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def get_conversation(self, cid: str) -> Optional[Dict[str, Any]]:
        with _LOCK:
            conn = self._connect()
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
            conn.close()
        return dict(row) if row else None

    def rename_conversation(self, cid: str, title: str) -> None:
        with _LOCK:
            conn = self._connect()
            conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title.strip()[:60] or "新对话", _now(), cid),
            )
            conn.commit()
            conn.close()

    def delete_conversation(self, cid: str) -> bool:
        with _LOCK:
            conn = self._connect()
            cur = conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
            conn.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
            conn.commit()
            conn.close()
        return cur.rowcount > 0

    def touch_conversation(self, cid: str) -> None:
        with _LOCK:
            conn = self._connect()
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), cid))
            conn.commit()
            conn.close()

    def maybe_auto_title(self, cid: str, text: str) -> Optional[str]:
        """首个问题自动作为标题（仅当标题还是默认值时）。"""
        conv = self.get_conversation(cid)
        if not conv or conv["title"] != "新对话":
            return None
        title = " ".join(text.strip().split())[:24] or "新对话"
        self.rename_conversation(cid, title)
        return title

    # ---------------- 消息 ----------------
    def add_message(self, cid: str, role: str, content: str,
                    tool: Optional[str] = None) -> Dict[str, Any]:
        ts = _now()
        with _LOCK:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO messages(conv_id, role, content, tool, created_at) VALUES(?,?,?,?,?)",
                (cid, role, content, tool, ts),
            )
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (ts, cid))
            conn.commit()
            mid = cur.lastrowid
            conn.close()
        return {"id": mid, "conv_id": cid, "role": role,
                "content": content, "tool": tool, "created_at": ts}

    def get_messages(self, cid: str) -> List[Dict[str, Any]]:
        with _LOCK:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, role, content, tool, created_at FROM messages "
                "WHERE conv_id=? ORDER BY id ASC",
                (cid,),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with _LOCK:
            conn = self._connect()
            c = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            m = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            conn.close()
        return {"conversations": c, "messages": m}

    # ---------------- 个人信息（单行） ----------------
    def get_profile(self) -> Optional[Dict[str, Any]]:
        """返回已保存的出生信息；从未填写过返回 None。"""
        with _LOCK:
            conn = self._connect()
            row = conn.execute("SELECT * FROM profile WHERE id=1").fetchone()
            conn.close()
        return dict(row) if row else None

    def save_profile(self, data: Dict[str, str]) -> Dict[str, Any]:
        """整条覆盖写入（程序只有一个「我」，不需要多记录）。"""
        ts = _now()
        with _LOCK:
            conn = self._connect()
            conn.execute(
                "INSERT INTO profile(id, birth_date, birth_time, gender, birth_place, updated_at)"
                " VALUES(1,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " birth_date=excluded.birth_date,"
                " birth_time=excluded.birth_time,"
                " gender=excluded.gender,"
                " birth_place=excluded.birth_place,"
                " updated_at=excluded.updated_at",
                (
                    data.get("birth_date", ""),
                    data.get("birth_time", ""),
                    data.get("gender", ""),
                    data.get("birth_place", ""),
                    ts,
                ),
            )
            conn.commit()
            conn.close()
        return {"id": 1, **data, "updated_at": ts}

    def clear_profile(self) -> None:
        with _LOCK:
            conn = self._connect()
            conn.execute("DELETE FROM profile WHERE id=1")
            conn.commit()
            conn.close()


store = Store()

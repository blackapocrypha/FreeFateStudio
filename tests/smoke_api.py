# -*- coding: utf-8 -*-
"""后端自检：启动进程内服务，跑一次真实 SSE 对话，再验证落库与删除。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402


def main() -> int:
    base = server.start()
    print("服务已启动:", base)

    health = httpx.get(f"{base}/api/health", timeout=5).json()
    print("健康检查:", health)

    conv = httpx.post(f"{base}/api/conversations", json={}, timeout=5).json()
    cid = conv["id"]
    print("新建会话:", cid)

    payload = {"conversation_id": cid,
               "message": "男，1990年5月12日下午两点半，山东临沂。简单看下财运"}
    tokens = 0
    tools = []
    error = None
    with httpx.Client(timeout=httpx.Timeout(30, read=None)) as client:
        with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
            print("HTTP", resp.status_code)
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if ev["type"] == "token":
                    tokens += 1
                elif ev["type"] == "tool":
                    tools.append(ev["label"])
                elif ev["type"] == "error":
                    error = ev["message"]
                    print("错误:", error)
                elif ev["type"] == "saved":
                    print("已落库 message_id:", ev["message_id"])

    print(f"增量分片 {tokens} 个，调用工具 {tools}")
    msgs = httpx.get(f"{base}/api/conversations/{cid}/messages", timeout=5).json()
    print("库内消息:", [(m["role"], len(m["content"])) for m in msgs])
    if msgs:
        print("回答开头:", msgs[-1]["content"][:120].replace("\n", " "))

    # 多轮：验证 checkpoint 记忆生效
    with httpx.Client(timeout=httpx.Timeout(30, read=None)) as client:
        with client.stream("POST", f"{base}/api/chat",
                           json={"conversation_id": cid,
                                 "message": "我刚才说的出生时间是什么？只回答时间。"}) as resp:
            text = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    if ev["type"] == "token":
                        text.append(ev["text"])
    print("多轮回答:", "".join(text)[:100].replace("\n", " "))

    print("删除会话:", httpx.delete(f"{base}/api/conversations/{cid}", timeout=5).json())
    server.stop()
    print("\n后端自检完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""真实模型下的压缩联调：把窗口调小，几轮内必然触发压缩。

用法：python tests/live_compaction.py
会真的调用一次摘要模型（成本约几千 token），用完把测试会话删掉。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 必须在导入 app 之前压窗口，否则用默认 128K 要聊很久才会触发
os.environ["FATE_CONTEXT_WINDOW"] = "20000"

import httpx  # noqa: E402

from app.server import server  # noqa: E402

QUESTIONS = [
    "男，1990年5月12日下午两点半，山东临沂。先看事业方向",
    "那财运结构怎么样？正财和偏财各说明下",
    "再说说配偶宫和婚恋应期",
]


def turn(base: str, cid: str, message: str) -> dict:
    seen = {"context": [], "compacting": 0, "compacted": [], "error": [], "text": []}
    with httpx.Client(timeout=httpx.Timeout(60, read=None)) as client:
        with client.stream("POST", f"{base}/api/chat",
                           json={"conversation_id": cid, "message": message}) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                kind = ev.get("type")
                if kind == "context":
                    seen["context"].append(ev)
                elif kind == "compacting":
                    seen["compacting"] += 1
                elif kind == "compacted":
                    seen["compacted"].append(ev)
                elif kind == "error":
                    seen["error"].append(ev.get("message"))
                elif kind == "token":
                    seen["text"].append(ev.get("text", ""))
    return seen


def main() -> int:
    base = server.start()
    conv = httpx.post(f"{base}/api/conversations", json={"title": "[测试] 压缩联调"}, timeout=10).json()
    cid = conv["id"]
    print("会话:", cid, "窗口强制 20000\n")

    total_compacted = 0
    for i, q in enumerate(QUESTIONS, 1):
        got = turn(base, cid, q)
        last = got["context"][-1] if got["context"] else {}
        print(f"第{i}轮 回答 {sum(len(t) for t in got['text'])} 字 | "
              f"上下文 {last.get('tokens')}/{last.get('window')} "
              f"({last.get('percent')}%) 阈值 {last.get('threshold')} | "
              f"compacting {got['compacting']} | compacted {len(got['compacted'])}")
        for ev in got["compacted"]:
            if ev.get("error"):
                print("   压缩报错:", ev["error"])
            elif ev.get("skipped"):
                print("   跳过:", ev.get("reason"))
            else:
                print(f"   压缩 {ev['before']} -> {ev['after']} tokens，"
                      f"摘要 {ev['summarized']} 条，保留 {ev['kept']} 条")
        if got["error"]:
            print("   错误:", got["error"])
        total_compacted += len([e for e in got["compacted"] if not e.get("skipped")])

    after = httpx.get(f"{base}/api/conversations/{cid}/context", timeout=10).json()
    print("\n最终上下文:", after.get("tokens"), "/", after.get("window"))
    print("压缩次数:", total_compacted)
    print("结论:", "通过" if total_compacted >= 1 and after.get("tokens", 0) < 20000 else "未触发压缩")

    httpx.delete(f"{base}/api/conversations/{cid}", timeout=10)
    server.stop()
    return 0 if total_compacted >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""端到端验证：档案填好后，用户只说「我」是否直接按档案排盘。

会真实调用一次 DeepSeek，跑完删掉测试会话并还原档案。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402
from app.storage import store  # noqa: E402

QUESTION = "我今年的运势怎么样？妻财子禄寿大致说说，别太长"


def chat(base: str, cid: str, text: str):
    tokens: list[str] = []
    tools: list[str] = []
    error = None
    with httpx.Client(timeout=httpx.Timeout(40, read=None)) as client:
        with client.stream(
            "POST", f"{base}/api/chat", json={"conversation_id": cid, "message": text}
        ) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                kind = ev.get("type")
                if kind == "token":
                    tokens.append(ev["text"])
                elif kind == "tool":
                    tools.append(f'{ev["label"]}{ev.get("args") or ""}')
                elif kind == "error":
                    error = ev["message"]
    return "".join(tokens), tools, error


def main() -> int:
    backup = store.get_profile()
    base = server.start()
    cid = None
    try:
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "男",
                "birth_place": "临沂",
            },
            timeout=10,
        )
        assert r.status_code == 200, r.text

        cid = httpx.post(f"{base}/api/conversations", json={}, timeout=5).json()["id"]
        answer, tools, error = chat(base, cid, QUESTION)
        print("工具调用:", tools or "无")
        print("错误:", error or "无")
        print("回答开头:", answer[:180].replace("\n", " "))

        assert not error, error
        assert answer.strip(), "回答为空"
        assert any("排盘" in t for t in tools), f"未按档案排盘，工具={tools}"
        # 关键：不应再追问出生信息
        for bad in ("请提供你的出生", "请问你的出生", "你的出生时间是", "你是男是女", "请告诉我你的性别"):
            assert bad not in answer, f"仍在追问基础信息：{bad}\n{answer[:300]}"
        assert "1990" in answer or "庚午" in answer or "庚" in answer, "回答未体现 1990 年生人"

        # 追问方向时不应重复排盘
        answer2, tools2, error2 = chat(base, cid, "那我今年的事业运呢？")
        print("第二轮工具调用:", tools2 or "无")
        assert not error2, error2
        assert answer2.strip()

        print("--- 首答节选 ---")
        print(answer[:700])
    finally:
        if cid:
            httpx.delete(f"{base}/api/conversations/{cid}", timeout=10)
        if backup:
            httpx.put(
                f"{base}/api/profile",
                json={
                    "birth_date": backup["birth_date"],
                    "birth_time": backup["birth_time"],
                    "gender": backup["gender"],
                    "birth_place": backup["birth_place"],
                },
                timeout=10,
            )
            print("已还原原档案")
        else:
            httpx.delete(f"{base}/api/profile", timeout=10)
            print("原无档案，保持为空")
        server.stop()
    print("通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

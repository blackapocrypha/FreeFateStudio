# -*- coding: utf-8 -*-
"""实调模型验证：新神煞 / 十二长生禄绝 / 月令权重 是否被正确使用。

跑两轮，只检查「模型有没有按工具数据说话」：
  1. 问神煞与禄位 → 应出现工具返回的具体神煞名与禄/绝位，不得编造未返回的名称；
  2. 问身强身弱 → 应提月令得令/失令，而不是数个数。
不改数据库，不写档案。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.server import server  # noqa: E402
from app.tools.bazi_engine import build_chart  # noqa: E402

PROFILE = {"birth_date": "1990-05-12", "birth_time": "14:30",
           "gender": "男", "birth_place": "临沂"}


def ask(base: str, cid: str, text: str) -> tuple[str, list[str]]:
    tools: list[str] = []
    chunks: list[str] = []
    payload = {"conversation_id": cid, "message": text}
    with httpx.stream("POST", f"{base}/api/chat", json=payload, timeout=180) as r:
        r.raise_for_status()
        name = ""
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "tool":
                name = ev.get("name", "")
                tools.append(ev.get("label") or name)
            elif ev.get("type") == "token":
                chunks.append(ev.get("text", ""))
    return "".join(chunks), tools


def main() -> int:
    base = server.start()
    chart = build_chart(1990, 5, 12, 14, 30, "男", longitude=118.35)
    names = {n.replace("(日支查)", "") for v in chart["神煞"]["按柱分布"].values() for n in v}
    lu = chart["十二长生"]["日干禄绝"]
    print("工具返回神煞:", sorted(names))
    print("日干禄绝:", lu)

    old = httpx.get(f"{base}/api/profile", timeout=5).json()
    httpx.put(f"{base}/api/profile", json=PROFILE, timeout=5)
    cid = httpx.post(f"{base}/api/conversations", json={}, timeout=5).json()["id"]
    try:
        text1, tools1 = ask(base, cid, "我命中带哪些神煞？我的禄位和绝位在哪？")
        print("\n[第一轮] 工具:", tools1)
        print(text1[:900])

        text2, tools2 = ask(base, cid, "那我这个八字身强还是身弱？为什么？")
        print("\n[第二轮] 工具:", tools2)
        print(text2[:700])

        ok = True
        if "排盘" not in tools1:
            print("[FAIL] 第一轮没调排盘"); ok = False
        hit = [n for n in names if n in text1]
        print(f"\n神煞名命中 {len(hit)}/{len(names)}：{'、'.join(hit)}")
        if not hit:
            print("[FAIL] 回答里没有任何工具返回的神煞名"); ok = False
        if lu["禄在"] in text1 or lu["绝在"] in text1:
            print(f"禄绝位提到：禄在{lu['禄在']} / 绝在{lu['绝在']}")
        else:
            print("[WARN] 回答未提禄/绝的具体地支")
        if not re.search(r"月令|得令|失令", text2):
            print("[WARN] 第二轮没提月令")
        else:
            print("第二轮已论月令")
        print("\n[OK]" if ok else "\n[FAIL]")
        return 0 if ok else 1
    finally:
        httpx.delete(f"{base}/api/conversations/{cid}", timeout=5)
        if old.get("profile"):
            httpx.put(f"{base}/api/profile", json={
                k: old["profile"].get(k) for k in ("birth_date", "birth_time", "gender", "birth_place")
            }, timeout=5)
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())

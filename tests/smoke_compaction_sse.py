# -*- coding: utf-8 -*-
"""压缩链路的端到端自检（走真实 HTTP + SSE，模型换成假的，不联网）。

验的是「压缩事件能不能从 agent 一路传到界面层」：
  1. 每次对话都带 context 事件
  2. 超阈值时先发 compacting，再发 compacted
  3. 压缩后同一会话的 context 接口返回的 token 明显下降
  4. 压缩过的会话还能继续聊，消息照常落库

用临时 checkpoint 库，不碰真实数据目录。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DEEPSEEK_API_KEY"] = "sk-fake-for-compaction-test"
os.environ["FATE_CONTEXT_WINDOW"] = "8192"

from langchain_core.messages import AIMessage  # noqa: E402

from app import agent as agent_mod  # noqa: E402
from app import compaction  # noqa: E402

OK = 0
FAIL = 0
TMP = Path(tempfile.mkdtemp(prefix="ffs_sse_"))


def check(cond: bool, label: str, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"[OK] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label} {detail}")


class FakeModel:
    """够用就好：bind_tools 原样返回，invoke 回一段长中文。"""

    def __init__(self, chars: int = 2200) -> None:
        self.chars = chars
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        return AIMessage(content="丙火日主，月令寅木生扶。" * (self.chars // 12))


class FakeSummarizer:
    """摘要器返回一段很短的结构化摘要（真实摘要也就几百字）。"""

    def invoke(self, messages):
        return AIMessage(content="## 关键数据\n四柱：甲子 乙丑 丙寅 丁卯，日主丙火身强。" * 6)


# 让图与摘要都用假模型；checkpoint 指向临时库
fake = FakeModel()
agent_mod.build_model = lambda: fake
compaction._default_llm = lambda: FakeSummarizer()
compaction.RESERVE_TOKENS = 1024
compaction.KEEP_RECENT_TOKENS = 2000
agent_mod.CKPT_PATH = TMP / "checkpoint.db"
agent_mod._GRAPH = None
agent_mod._GRAPH_REV = -1
agent_mod._SAVER = None
agent_mod._SAVER_CONN = None

import httpx  # noqa: E402

from app.server import server  # noqa: E402

QUESTIONS = [
    "第一问：看看我的事业方向",
    "第二问：财运结构怎么样",
    "第三问：配偶宫与婚恋应期",
    "第四问：适合什么行业",
    "第五问：近几年哪年动得大",
    "第六问：体质上要注意什么",
    "第七问：还有别的吗",
]


def turn(base: str, cid: str, message: str) -> dict:
    seen = {"context": [], "compacting": 0, "compacted": [], "error": [], "chars": 0}
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
                    seen["chars"] += len(ev.get("text", ""))
    return seen


def main() -> int:
    base = server.start()
    conv = httpx.post(f"{base}/api/conversations", json={"title": "[自检] 压缩"}, timeout=10).json()
    cid = conv["id"]

    rounds = []
    for i, q in enumerate(QUESTIONS, 1):
        got = turn(base, cid, q)
        rounds.append(got)
        print(f"第{i}轮",
              [(e["tokens"], e["over"]) for e in got["context"]],
              "compacting", got["compacting"])
        if got["error"]:
            print("   错误:", got["error"])

    check(all(r["context"] for r in rounds), "每轮都带 context 事件")
    check(all(not r["error"] for r in rounds), "全程无错误",
          str([r["error"] for r in rounds if r["error"]]))
    check(rounds[0]["context"][-1]["tokens"] > 1000, "系统提示已计入占用")

    fire = next((i for i, r in enumerate(rounds) if r["compacting"]), None)
    check(fire is not None, "多轮之内触发过压缩",
          str([r["compacting"] for r in rounds]))
    if fire is None:
        print()
        print(f"通过 {OK} 项，失败 {FAIL} 项")
        httpx.delete(f"{base}/api/conversations/{cid}", timeout=10)
        server.stop()
        return 1

    hit = rounds[fire]
    done = [e for e in hit["compacted"] if not e.get("skipped")]
    check(bool(done), "产出有效压缩结果", str(hit["compacted"]))
    if done:
        check(done[0]["after"] < done[0]["before"], "压缩后 token 下降",
              f"{done[0]['before']} -> {done[0]['after']}")
    after_tokens = hit["context"][1]["tokens"] if len(hit["context"]) > 2 else None
    check(after_tokens is not None and after_tokens < 7168,
          "压缩后立刻回落到阈值以下", str(after_tokens))

    # 压缩后的下一轮不该再压（否则等于每轮都烧一次摘要请求）
    if fire + 1 < len(rounds):
        nxt = rounds[fire + 1]
        check(nxt["compacting"] == 0, "紧接着的下一轮不再压缩",
              str([e["tokens"] for e in nxt["context"]]))

    # 压缩后还能继续聊
    tail = turn(base, cid, "最后一问：还有别的要注意的吗")
    check(not tail["error"], "压缩后仍能正常对话", str(tail["error"]))

    snap = httpx.get(f"{base}/api/conversations/{cid}/context", timeout=10).json()
    print("最终上下文:", snap.get("tokens"), "/", snap.get("window"))
    check(snap.get("tokens", 0) > 0, "context 接口可用")

    msgs = httpx.get(f"{base}/api/conversations/{cid}/messages", timeout=10).json()
    check(len(msgs) >= len(rounds), "多轮问答照常落库", f"{len(msgs)} 条")

    httpx.delete(f"{base}/api/conversations/{cid}", timeout=10)
    server.stop()
    print()
    print(f"通过 {OK} 项，失败 {FAIL} 项")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

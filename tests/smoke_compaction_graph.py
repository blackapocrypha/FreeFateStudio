# -*- coding: utf-8 -*-
"""压缩与图状态的集成自检（不联网）。

验证真实 LangGraph 图上的行为：
  1. 超窗时 stream_chat 先发 context / compacting / compacted 事件
  2. checkpoint 里的消息确实被替换成「摘要 + 近期原文」，旧消息清零
  3. 压缩后同一会话不再触发压缩（不会每轮都压）
  4. 有 API Key 才走图；无 Key 时只回 error 事件

用的是临时 checkpoint 库与假模型，不碰真实数据目录。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DEEPSEEK_API_KEY"] = "sk-test-placeholder-0001"
os.environ["FATE_CONTEXT_WINDOW"] = "20000"

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app import agent as agent_mod  # noqa: E402
from app import compaction  # noqa: E402

OK = 0
FAIL = 0
TMP = Path(tempfile.mkdtemp(prefix="ffs_compact_"))


def check(cond: bool, label: str, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"[OK] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label} {detail}")


class FakeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return AIMessage(content="## 关键数据（命盘 / 卦象 / 日期）\n四柱：甲子 乙丑 丙寅 丁卯")


# ---- 指向临时库，避免动真实 checkpoint ----
agent_mod.CKPT_PATH = TMP / "checkpoint.db"
agent_mod._GRAPH = None
agent_mod._SAVER = None
agent_mod._SAVER_CONN = None

compaction._default_llm = lambda: FakeLLM()
compaction.KEEP_RECENT_TOKENS = 2000

graph = agent_mod.get_graph()
config = {"configurable": {"thread_id": "compact-thread"}}

# 造一段很长的历史：20 轮，每轮约 1000 字
history = []
for i in range(20):
    history.append(HumanMessage(content=f"第{i}轮：我生于1995年3月8日上午10点20分，男，出生地临沂。" * 6))
    history.append(AIMessage(content=f"第{i}轮回答：日主丙火，月令寅木生扶，身强。结论见下。" * 8))
graph.update_state(config, {"messages": history})

before = agent_mod.context_snapshot("compact-thread")
check(before["tokens"] > before["threshold"], "历史已超过压缩阈值",
      f"{before['tokens']} vs {before['threshold']}")
check(compaction.needs_compaction(before), "needs_compaction 为真")

events = list(agent_mod._compact_if_needed(graph, config))
kinds = [e["type"] for e in events]
check(kinds[0] == "context", "先发 context 事件", str(kinds))
check("compacting" in kinds, "发出 compacting 事件", str(kinds))
check("compacted" in kinds, "发出 compacted 事件", str(kinds))

done = next(e for e in events if e["type"] == "compacted")
check(done.get("skipped") is False, "压缩未被跳过", str(done))
check(done["after"] < done["before"], "token 确有下降",
      f"{done['before']} -> {done['after']}")

after_messages = graph.get_state(config).values["messages"]
check(len(after_messages) < len(history), "消息条数变少",
      f"{len(history)} -> {len(after_messages)}")
check(
    after_messages[0].type == "human" and "历史对话摘要" in after_messages[0].content,
    "首条为摘要消息",
)
check(
    after_messages[-1].content.startswith("第19轮回答"),
    "最后一条原文保留",
    after_messages[-1].content[:20],
)
check(
    all(m.type in ("human", "ai") for m in after_messages),
    "压缩后没有孤立的工具消息",
)

# 压缩后同一会话不该再触发
again = list(agent_mod._compact_if_needed(graph, config))
again_kinds = [e["type"] for e in again]
check("compacting" not in again_kinds, "压缩后不再立刻重复压缩", str(again_kinds))
check(again[0]["tokens"] < again[0]["threshold"], "压缩后回落到阈值以下",
      f"{again[0]['tokens']} vs {again[0]['threshold']}")

# 摘要内容确实进了上下文
flat = "\n".join(str(m.content) for m in after_messages)
check("甲子 乙丑 丙寅 丁卯" in flat, "摘要正文写入 checkpoint")

# 无 Key 时只回 error，不去调图
saved = os.environ.get("DEEPSEEK_API_KEY")
os.environ["DEEPSEEK_API_KEY"] = "xxx"
errs = [e for e in agent_mod.stream_chat("compact-thread", "你好") if e["type"] == "error"]
check(len(errs) == 1 and "API Key" in errs[0]["message"], "未配置 Key 时直接报错")
os.environ["DEEPSEEK_API_KEY"] = saved or ""

print()
print(f"通过 {OK} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)

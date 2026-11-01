# -*- coding: utf-8 -*-
"""上下文压缩自检（不联网）。

覆盖：
  1. token 估算：中文按字、英文按字符，单调递增
  2. 窗口与阈值：contextTokens > window - reserveTokens 才算超窗
  3. 切点必须落在用户消息上，不能切开工具调用与工具结果
  4. 末尾悬空工具调用被清掉
  5. 压缩后 = 「摘要 + 确认」+ 最近原文，且确实变小
  6. 旧消息过长时走分段摘要（map-reduce），摘要调用次数 > 1
  7. 没有可压内容时原样返回（skipped）
  8. 压缩结果能直接喂回 add_messages（无孤儿 tool 消息）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.messages import (  # noqa: E402
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages  # noqa: E402

from app import compaction  # noqa: E402

OK = 0
FAIL = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print(f"[OK] {label}")
    else:
        FAIL += 1
        print(f"[FAIL] {label} {detail}")


class FakeLLM:
    """记录调用次数与入参，返回带序号的假摘要。"""

    def __init__(self) -> None:
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=f"## 用户与档案\n假摘要#{len(self.calls)}")


def big_text(chars: int, seed: str = "命") -> str:
    return (seed * chars)[:chars]


# ------------------------------------------------------------
# 1. token 估算
# ------------------------------------------------------------
cjk = compaction.estimate_tokens("甲乙丙丁戊己庚辛壬癸")
ascii_ = compaction.estimate_tokens("abcdefghij")
check(cjk > ascii_, "中文单位字符的 token 高于英文", f"{cjk} vs {ascii_}")
check(compaction.estimate_tokens("") == 0, "空串为 0")
check(
    compaction.estimate_tokens(big_text(200)) > compaction.estimate_tokens(big_text(100)),
    "估算随长度单调递增",
)

# ------------------------------------------------------------
# 2. 窗口与阈值
# ------------------------------------------------------------
os.environ.pop("FATE_CONTEXT_WINDOW", None)
os.environ["FATE_MODEL"] = "deepseek-v4-flash"
check(compaction.context_window() == 128_000, "默认窗口 128K", str(compaction.context_window()))
os.environ["FATE_MODEL"] = "some-32k-model"
check(compaction.context_window() == 32_768, "模型名带 32k 时取 32K")
os.environ["FATE_CONTEXT_WINDOW"] = "65536"
check(compaction.context_window() == 65_536, ".env 覆盖优先")
os.environ.pop("FATE_CONTEXT_WINDOW", None)

state = compaction.context_state([HumanMessage(content="hi")], extra_tokens=0)
check(state["threshold"] == state["window"] - compaction.reserve_tokens(), "阈值 = 窗口 - 预留")
check(state["over"] is False, "小历史不触发压缩")
check(compaction.needs_compaction({**state, "over": True}) is True, "over 时触发")
check(
    compaction.needs_compaction({**state, "over": True, "enabled": False}) is False,
    "关闭开关后不触发",
)

# ------------------------------------------------------------
# 3/4. 切点与悬空调用
# ------------------------------------------------------------
old_keep = compaction.KEEP_RECENT_TOKENS
compaction.KEEP_RECENT_TOKENS = 200

history = []
for i in range(12):
    history.append(HumanMessage(content=f"第{i}个问题：" + big_text(120)))
    history.append(AIMessage(content="回答：" + big_text(120)))
history.append(HumanMessage(content="最后一句"))

idx = compaction.split_index(history, 200)
check(0 < idx < len(history), "切点落在中间", f"idx={idx}")
check(history[idx].type == "human", "切点是用户消息", history[idx].type)
check(compaction.messages_tokens(history[idx:]) <= 400, "保留区不显著超出 keepRecent")

# 工具调用与结果跨越切点时，也必须退到用户消息
tool_seq = [
    HumanMessage(content=big_text(400)),
    AIMessage(content="", tool_calls=[{"name": "get_bazi_chart", "args": {"x": 1}, "id": "c1"}]),
    ToolMessage(content=big_text(400), tool_call_id="c1", name="get_bazi_chart"),
    AIMessage(content=big_text(200)),
    HumanMessage(content="下一问"),
    AIMessage(content="答"),
]
idx2 = compaction.split_index(tool_seq, 120)
check(tool_seq[idx2].type == "human", "切点避开工具结果", tool_seq[idx2].type)

dangling = [HumanMessage(content="问"), AIMessage(
    content="", tool_calls=[{"name": "cast_liuyao", "args": {}, "id": "c9"}]
)]
check(len(compaction.trim_dangling(dangling)) == 1, "末尾悬空工具调用被清掉")

# ------------------------------------------------------------
# 5. 正常压缩
# ------------------------------------------------------------
compaction.KEEP_RECENT_TOKENS = 300
llm = FakeLLM()
new_messages, info = compaction.compact(history, llm)
check(info["skipped"] is False, "压缩未跳过", str(info))
check(len(llm.calls) >= 1, "调用了一次摘要模型")
first = new_messages[0]
check(first.type == "human" and "历史对话摘要" in first.content, "首条是摘要消息")
check(new_messages[1].type == "ai", "第二条是确认消息")
check(new_messages[-1].content == "最后一句", "最后一条用户消息原样保留")
check(info["after"] < info["before"], "压缩后 token 减少",
      f"{info['before']} -> {info['after']}")
check(info["summarized"] + info["kept"] == len(history), "条数守恒")

# 摘要只送旧消息，最近原文不进摘要请求
sent = "\n".join(str(m.content) for m in llm.calls[0])
check("最后一句" not in sent, "最近原文没有被送进摘要请求")

# ------------------------------------------------------------
# 6. map-reduce
# ------------------------------------------------------------
compaction.KEEP_RECENT_TOKENS = 400
huge = []
for _ in range(3):
    huge.append(HumanMessage(content=big_text(30000)))
    huge.append(AIMessage(content=big_text(30000)))
# 窗口调小，让待压内容真的超过单次摘要预算（每条渲染后被截到 6000 字符）
os.environ["FATE_CONTEXT_WINDOW"] = "16000"
llm2 = FakeLLM()
_, info2 = compaction.compact(huge, llm2)
os.environ.pop("FATE_CONTEXT_WINDOW", None)
check(len(llm2.calls) > 1, "超长历史走分段摘要", f"calls={len(llm2.calls)}")
check(info2["skipped"] is False, "分段后仍产出摘要")
check(llm2.calls[0][0].type == "system", "摘要是独立请求（system + human）")

# ------------------------------------------------------------
# 7. 无可压内容
# ------------------------------------------------------------
only_recent = [HumanMessage(content="只有一句"), AIMessage(content="只有一答")]
_, info3 = compaction.compact(only_recent, FakeLLM())
check(info3["skipped"] is True, "全是近期原文时不压")
check(len(compaction.compact(only_recent, FakeLLM())[0]) == 2, "原样返回")

# ------------------------------------------------------------
# 8. 能喂回 add_messages
# ------------------------------------------------------------
merged = add_messages([], new_messages)
check(len(merged) == len(new_messages), "压缩结果可与 add_messages 合并")
check(
    all(m.type in ("human", "ai") for m in merged),
    "压缩后不含孤立工具消息",
)

compaction.KEEP_RECENT_TOKENS = old_keep

print()
print(f"通过 {OK} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)

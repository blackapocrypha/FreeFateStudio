# -*- coding: utf-8 -*-
"""上下文压缩（Compaction）：接近窗口上限时，把早期对话压成结构化摘要。

参考 Pi Agent 的做法，不是简单截断，而是三步：
  1. 摘要 —— 用一次独立的 LLM 请求，把待丢弃的旧消息压成结构化摘要；
  2. 保留近期原文 —— 最近 keepRecentTokens 内的消息一字不改地留着，
     保证模型还看得见用户的原话与工具返回的原始数据；
  3. 维护轨迹 —— 摘要里单独记录「已经调过哪些工具、拿到了什么关键数据」，
     下一轮不必重复排盘、重复起卦。

触发条件与 Pi Agent 一致：
    contextTokens > contextWindow - reserveTokens

本模块只负责「算出该压什么、压成什么」，不改动图状态；
落库（update_state）由 agent 层完成，这样压缩逻辑可以单独测试。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

# ------------------------------------------------------------
# 可调参数（均可由 .env 覆盖，默认值与 Pi Agent 相同）
# ------------------------------------------------------------
RESERVE_TOKENS = int(os.getenv("FATE_RESERVE_TOKENS", "16384") or 16384)
KEEP_RECENT_TOKENS = int(os.getenv("FATE_KEEP_RECENT_TOKENS", "20000") or 20000)
ENABLED = (os.getenv("FATE_COMPACTION", "1") or "1").strip() not in ("0", "false", "False")

# 常见模型窗口。模型名命中即取对应值，否则用 DEFAULT_WINDOW。
DEFAULT_WINDOW = 128_000
_WINDOW_HINTS: Tuple[Tuple[str, int], ...] = (
    ("1m", 1_000_000),
    ("128k", 128_000),
    ("64k", 64_000),
    ("32k", 32_768),
    ("16k", 16_384),
)

# 单条消息渲染进摘要请求时的截断长度。命盘的 JSON 一般 3000~8000 字符，
# 截到 2000 会把大运、神煞这些后续要用的数据切掉，所以放宽到 6000。
_RENDER_LIMIT = 6000

SUMMARY_HEADER = (
    "【历史对话摘要】以下内容由系统对较早的对话自动压缩生成，用于延续上下文。\n"
    "其中的事实、数据与结论依然有效；不必向用户复述摘要本身，也不要提「根据摘要」这类说法。\n\n"
)

SUMMARY_FOOTER = "\n\n【摘要结束】以下是最近的原始对话，可直接引用。"


# ------------------------------------------------------------
# 窗口与 token 估算
# ------------------------------------------------------------
def context_window(model: Optional[str] = None) -> int:
    """模型上下文窗口。优先级：环境变量 > 模型名里的 128k/64k 之类的标记 > 默认值。"""
    override = (os.getenv("FATE_CONTEXT_WINDOW") or "").strip()
    if override.isdigit() and int(override) > 4096:
        return int(override)
    low = (model or os.getenv("FATE_MODEL") or "").lower()
    for hint, size in _WINDOW_HINTS:
        if hint in low:
            return size
    return DEFAULT_WINDOW


def reserve_tokens() -> int:
    """预留给模型输出、工具调用与后续响应的预算。"""
    return max(1024, RESERVE_TOKENS)


def keep_recent_tokens() -> int:
    return max(1024, KEEP_RECENT_TOKENS)


def estimate_tokens(text: str) -> int:
    """轻量估算，不引入分词器依赖。

    中文约 1 token ≈ 1.5 字，英文约 1 token ≈ 4 字符；这里对中文取 0.68/字、
    其它取 1/3.6，宁可高估一点，避免压到最后一刻才发现超窗。
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        code = ord(ch)
        if 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
            cjk += 1
        else:
            other += 1
    return int(cjk * 0.68 + other / 3.6) + 1


def message_tokens(message: BaseMessage) -> int:
    """单条消息的 token 估算，含角色开销与工具调用参数。"""
    total = 4
    content = getattr(message, "content", "")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                total += estimate_tokens(str(part.get("text", "")))
            else:
                total += estimate_tokens(str(part))
    for tc in (getattr(message, "tool_calls", None) or []):
        total += estimate_tokens(str(tc.get("name", "")))
        total += estimate_tokens(str(tc.get("args", "")))
    name = getattr(message, "name", None)
    if name:
        total += estimate_tokens(str(name))
    return total


def messages_tokens(messages: Sequence[BaseMessage]) -> int:
    return sum(message_tokens(m) for m in messages)


def context_state(
    messages: Sequence[BaseMessage],
    extra_tokens: int = 0,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """给界面用的上下文快照。

    extra_tokens 是系统提示等「不在 messages 里但每轮都发送」的部分，
    不把它算进去，进度环会长期偏低十几个百分点。
    """
    window = context_window(model)
    reserve = reserve_tokens()
    used = messages_tokens(messages) + max(0, extra_tokens)
    threshold = max(1024, window - reserve)
    return {
        "tokens": used,
        "window": window,
        "reserve": reserve,
        "threshold": threshold,
        "keep_recent": keep_recent_tokens(),
        "percent": round(min(100.0, used * 100.0 / window), 1),
        "threshold_percent": round(min(100.0, threshold * 100.0 / window), 1),
        "enabled": ENABLED,
        "over": used > threshold,
    }


def needs_compaction(state: Dict[str, Any]) -> bool:
    """是否该压缩。state 里的 enabled 优先，便于界面/接口临时关掉而不动 .env。"""
    enabled = state.get("enabled")
    if enabled is None:
        enabled = ENABLED
    return bool(enabled and state.get("over"))


# ------------------------------------------------------------
# 切点
# ------------------------------------------------------------
def split_index(messages: Sequence[BaseMessage], keep_tokens: int) -> int:
    """返回保留区起点下标；[0, idx) 进摘要，[idx, end) 原样保留。

    两条硬约束：
      1. 切点必须落在用户消息上。切成「助手的一半回答」或「孤立的工具结果」，
         下一轮请求会因为 tool_call 与 tool_result 不配对直接报错；
      2. 找不到合法切点（整段都没有用户消息）时返回 0，宁可不压。
    """
    total = 0
    idx = len(messages)
    while idx > 0:
        cost = message_tokens(messages[idx - 1])
        # 至少要保留最后一条，否则等于把所有原文都压没了
        if total + cost > keep_tokens and idx < len(messages):
            break
        total += cost
        idx -= 1

    while 0 < idx < len(messages) and getattr(messages[idx], "type", "") != "human":
        idx -= 1
    return 0 if idx >= len(messages) else idx


def trim_dangling(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """去掉末尾没有结果的工具调用，避免压缩后状态停在半截。"""
    out = list(messages)
    while out and getattr(out[-1], "type", "") == "ai" and getattr(out[-1], "tool_calls", None):
        out.pop()
    return out


# ------------------------------------------------------------
# 摘要
# ------------------------------------------------------------
SUMMARY_SYSTEM = """你是对话压缩器。把下面这段较早的对话压成一份结构化摘要，供后续继续同一场对话使用。

硬性要求：
1. 只输出摘要正文，不要寒暄，不要解释你在做什么，不要输出"以下是摘要"这类引导语。
2. 逐字保留可核查的关键事实：出生日期与时刻、性别、出生地、四柱干支、日主、旺衰结论、
   大运流年、卦名与动爻、查询日期。这些数字错一个，后面全错。
3. 保留已经给出的结论与建议要点，以及用户明确表达的偏好、禁忌、已经否决的方向。
4. 记录调用过的工具和拿到的主要结果，标明"已有数据，无需重复调用"。
5. 记录尚未解决的问题、用户最后关心的方向。
6. 按下面的小节输出 Markdown，总长控制在 800 字以内：
   ## 用户与档案
   ## 关键数据（命盘 / 卦象 / 日期）
   ## 已给出的结论与建议
   ## 工具与数据轨迹
   ## 未决事项与偏好
7. 对话里没有的不要编；确实没有内容的写"未提及"。"""

MERGE_SYSTEM = """你是对话压缩器。下面是对同一段对话分段生成的若干份摘要，请合并成一份。

要求：
1. 去重但不丢信息：同一事实只保留一处，数字与干支原样保留。
2. 冲突时以更晚出现的内容为准，并注明"此前口径已修正"。
3. 保持原有小节结构，总长不超过 1000 字。
4. 只输出合并后的摘要正文。"""

_ROLE_LABEL = {
    "human": "用户",
    "ai": "助手",
    "tool": "工具结果",
    "system": "系统",
}


def _content_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for part in content:
            if isinstance(part, dict):
                pieces.append(str(part.get("text", "")))
            else:
                pieces.append(str(part))
        return "\n".join(pieces)
    return str(content)


def render_message(message: BaseMessage) -> str:
    """把一条消息渲染成摘要请求里的纯文本段落。"""
    role = _ROLE_LABEL.get(getattr(message, "type", ""), "消息")
    text = _content_text(message).strip()
    if len(text) > _RENDER_LIMIT:
        text = text[:_RENDER_LIMIT] + f"…（后略，原文共 {len(text)} 字）"

    calls = []
    for tc in (getattr(message, "tool_calls", None) or []):
        args = tc.get("args")
        if isinstance(args, dict):
            args = ", ".join(f"{k}={v}" for k, v in args.items())
        calls.append(f"{tc.get('name', '?')}({args})")

    head = role
    name = getattr(message, "name", None)
    if role == "工具结果" and name:
        head = f"工具结果[{name}]"
    if calls:
        head += " → 调用 " + "; ".join(calls)
    return f"### {head}\n{text}" if text else f"### {head}"


def _effective_keep() -> int:
    """压缩时要保留多少原文。

    取 keepRecentTokens 与「阈值三分之一」的较小值：压完必须明显低于阈值，
    否则下一轮立刻又超、又压一次，白烧一次摘要请求。正常窗口（128K/16K）下
    阈值三分之一远大于 20K，实际就是 keepRecentTokens 本身。
    """
    threshold = max(1024, context_window() - reserve_tokens())
    return max(1200, min(keep_recent_tokens(), threshold // 3))


def _chunk(texts: List[str], budget: int) -> List[List[str]]:
    """按 token 预算把渲染好的段落分组，保证单次摘要请求不超窗。"""
    chunks: List[List[str]] = []
    current: List[str] = []
    used = 0
    for item in texts:
        cost = estimate_tokens(item)
        if current and used + cost > budget:
            chunks.append(current)
            current, used = [], 0
        current.append(item)
        used += cost
    if current:
        chunks.append(current)
    return chunks or [[]]


def _default_llm():
    """复用 agent 里按当前配置构造的模型，避免出现两套模型配置。"""
    from .agent import build_model

    return build_model()


def _call(llm: Any, body: str, system: str, label: str) -> str:
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=body)])
    text = _content_text(resp).strip()
    return text or f"（{label}无输出）"


def summarize(messages: Sequence[BaseMessage], llm: Any = None) -> str:
    """把一段旧消息压成摘要；过长时先分段摘要再合并（map-reduce）。"""
    if not messages:
        return ""
    llm = llm or _default_llm()
    rendered = [render_message(m) for m in messages]
    budget = max(4000, int(context_window() * 0.42))

    parts = _chunk(rendered, budget)
    if len(parts) == 1:
        return _call(llm, "\n\n".join(parts[0]), SUMMARY_SYSTEM, "摘要")

    partials = [
        _call(llm, f"（第 {i + 1}/{len(parts)} 段）\n\n" + "\n\n".join(chunk),
              SUMMARY_SYSTEM, f"第 {i + 1} 段摘要")
        for i, chunk in enumerate(parts)
    ]

    for _ in range(4):
        if len(partials) <= 1:
            break
        groups = _chunk(partials, budget)
        if len(groups) == len(partials):
            groups = [partials[i:i + 2] for i in range(0, len(partials), 2)]
        partials = [
            _call(llm, "\n\n---\n\n".join(group), MERGE_SYSTEM, "合并摘要")
            for group in groups
        ]
    return partials[0] if len(partials) == 1 else "\n\n".join(partials)


# ------------------------------------------------------------
# 主入口
# ------------------------------------------------------------
def compact(
    messages: Sequence[BaseMessage],
    llm: Any = None,
) -> Tuple[List[BaseMessage], Dict[str, Any]]:
    """生成压缩后的新消息序列与统计信息。

    返回 (new_messages, info)。没有可压的部分时原样返回，info["skipped"] 为真。
    """
    messages = trim_dangling(messages)
    before = messages_tokens(messages)
    idx = split_index(messages, _effective_keep())
    if idx <= 0:
        return list(messages), {
            "skipped": True,
            "reason": "没有可压缩的早期内容",
            "before": before,
            "after": before,
            "summarized": 0,
            "kept": len(messages),
        }

    old, recent = list(messages[:idx]), list(messages[idx:])
    summary = summarize(old, llm)
    head = [
        HumanMessage(content=SUMMARY_HEADER + summary + SUMMARY_FOOTER),
        AIMessage(content="已了解上述历史要点，继续。"),
    ]
    new_messages = head + recent
    return new_messages, {
        "skipped": False,
        "before": before,
        "after": messages_tokens(new_messages),
        "summarized": len(old),
        "kept": len(recent),
        "summary_chars": len(summary),
    }

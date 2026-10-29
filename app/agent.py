# -*- coding: utf-8 -*-
"""LangGraph ReAct Agent：模型 + 命理工具层 + SQLite 记忆。

手写循环（llm_node / tool_node / router），与 fate_demo 一致，
区别是多了一个 SqliteSaver，把每个会话的图状态按 thread_id 持久化。
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, Iterator, List, Optional

from langchain.messages import SystemMessage, ToolMessage
from langchain.tools import BaseTool
from langchain_core.messages import AIMessageChunk
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph

from .config import (
    CKPT_PATH,
    api_key,
    config_revision,
    model_name,
    thinking_enabled,
)
from .profile import prompt_block as profile_prompt
from .tools import ALL_TOOLS

_GRAPH_LOCK = threading.RLock()
_GRAPH = None
_GRAPH_REV = -1
_SAVER = None
_SAVER_CONN: Optional[sqlite3.Connection] = None


SYSTEM_PROMPT = """你是一位专业的东方命理顾问，通子平八字、六爻、黄历择日，擅长把术语翻译成现代人能落地的表述。

============================================================
一、工具与调用规则（严禁自行推算）
============================================================
1. get_bazi_chart —— 排八字命盘。返回四柱干支、藏干、纳音、十神、地势、旬空、五行力量、
   神煞（42 种，带溯源）、十二长生禄绝、刑冲合害、胎元命宫身宫、起运、大运与流年。
   一次调用即可，不要重复调。
2. cast_liuyao —— 六爻起卦。用于"能不能成""什么时候""该不该做"这类**单一、具体**的占问。
3. query_almanac —— 黄历。查某日宜忌、冲煞、值神、吉神凶煞、时辰吉凶，用于择日。
4. explain_term —— 术语解释。用户问"什么是XX"时调用，不要凭记忆硬解。
5. get_today_date —— 把"今年/明年/现在"换算成具体日期。
6. get_my_profile —— 读取用户本人的出生档案，仅用于核对"你记得我的信息吗"这类追问。

硬性要求：
- 任何干支、卦象、宜忌、大运流年都必须来自工具返回；工具没给就说"信息不足"，绝不编造。
- 同一会话里命盘已排过且出生信息未变，直接复用上下文数据；只有用户修正信息才重新排盘。
- 一次只选最贴合问题的工具，不要为了显得全面而乱调。
- 六爻一次只断一件事；用户没给明确问题时，先问清"要问的具体事情"。

============================================================
二、起盘前的信息采集
============================================================
排八字必需：出生年月日 + 具体到分钟的时间 + 性别。
**若第七节「本人档案」已填写，用户说"我"时直接用档案，不再采集、不再追问。**
1. "晚上八点半""下午三点多""凌晨"要换算成 24 小时制。
2. 只说时辰的，按时辰中点传小时：子0 丑2 寅4 卯6 辰8 巳10 午12 未14 申16 酉18 戌20 亥22；
   晚子时（23 点后）传 23，并注明"按 XX 时起盘"。
3. 没说分钟按整点起盘并说明；时柱只由时辰决定，分钟不影响时柱。
4. 用户给了出生地（如"我生在临沂"），把城市传 birth_city 做真太阳时校正，它可能改变时柱。
5. 农历生日传 calendar_type="阴历"，闰月传 is_leap_month=true。
6. 性别缺失必须问，不能猜（大运顺逆完全依赖男女）。
7. 一次只问缺的那一项，不做问卷式连环追问。

============================================================
三、八字默认分析：妻、财、子、禄、寿
============================================================
日主（日干）是全部判断的基准。每个方向"结论—依据—建议"三段式。

【妻】婚恋与配偶：日支为配偶宫，受合冲刑害空亡直接动婚恋；男看财星（正财为妻、偏财为异性缘），
女看官杀（正官正缘、七杀压力型关系）；参看桃花、红鸾天喜、孤辰寡宿、阴阳差错；
婚动应期＝大运流年引动日支或配偶星到位。

【财】财富与结构：正财＝稳定收入/可控资产，偏财＝浮动收益/机会财；看身财是否平衡（身弱财旺
则机会多守不住）、食伤能否生财、财库是否被冲开、劫财是否分流。

【子】子女与传承：时柱为子女宫；男看官杀、女看食伤，看星是否得地受伤；看引动时柱的运年。

【禄】事业与角色：官杀（职位责任竞争）与印星（学历资质平台）的配合是主线，月柱为事业宫；
禄神、文昌、国印、将星、词馆、学堂为加分项，羊刃魁罡宜武职、技术攻坚、强竞争领域；
「十二长生」段给出日干禄位（临官）与绝位落在哪柱——禄位主根基与担当，绝位主该处需外力扶持，
大运流年走到禄位/绝位多为事业节奏的转折提示；
五行偏旺定行业属性（木文教医药、火能源电子传媒、土地产工程、金机械金融法务、水物流贸易信息）。

【寿】体质与长期稳定性：日主根气为底盘，同党明显偏弱者在高压下易透支；五行偏枯对应体质
薄弱环节，只讲养生倾向；用神受制、忌神当令的年份宜降速。表述落在作息、体检、运动、情绪管理。

【旺衰口径】五行力量已按「天干 1.0 + 地支藏干（本气0.6/中气0.25/余气0.15）+ 月令×3」加权，
满盘 10 分。谈身强身弱依次看：
1. 月令是否得令（旺/相/休/囚/死）——这是第一权重，先定性；
2. `五行与旺衰.综合参考`——已按月令把同党占比档位增减一档，**以它为准**；
3. `量化参考` 与同党/异党占比只作旁证，两者不一致时（如得令但财重）要先说月令定调，再说占比接近；
4. 最后看是否通根、有无合冲破坏。不要用「数个数」下结论，也不要同时给出两个互相否定的结论。

【神煞口径】42 种，每条都带溯源（如「以日干丁查」）与释义。用法：
1. 只取与所问方向相关的那几条展开，不要罗列全表；
2. 吉神不叠加成"必定发达"，凶煞不叠加成"必遭灾祸"，都只说倾向与提醒；
3. 神煞是辅助，权重低于格局（月令、日主强弱、十神配合），冲刑破坏才是优先项；
4. 神煞名称以工具返回为准，不要增补工具未给的名称。

============================================================
四、六爻断卦口径
============================================================
1. 取用神：问财取妻财，问工作职位取官鬼，问文书合同学历取父母，问子女下属取子孙，
   问同辈合伙取兄弟；问自身看世爻，问对方看应爻。
2. 看旺衰：用神在月建、日辰下的强弱，是否临空破、入墓、被合。
3. 看动变：动爻生克用神的方向，变爻回头生克，忌神发动则事多阻碍。
4. 给应期：结合月建日辰与动爻，指出可能的月份或节奏，不给绝对日期承诺。
5. 静卦说明变化不大、以现状延续，不要硬编动象。

============================================================
五、输出格式
============================================================
1. 八字：先给「命盘速览」Markdown 表格（柱 | 天干 | 地支 | 天干十神 | 藏干 | 纳音 | 地势），
   再一句话总纲，然后按方向分小节。
2. 六爻：先列卦名、卦宫、动爻，再用表格给六爻（爻位/六亲/纳甲/六神/世应/动变），最后断语。
3. 黄历：结论先行（这天适不适合做某事），再列依据。
4. 术语：一句话白话定义 + 一句在命盘里怎么用。
5. 术语首次出现时括号补白话，如「正财（稳定收入、可控资产）」。
6. 结尾一行：命理属传统文化参考，不替代医疗、法律、投资等专业决策。

============================================================
六、追问与红线
============================================================
1. 追问只答被问的方向，不重复整套五维；问"什么时候"就给运年时间窗并说明触发原因。
2. 用户问"适不适合/该不该"时，讲结构倾向 + 可执行的判断标准，不替用户做决定。
3. 不预测寿元终点、不预测具体疾病、不判生死灾祸，转为体质倾向与风险偏好。
4. 不用"必然、一定、注定"等断言，改用"倾向于、概率较高、需要留意、可主动调整"。
5. 不制造恐慌，不推销符咒、改运、收费化解；不涉及政治与道德说教。
6. 全程中文，平实、具体、可操作，避免堆砌玄虚术语。
"""


def build_model() -> ChatDeepSeek:
    """每次重建都读取当前配置，保存设置后无需重启即可换模型/换 Key。"""
    return ChatDeepSeek(
        model=model_name(),
        api_key=api_key() or None,
        extra_body={"thinking": {"type": "enabled" if thinking_enabled() else "disabled"}},
    )


def _system_message() -> SystemMessage:
    """每轮现拼系统提示：本人档案来自 SQLite，改完立即对下一句话生效。

    不走重建图的原因是档案与模型配置无关，重建会白丢一次模型实例；
    但要注意系统消息本身不进 checkpoint（节点只回 AI 消息），所以必须逐轮加。
    """
    return SystemMessage(content=SYSTEM_PROMPT + "\n" + profile_prompt())


def _llm_node_factory(model_with_tools):
    def llm_node(state: MessagesState) -> dict:
        messages = list(state["messages"])
        if messages and getattr(messages[0], "type", None) == "system":
            messages[0] = _system_message()
        else:
            messages = [_system_message()] + messages
        return {"messages": [model_with_tools.invoke(messages)]}
    return llm_node


def _tool_node_factory(tools_by_name: Dict[str, BaseTool]):
    def tool_node(state: MessagesState) -> dict:
        tool_messages: List[ToolMessage] = []
        for tc in state["messages"][-1].tool_calls:
            name, args = tc["name"], tc["args"]
            try:
                result = tools_by_name[name].invoke(args)
            except Exception as exc:
                result = f"工具 {name} 调用失败：{exc}"
            tool_messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"], name=name)
            )
        return {"messages": tool_messages}
    return tool_node


def _router(state: MessagesState):
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tool_node"
    return END


def get_graph():
    """构建（并缓存）编译后的图。首次调用时初始化 SQLite checkpointer。

    配置版本号变化（用户在设置里改了模型或 Key）时重建模型与图，
    checkpointer 连接复用，历史上下文不丢。
    """
    global _GRAPH, _GRAPH_REV, _SAVER, _SAVER_CONN
    with _GRAPH_LOCK:
        rev = config_revision()
        if _GRAPH is not None and _GRAPH_REV == rev:
            return _GRAPH

        model = build_model()
        tools_by_name = {t.name: t for t in ALL_TOOLS}
        model_with_tools = model.bind_tools(ALL_TOOLS)

        builder = StateGraph(state_schema=MessagesState)
        builder.add_node("llm_node", _llm_node_factory(model_with_tools))
        builder.add_node("tool_node", _tool_node_factory(tools_by_name))
        builder.add_edge(START, "llm_node")
        builder.add_conditional_edges("llm_node", _router, ["tool_node", END])
        builder.add_edge("tool_node", "llm_node")

        if _SAVER is None:
            _SAVER_CONN = sqlite3.connect(str(CKPT_PATH), check_same_thread=False)
            _SAVER = SqliteSaver(_SAVER_CONN)
            _SAVER.setup()

        _GRAPH = builder.compile(checkpointer=_SAVER)
        _GRAPH_REV = rev
        return _GRAPH


TOOL_LABELS = {
    "get_bazi_chart": "排盘",
    "cast_liuyao": "起卦",
    "query_almanac": "查黄历",
    "explain_term": "查术语",
    "get_today_date": "取当前时间",
    "get_my_profile": "读个人信息",
}


def stream_chat(conversation_id: str, text: str) -> Iterator[Dict[str, Any]]:
    """同步流式生成事件，供 API 层转为 SSE。

    事件类型：
      token     {"text": "..."}           模型增量输出
      tool      {"name","label","args"}   即将调用的工具
      reset     {}                        需要清空已渲染内容（模型进入工具轮）
      error     {"message": "..."}
    """
    if not api_key():
        yield {
            "type": "error",
            "message": "未配置 API Key：点击左下角齿轮 → 模型配置，填入 DeepSeek Key 后保存即可",
        }
        return

    graph = get_graph()
    config = {"configurable": {"thread_id": conversation_id}}

    emitted_tools = set()
    try:
        for mode, chunk in graph.stream(
            {"messages": [("user", text)]},
            config,
            stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                msg, _meta = chunk
                # messages 流里也会出现 ToolMessage（工具返回的整段 JSON），
                # 只把模型自己的增量输出当正文，否则工具数据会污染回答
                if not isinstance(msg, AIMessageChunk):
                    continue
                # 工具调用意图：工具名只在首个分片里出现
                for tc in (getattr(msg, "tool_call_chunks", None) or []):
                    name = tc.get("name")
                    if name and tc.get("id") not in emitted_tools:
                        emitted_tools.add(tc.get("id"))
                        yield {
                            "type": "tool",
                            "name": name,
                            "label": TOOL_LABELS.get(name, name),
                            "args": tc.get("args") or "",
                        }
                content = getattr(msg, "content", "")
                if content and isinstance(content, str):
                    yield {"type": "token", "text": content}
            elif mode == "updates":
                for node, payload in (chunk or {}).items():
                    if node != "llm_node" or not isinstance(payload, dict):
                        continue
                    for m in payload.get("messages", []):
                        # 模型决定调用工具时，本轮文本往往是"我要开始排盘"这类过渡语，
                        # 丢弃重来，避免界面上出现两段拼接的回答
                        if getattr(m, "tool_calls", None):
                            yield {"type": "reset"}
    except Exception as exc:  # 网络、鉴权、超时统一回给界面
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}


def clear_thread(conversation_id: str) -> None:
    """删除某会话的图状态（checkpoint）。"""
    try:
        conn = sqlite3.connect(str(CKPT_PATH), timeout=10)
        for table in ("writes", "checkpoints"):
            try:
                conn.execute(f"DELETE FROM {table} WHERE thread_id=?", (conversation_id,))
            except sqlite3.Error:
                pass
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass

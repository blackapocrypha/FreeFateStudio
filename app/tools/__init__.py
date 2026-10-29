# -*- coding: utf-8 -*-
"""命理工具层 · 入口。

对外只暴露 ALL_TOOLS，Agent 直接绑定即可。
"""

from __future__ import annotations

import json
from datetime import datetime

from langchain.tools import tool

from .bazi import get_bazi_chart
from .liuyao import cast_liuyao
from .almanac import query_almanac
from .glossary import explain_term
from .memory import get_my_profile


@tool
def get_today_date() -> str:
    """获取当前确切日期、时辰与相邻年份。

    用于把"今年/明年/最近/现在"换算成具体时间，再去命盘的大运流年里定位。
    """
    now = datetime.now()
    zhi = "子丑寅卯辰巳午未申酉戌亥"
    idx = ((now.hour + 1) // 2) % 12
    return json.dumps(
        {
            "当前时间": now.strftime("%Y-%m-%d %H:%M"),
            "当前时辰": f"{zhi[idx]}时",
            "今年": now.year,
            "明年": now.year + 1,
            "后年": now.year + 2,
            "去年": now.year - 1,
        },
        ensure_ascii=False,
    )


ALL_TOOLS = [
    get_bazi_chart,
    cast_liuyao,
    query_almanac,
    explain_term,
    get_today_date,
    get_my_profile,
]

__all__ = [
    "ALL_TOOLS",
    "get_bazi_chart",
    "cast_liuyao",
    "query_almanac",
    "explain_term",
    "get_today_date",
    "get_my_profile",
]

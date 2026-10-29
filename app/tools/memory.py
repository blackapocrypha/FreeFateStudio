# -*- coding: utf-8 -*-
"""长期记忆工具：把「个人信息」里的本人档案交给模型。

与提示词里的档案段落功能重叠——提示词负责让模型默认知道「我」是谁，
这个工具负责在用户明确追问「你记得我的出生信息吗」时给出可引用的结构化数据，
两者都读同一份 SQLite 记录，不会分叉。
"""

from __future__ import annotations

import json

from langchain.tools import tool


@tool
def get_my_profile() -> str:
    """读取用户本人的出生档案（出生日期时刻、性别、出生地、真太阳时是否启用）。

    仅在用户询问「你记得我的信息吗」「我的档案是什么」或需要核对本人信息时调用。
    用户以「我」提问八字时，档案已在系统提示里给出，不必调用本工具。
    """
    # 延迟导入：tools 包与 profile 模块互相引用，放在函数内可避开循环导入
    from ..profile import state

    info = state()
    if not info["configured"]:
        return json.dumps(
            {"已填写": False, "提示": "用户尚未填写个人信息，可在左下角齿轮 → 个人信息 中填写"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "已填写": True,
            "出生日期": info["birth_date"],
            "出生时刻": info["birth_time"],
            "历法": "公历",
            "性别": info["gender"],
            "出生地": info["birth_place"] or "未填写",
            "真太阳时": {
                "启用": info["solar_time"]["enabled"],
                "经度": info["solar_time"]["longitude"],
                "说明": info["solar_time"]["note"],
            },
            "排盘入参": {
                "year": info["year"],
                "month": info["month"],
                "day": info["day"],
                "hour": info["hour"],
                "minute": info["minute"],
                "gender": info["gender"],
                "birth_city": info["birth_place"] if info["solar_time"]["enabled"] else None,
            },
        },
        ensure_ascii=False,
    )

# -*- coding: utf-8 -*-
"""命理工具层 · 八字排盘。

排盘计算全部委托给 bazi_engine（基于 lunar_python 的 EightChar），
本文件只负责把参数清洗成工具入参、把结果序列化给模型。
"""

from __future__ import annotations

import json
from typing import Optional

from langchain.tools import tool

from .bazi_engine import build_chart, resolve_city_longitude


@tool
def get_bazi_chart(
    year: int,
    month: int,
    day: int,
    gender: str,
    hour: int = 0,
    minute: int = 0,
    calendar_type: str = "阳历",
    is_leap_month: bool = False,
    birth_city: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    """按出生时间排出完整八字命盘，返回天干地支、藏干、纳音、十神、神煞、大运、流年等全部数据。

    这是唯一的排盘工具，调用一次即可拿到后续分析所需的全部信息，不要重复调用。

    Args:
        year: 出生年份（四位，公历或农历），如 1990
        month: 出生月份 1-12
        day: 出生日 1-31
        gender: 性别，"男" 或 "女"（决定大运顺逆，必填）
        hour: 出生小时（24 小时制）。只知道时辰时按时辰中点：子0 丑2 寅4 卯6 辰8
              巳10 午12 未14 申16 酉18 戌20 亥22；晚子时（23 点后）传 23
        minute: 出生分钟 0-59；未知传 0，并在回答中说明按整点起盘
        calendar_type: "阳历" 或 "阴历"
        is_leap_month: 农历是否闰月，仅 calendar_type="阴历" 时有效
        birth_city: 出生城市，如 "临沂"。传入后按真太阳时校正，可能改变时柱
        name: 称谓，可选
    """
    try:
        lon = None
        city_note = "未提供出生地，未做真太阳时校正"
        if birth_city:
            lon, city_note = resolve_city_longitude(birth_city)

        chart = build_chart(
            year=int(year),
            month=int(month),
            day=int(day),
            hour=int(hour),
            minute=int(minute),
            gender=gender,
            calendar_type=calendar_type,
            is_leap_month=bool(is_leap_month),
            longitude=lon,
            name=name or None,
        )
        chart["基本信息"]["出生地校正说明"] = city_note
        return json.dumps(chart, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"错误": f"排盘失败：{exc}",
             "提示": "请核对出生年月日时分是否真实存在，或改用公历/夏令时修正后的时间"},
            ensure_ascii=False,
        )

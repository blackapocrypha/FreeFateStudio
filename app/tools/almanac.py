# -*- coding: utf-8 -*-
"""命理工具层 · 黄历查询。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from langchain.tools import tool

from lunar_python import Solar

_WEEK = ("一", "二", "三", "四", "五", "六", "日")


def _opt(fn, default=None):
    try:
        v = fn()
        return v if v not in (None, "", []) else default
    except Exception:
        return default


@tool
def query_almanac(date: str = "", with_hours: bool = False) -> str:
    """查询某一天的黄历信息：农历、干支、宜忌、冲煞、值神、吉神凶煞、彭祖百忌、二十八宿、吉神方位，
    可选返回十二时辰各自的吉凶与宜忌。

    用于择日、看某天适不适合做某事、查当日宜忌。

    Args:
        date: 公历日期，格式 "YYYY-MM-DD"；留空表示今天
        with_hours: 是否返回十二时辰明细（吉时/凶时、各时辰宜忌），默认 False
    """
    text = (date or "").strip()
    try:
        dt = datetime.strptime(text, "%Y-%m-%d") if text else datetime.now()
    except ValueError:
        return json.dumps({"错误": f"日期格式不对：{date}，应为 YYYY-MM-DD"}, ensure_ascii=False)

    lunar = Solar.fromYmdHms(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0).getLunar()

    data: Dict[str, Any] = {
        "公历": f"{dt.strftime('%Y-%m-%d')} 星期{_WEEK[dt.weekday()]}",
        "农历": f"{lunar.getYearInChinese()}年{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "生肖": lunar.getYearShengXiao(),
        "节气": _opt(lambda: lunar.getJieQi()) or "无",
        "干支": {
            "年": lunar.getYearInGanZhi(),
            "月": lunar.getMonthInGanZhi(),
            "日": lunar.getDayInGanZhi(),
        },
        "日纳音": _opt(lunar.getDayNaYin),
        "值神": f"{_opt(lunar.getDayTianShen, '')}（{_opt(lunar.getDayTianShenType, '')}·{_opt(lunar.getDayTianShenLuck, '')}）",
        "宜": _opt(lunar.getDayYi, []),
        "忌": _opt(lunar.getDayJi, []),
        "冲煞": f"冲{_opt(lunar.getDayChongDesc, '')} 煞{_opt(lunar.getDaySha, '')}",
        "吉神宜趋": _opt(lunar.getDayJiShen, []),
        "凶煞宜忌": _opt(lunar.getDayXiongSha, []),
        "彭祖百忌": f"{_opt(lunar.getPengZuGan, '')} {_opt(lunar.getPengZuZhi, '')}".strip(),
        "二十八宿": f"{_opt(lunar.getXiu, '')}({_opt(lunar.getXiuLuck, '')}) 值日：{_opt(lunar.getZheng, '')} 兽：{_opt(lunar.getAnimal, '')}",
        "吉神方位": {
            "喜神": _opt(lambda: lunar.getDayPositionXiDesc()),
            "财神": _opt(lambda: lunar.getDayPositionCaiDesc()),
            "福神": _opt(lambda: lunar.getDayPositionFuDesc()),
        },
        "旬空": _opt(lunar.getDayXunKong),
    }

    if with_hours:
        hours: List[Dict[str, Any]] = []
        for t in lunar.getTimes():
            hours.append({
                "时段": f"{_opt(t.getMinHm, '')}-{_opt(t.getMaxHm, '')}",
                "时辰": f"{t.getGanZhi()}时",
                "天神": _opt(t.getTianShen),
                "吉凶": _opt(t.getTianShenLuck),
                "宜": _opt(t.getYi, []),
                "忌": _opt(t.getJi, []),
            })
        data["十二时辰"] = hours

    return json.dumps(data, ensure_ascii=False)

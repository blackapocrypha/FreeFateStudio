# -*- coding: utf-8 -*-
"""个人信息（「我」的长期记忆）。

只存一条记录：出生日期、出生时刻（精确到分钟）、性别、出生地。
出生地可留空；留空、空白、或地名查不到经度时，一律不做真太阳时校正。

职责边界：
  - storage  只负责落库（单行表 profile）
  - 本模块    负责校验、地名解析、生成给模型的档案段落
  - agent     每轮把档案段落拼进 system prompt，使「我」默认指向本人
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

from .storage import store
from .tools.bazi_engine import resolve_city_longitude

MIN_YEAR = 1900
_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2})\s*[:：]\s*(\d{1,2})$")


# ------------------------------------------------------------
# 解析与校验
# ------------------------------------------------------------
def _parse_date(text: str) -> Tuple[int, int, int]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("请填写出生日期")
    m = _DATE_RE.match(raw)
    if not m:
        raise ValueError("出生日期格式应为 1990-05-12")
    y, mo, d = (int(g) for g in m.groups())
    try:
        parsed = date(y, mo, d)  # 天然拒绝 2 月 30 日之类不存在的日期
    except ValueError:
        raise ValueError(f"{y}-{mo:02d}-{d:02d} 不是真实存在的日期") from None
    if y < MIN_YEAR:
        raise ValueError(f"出生年份需在 {MIN_YEAR} 年之后")
    if parsed > date.today():
        raise ValueError("出生日期不能晚于今天")
    return y, mo, d


def _parse_time(text: str) -> Tuple[int, int]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("请填写出生时刻（精确到分钟）")
    m = _TIME_RE.match(raw)
    if not m:
        raise ValueError("出生时刻格式应为 14:30（24 小时制）")
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"{raw} 不是有效的时刻")
    return h, mi


def _clean_gender(text: str) -> str:
    raw = (text or "").strip()
    if raw not in ("男", "女"):
        raise ValueError("性别需选择「男」或「女」（大运顺逆依赖性别）")
    return raw


def _resolve_place(place: str) -> Tuple[Optional[float], str, bool]:
    """返回 (经度, 说明, 是否启用真太阳时)。空地名或查不到 → 不启用。"""
    raw = (place or "").strip()
    if not raw:
        return None, "未填写出生地，不做真太阳时校正", False
    lon, note = resolve_city_longitude(raw)
    if lon is None:
        # 引擎的说明已经写明「未收录」，直接沿用，避免两套措辞
        return None, note, False
    return lon, note, True


# ------------------------------------------------------------
# 读写
# ------------------------------------------------------------
def state() -> Dict[str, Any]:
    """完整档案快照，供界面渲染与提示词生成共用。"""
    raw = store.get_profile() or {}
    birth_date = str(raw.get("birth_date") or "")
    birth_time = str(raw.get("birth_time") or "")
    gender = str(raw.get("gender") or "")
    place = str(raw.get("birth_place") or "")

    lon, note, use_solar = _resolve_place(place)

    y = mo = d = h = mi = None
    try:
        y, mo, d = _parse_date(birth_date)
        h, mi = _parse_time(birth_time)
        valid = True
    except ValueError:
        valid = False

    return {
        "configured": bool(valid and gender in ("男", "女")),
        "birth_date": birth_date,
        "birth_time": birth_time,
        "gender": gender,
        "birth_place": place,
        "year": y,
        "month": mo,
        "day": d,
        "hour": h,
        "minute": mi,
        "solar_time": {
            "enabled": use_solar,
            "longitude": lon,
            "note": note,
        },
        "updated_at": raw.get("updated_at") or "",
    }


def save(
    birth_date: str,
    birth_time: str,
    gender: str,
    birth_place: str = "",
) -> Dict[str, Any]:
    """校验后覆盖写入。校验失败抛 ValueError（由 API 层转 400）。"""
    y, mo, d = _parse_date(birth_date)
    h, mi = _parse_time(birth_time)
    g = _clean_gender(gender)
    place = (birth_place or "").strip()

    store.save_profile(
        {
            "birth_date": f"{y:04d}-{mo:02d}-{d:02d}",
            "birth_time": f"{h:02d}:{mi:02d}",
            "gender": g,
            "birth_place": place,
        }
    )
    return state()


# ------------------------------------------------------------
# 提示词
# ------------------------------------------------------------
def prompt_block() -> str:
    """拼进 system prompt 的「本人档案」段落。

    每轮重新生成，因此用户在设置里改完立即对下一句话生效，
    不需要重建模型或图。
    """
    info = state()
    head = (
        "\n============================================================\n"
        "七、本人档案（长期记忆，用户在「个人信息」里填写）\n"
        "============================================================\n"
    )

    if not info["configured"]:
        return head + (
            "当前尚未填写。\n"
            "1. 用户以「我」提问八字、运势、流年时，先提醒他可以在左下角齿轮 → 个人信息"
            "里一次性填好出生日期（精确到分钟）、性别、出生地，之后不必重复说明。\n"
            "2. 若用户当轮已自报出生信息，照常排盘，不要因为档案为空而拒答。\n"
            "3. 绝不可臆测或套用他的出生时间。\n"
        )

    place = info["birth_place"] or "（未填写）"
    solar = info["solar_time"]
    if solar["enabled"]:
        solar_line = (
            f"真太阳时：已启用，{solar['note']}（经度 {solar['longitude']}°E），"
            "时柱可能因此变化，排盘时必须带上出生地。\n"
        )
        city_arg = f', birth_city="{info["birth_place"]}"'
    else:
        solar_line = f"真太阳时：未启用（{solar['note']}）。\n"
        city_arg = ""

    call = (
        f"get_bazi_chart(year={info['year']}, month={info['month']}, day={info['day']}, "
        f'hour={info["hour"]}, minute={info["minute"]}, gender="{info["gender"]}"{city_arg})'
    )

    return head + (
        f"出生时间：{info['birth_date']} {info['birth_time']}（公历）\n"
        f"性别：{info['gender']}\n"
        f"出生地：{place}\n"
        f"{solar_line}"
        f"标准调用：{call}\n"
        "规则：\n"
        "1. 用户说「我」「我的」「本人」「我今年运势」时，指的就是上面这个人，"
        "直接按档案排盘，不要再问出生时间、性别、出生地。\n"
        "2. 本次会话已排过盘、且上下文里的出生时间与档案一致时，复用命盘不重复调用工具；"
        "若上下文里的出生时间与档案不一致（用户刚改过个人信息），以档案为准重新排盘，"
        "并说明「按更新后的信息重排」。\n"
        "3. 用户给出的是**别人**的出生信息时，按新信息排盘，不影响档案。\n"
        "4. 用户想改本人信息时，引导他去左下角齿轮 → 个人信息 修改，"
        "不要在对话里假装已经改好。\n"
    )

# -*- coding: utf-8 -*-
"""命理工具层 · 六爻起卦（金钱卦 / 时间卦）。

纯本地推算，不依赖外部服务：
  摇卦 → 六爻阴阳老少 → 本卦、变卦 → 定宫 → 纳甲装卦（六亲、六神、世应、动爻）
  并给出起卦时间的月建、日辰、旬空，供模型判断旺衰。
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain.tools import tool

try:
    from lunar_python import Solar
except ImportError:  # pragma: no cover
    Solar = None

# ------------------------------------------------------------
# 八卦：bits 自下而上，1 阳 0 阴
# ------------------------------------------------------------
TRIGRAMS: Dict[str, Dict[str, Any]] = {
    "乾": {"bits": (1, 1, 1), "wx": "金", "nature": "天"},
    "兑": {"bits": (1, 1, 0), "wx": "金", "nature": "泽"},
    "离": {"bits": (1, 0, 1), "wx": "火", "nature": "火"},
    "震": {"bits": (1, 0, 0), "wx": "木", "nature": "雷"},
    "巽": {"bits": (0, 1, 1), "wx": "木", "nature": "风"},
    "坎": {"bits": (0, 1, 0), "wx": "水", "nature": "水"},
    "艮": {"bits": (0, 0, 1), "wx": "土", "nature": "山"},
    "坤": {"bits": (0, 0, 0), "wx": "土", "nature": "地"},
}
_BITS_TO_NAME = {v["bits"]: k for k, v in TRIGRAMS.items()}

# ------------------------------------------------------------
# 六十四卦：上卦 → 下卦 → 卦名
# ------------------------------------------------------------
NAMES: Dict[Tuple[str, str], str] = {
    ("乾", "乾"): "乾为天", ("乾", "兑"): "天泽履", ("乾", "离"): "天火同人",
    ("乾", "震"): "天雷无妄", ("乾", "巽"): "天风姤", ("乾", "坎"): "天水讼",
    ("乾", "艮"): "天山遁", ("乾", "坤"): "天地否",
    ("兑", "乾"): "泽天夬", ("兑", "兑"): "兑为泽", ("兑", "离"): "泽火革",
    ("兑", "震"): "泽雷随", ("兑", "巽"): "泽风大过", ("兑", "坎"): "泽水困",
    ("兑", "艮"): "泽山咸", ("兑", "坤"): "泽地萃",
    ("离", "乾"): "火天大有", ("离", "兑"): "火泽睽", ("离", "离"): "离为火",
    ("离", "震"): "火雷噬嗑", ("离", "巽"): "火风鼎", ("离", "坎"): "火水未济",
    ("离", "艮"): "火山旅", ("离", "坤"): "火地晋",
    ("震", "乾"): "雷天大壮", ("震", "兑"): "雷泽归妹", ("震", "离"): "雷火丰",
    ("震", "震"): "震为雷", ("震", "巽"): "雷风恒", ("震", "坎"): "雷水解",
    ("震", "艮"): "雷山小过", ("震", "坤"): "雷地豫",
    ("巽", "乾"): "风天小畜", ("巽", "兑"): "风泽中孚", ("巽", "离"): "风火家人",
    ("巽", "震"): "风雷益", ("巽", "巽"): "巽为风", ("巽", "坎"): "风水涣",
    ("巽", "艮"): "风山渐", ("巽", "坤"): "风地观",
    ("坎", "乾"): "水天需", ("坎", "兑"): "水泽节", ("坎", "离"): "水火既济",
    ("坎", "震"): "水雷屯", ("坎", "巽"): "水风井", ("坎", "坎"): "坎为水",
    ("坎", "艮"): "水山蹇", ("坎", "坤"): "水地比",
    ("艮", "乾"): "山天大畜", ("艮", "兑"): "山泽损", ("艮", "离"): "山火贲",
    ("艮", "震"): "山雷颐", ("艮", "巽"): "山风蛊", ("艮", "坎"): "山水蒙",
    ("艮", "艮"): "艮为山", ("艮", "坤"): "山地剥",
    ("坤", "乾"): "地天泰", ("坤", "兑"): "地泽临", ("坤", "离"): "地火明夷",
    ("坤", "震"): "地雷复", ("坤", "巽"): "地风升", ("坤", "坎"): "地水师",
    ("坤", "艮"): "地山谦", ("坤", "坤"): "坤为地",
}

# 八宫卦序：本宫、一世…五世、游魂、归魂
PALACES: Dict[str, List[str]] = {
    "乾": ["乾为天", "天风姤", "天山遁", "天地否", "风地观", "山地剥", "火地晋", "火天大有"],
    "坎": ["坎为水", "水泽节", "水雷屯", "水火既济", "泽火革", "雷火丰", "地火明夷", "地水师"],
    "艮": ["艮为山", "山火贲", "山天大畜", "山泽损", "火泽睽", "天泽履", "风泽中孚", "风山渐"],
    "震": ["震为雷", "雷地豫", "雷水解", "雷风恒", "地风升", "水风井", "泽风大过", "泽雷随"],
    "巽": ["巽为风", "风天小畜", "风火家人", "风雷益", "天雷无妄", "火雷噬嗑", "山雷颐", "山风蛊"],
    "离": ["离为火", "火山旅", "火风鼎", "火水未济", "山水蒙", "风水涣", "天水讼", "天火同人"],
    "坤": ["坤为地", "地雷复", "地泽临", "地天泰", "雷天大壮", "泽天夬", "水天需", "水地比"],
    "兑": ["兑为泽", "泽水困", "泽地萃", "泽山咸", "水山蹇", "地山谦", "雷山小过", "雷泽归妹"],
}
_PALACE_OF: Dict[str, Tuple[str, int, str]] = {}
for _p, _names in PALACES.items():
    for _i, _n in enumerate(_names):
        _kind = ["本宫", "一世", "二世", "三世", "四世", "五世", "游魂", "归魂"][_i]
        _shi = [6, 1, 2, 3, 4, 5, 4, 3][_i]
        _PALACE_OF[_n] = (_p, _shi, _kind)

# 纳甲：内卦（初、二、三）与外卦（四、五、上）
NAJIA_IN: Dict[str, Tuple[str, str, str]] = {
    "乾": ("甲子", "甲寅", "甲辰"), "坎": ("戊寅", "戊辰", "戊午"),
    "艮": ("丙辰", "丙午", "丙申"), "震": ("庚子", "庚寅", "庚辰"),
    "巽": ("辛丑", "辛亥", "辛酉"), "离": ("己卯", "己丑", "己亥"),
    "坤": ("乙未", "乙巳", "乙卯"), "兑": ("丁巳", "丁卯", "丁丑"),
}
NAJIA_OUT: Dict[str, Tuple[str, str, str]] = {
    "乾": ("壬午", "壬申", "壬戌"), "坎": ("戊申", "戊戌", "戊子"),
    "艮": ("丙戌", "丙子", "丙寅"), "震": ("庚午", "庚申", "庚戌"),
    "巽": ("辛未", "辛巳", "辛卯"), "离": ("己酉", "己未", "己巳"),
    "坤": ("癸丑", "癸亥", "癸酉"), "兑": ("丁亥", "丁酉", "丁未"),
}

ZHI_WX = {"子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
          "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水"}
WX_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
WX_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

LIU_SHEN = ("青龙", "朱雀", "勾陈", "螣蛇", "白虎", "玄武")
_LS_START = {"甲": 0, "乙": 0, "丙": 1, "丁": 1, "戊": 2,
             "己": 3, "庚": 4, "辛": 4, "壬": 5, "癸": 5}

YAO_POS = ("初", "二", "三", "四", "五", "上")


def _liu_qin(gong_wx: str, zhi: str) -> str:
    wx = ZHI_WX[zhi]
    if wx == gong_wx:
        return "兄弟"
    if WX_SHENG[wx] == gong_wx:
        return "父母"
    if WX_SHENG[gong_wx] == wx:
        return "子孙"
    if WX_KE[gong_wx] == wx:
        return "妻财"
    return "官鬼"


def _yao_label(pos: int, yang: bool) -> str:
    head = YAO_POS[pos - 1]
    if pos in (1, 6):
        return f"{head}{'九' if yang else '六'}"
    return f"{'九' if yang else '六'}{head}"


def _hex_name(upper: str, lower: str) -> str:
    return NAMES[(upper, lower)]


def _split_trigrams(bits: List[int]) -> Tuple[str, str]:
    lower = _BITS_TO_NAME[tuple(bits[0:3])]
    upper = _BITS_TO_NAME[tuple(bits[3:6])]
    return upper, lower


def _build_hex(bits: List[int], day_gan: str, order: str = "本卦",
               gong_wx_override: Optional[str] = None) -> Dict[str, Any]:
    """装卦：纳甲、六亲、六神、世应。"""
    upper, lower = _split_trigrams(bits)
    name = _hex_name(upper, lower)
    palace, shi_pos, kind = _PALACE_OF[name]
    gong_wx = TRIGRAMS[palace]["wx"]
    calc_wx = gong_wx_override or gong_wx
    ying_pos = shi_pos + 3 if shi_pos <= 3 else shi_pos - 3
    ls_start = _LS_START.get(day_gan, 0)

    rows = []
    for i in range(6):
        pos = i + 1
        yang = bool(bits[i])
        if pos <= 3:
            ganzhi = NAJIA_IN[lower][pos - 1]
        else:
            ganzhi = NAJIA_OUT[upper][pos - 4]
        zhi = ganzhi[1]
        rows.append({
            "爻位": _yao_label(pos, yang),
            "序号": pos,
            "阴阳": "阳" if yang else "阴",
            "六神": LIU_SHEN[(ls_start + i) % 6],
            "六亲": _liu_qin(calc_wx, zhi),
            "纳甲": ganzhi,
            "五行": ZHI_WX[zhi],
            "世应": "世" if pos == shi_pos else ("应" if pos == ying_pos else ""),
        })
    rows.reverse()  # 输出自上而下（上爻在前）
    return {
        "卦名": name,
        "卦宫": f"{palace}宫（{kind}卦）",
        "宫五行": gong_wx,
        "上卦": f"{upper}（{TRIGRAMS[upper]['nature']}·{TRIGRAMS[upper]['wx']}）",
        "下卦": f"{lower}（{TRIGRAMS[lower]['nature']}·{TRIGRAMS[lower]['wx']}）",
        "世爻": f"第{shi_pos}爻",
        "应爻": f"第{ying_pos}爻",
        "六爻": rows,
    }


def _throw_coins(rng: random.Random) -> Tuple[int, bool]:
    """摇一次（三枚铜钱）。返回 (1 阳 / 0 阴, 是否动爻)。"""
    backs = sum(1 for _ in range(3) if rng.random() < 0.5)  # 背为阳
    if backs == 3:
        return 1, True      # 老阳：阳动
    if backs == 2:
        return 0, False     # 少阴
    if backs == 1:
        return 1, False     # 少阳
    return 0, True          # 老阴：阴动


def _time_bits(lunar) -> Tuple[List[int], int]:
    """时间起卦（梅花易数）：先天卦数 乾1兑2离3震4巽5坎6艮7坤8。"""
    zhi = "子丑寅卯辰巳午未申酉戌亥"
    year_num = zhi.index(lunar.getYearZhi()) + 1
    month_num = lunar.getMonth()
    day_num = lunar.getDay()
    hour_num = zhi.index(lunar.getTimeZhi()) + 1
    total = year_num + month_num + day_num
    total_h = total + hour_num

    def num_to_trigram(n: int) -> str:
        return {1: "乾", 2: "兑", 3: "离", 4: "震",
                5: "巽", 6: "坎", 7: "艮", 0: "坤"}[n % 8]

    upper = num_to_trigram(total)
    lower = num_to_trigram(total_h)
    dong = total_h % 6 or 6
    return list(TRIGRAMS[lower]["bits"]) + list(TRIGRAMS[upper]["bits"]), dong


@tool
def cast_liuyao(question: str, method: str = "铜钱摇卦",
                cast_time: Optional[str] = None,
                seed: Optional[int] = None) -> str:
    """六爻起卦：按问题摇卦，返回本卦、变卦及纳甲装卦的六爻详情。

    适用于"能不能成""什么时候""该不该做""这件事的走向"这类具体、单一、有疑问指向的占问。
    一次只问一件事；问题越具体，断卦越准。

    Args:
        question: 占问原文，例如"这次面试能否通过"
        method: "铜钱摇卦"（默认，随机摇六次）或 "时间起卦"（按起卦时刻起卦）
        cast_time: 起卦时间 "YYYY-MM-DD HH:mm"，默认当前时间
        seed: 随机种子，仅调试用，正常不要传
    """
    if not question or not question.strip():
        return json.dumps({"错误": "缺少占问内容，请先说明要问的事"}, ensure_ascii=False)

    try:
        dt = (datetime.strptime(cast_time, "%Y-%m-%d %H:%M")
              if cast_time else datetime.now())
    except ValueError:
        return json.dumps({"错误": f"起卦时间格式不对：{cast_time}，应为 YYYY-MM-DD HH:mm"},
                          ensure_ascii=False)

    lunar = Solar.fromYmdHms(dt.year, dt.month, dt.day,
                             dt.hour, dt.minute, 0).getLunar()
    day_gan = lunar.getDayGan()
    month_gz = lunar.getMonthInGanZhi()
    day_gz = lunar.getDayInGanZhi()

    dong_yao: List[int] = []
    if method and "时间" in method:
        bits, dong = _time_bits(lunar)
        dong_yao = [dong]
        method_label = "时间起卦"
    else:
        rng = random.Random(seed) if seed is not None else random.SystemRandom()
        bits = []
        for i in range(6):
            val, moving = _throw_coins(rng)
            bits.append(val)
            if moving:
                dong_yao.append(i + 1)
        method_label = "铜钱摇卦"

    ben = _build_hex(bits, day_gan)
    result: Dict[str, Any] = {
        "占问": question.strip(),
        "起卦时间": dt.strftime("%Y-%m-%d %H:%M"),
        "起卦方式": method_label,
        "四柱": {
            "月建": month_gz,
            "日辰": day_gz,
            "旬空": lunar.getDayXunKong(),
            "时辰": f"{lunar.getTimeZhi()}时（{lunar.getTimeInGanZhi()}）",
        },
        "动爻": [f"第{n}爻" for n in sorted(dong_yao)] or ["无动爻（静卦）"],
        "本卦": ben,
    }

    if dong_yao:
        bian_bits = list(bits)
        for n in dong_yao:
            bian_bits[n - 1] ^= 1
        bian = _build_hex(bian_bits, day_gan, "变卦",
                          gong_wx_override=ben["宫五行"])
        # 标出变出之爻
        for row, pos in ((r, r["序号"]) for r in bian["六爻"]):
            if pos in dong_yao:
                row["动变"] = "由本卦动爻变来"
        result["变卦"] = bian
        result["变爻六亲基准"] = f"以本卦{ben['卦宫']}之宫五行（{ben['宫五行']}）为基准"
    else:
        result["变卦"] = None

    result["取用提示"] = (
        "六爻以用神为核心：问财看妻财，问工作职位看官鬼，问文书学历看父母，"
        "问子女下属看子孙，问同辈合伙看兄弟；再看用神在月建日辰下的旺衰、"
        "有无动爻生克、是否空破入墓，最后看应期。"
    )
    return json.dumps(result, ensure_ascii=False)

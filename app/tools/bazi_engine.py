# -*- coding: utf-8 -*-
"""八字命盘计算引擎。

基于 lunar_python 1.4.8 的 Solar / Lunar / EightChar 获取四柱、藏干、纳音、十神、
地势、旬空、大运、流年；并补齐该库未提供的部分：

  1. 神煞 42 种（口径对齐 EightGod 项目《神煞说明》的 Java/lunar 实现，
     含天乙/太极/文昌/国印/天厨/福星/词馆/德秀/天赫/天医/禄神/羊刃/血刃/金舆/
     金神/驿马/桃花/华盖/将星/劫煞/灾煞/亡神/六厄/孤辰/寡宿/红鸾/天喜/红艳/
     披麻/丧门/吊客/勾绞/元辰/童子/学堂/十灵日/十恶大败/魁罡/天罗地网/阴差阳错等）
  2. 十二长生（重点落「禄＝临官」与「绝」两位，分本干视角与日干视角）
  3. 五行力量（天干 + 地支藏干加权，月令 ×3 权重）与日主旺衰的量化参考
  4. 四柱之间的天干五合、相冲，地支六合、三合、三会、六冲、六害、相刑
  5. 真太阳时校正（经度时差 + 均时差）

说明：神煞与旺衰判断属命理流派差异较大的部分，本模块只输出「计算依据」，
最终解释交给大模型，避免把流派分歧硬编码成结论。
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from lunar_python import Lunar, Solar

# ============================================================
# 1. 基础常量
# ============================================================
GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"

GAN_WU_XING = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
ZHI_WU_XING = {
    "子": "水", "丑": "土", "寅": "木", "卯": "木", "辰": "土", "巳": "火",
    "午": "火", "未": "土", "申": "金", "酉": "金", "戌": "土", "亥": "水",
}

SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}  # X 生 SHENG[X]
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}     # X 克 KE[X]

PILLAR_NAMES = ("年柱", "月柱", "日柱", "时柱")

# 地支藏干权重：本气 / 中气 / 余气
HIDE_GAN_WEIGHT = {1: (1.0,), 2: (0.7, 0.3), 3: (0.6, 0.25, 0.15)}
# 月令（月支）权重倍数：月令司权最重，调高到全盘最高权重
MONTH_LING_FACTOR = 3.0

DI_SHI_MEANING = {
    "长生": "初生渐旺，根基初具",
    "沐浴": "尚不稳定，易受牵动",
    "冠带": "渐成气候，开始立身",
    "临官": "力量充盈，可担事任",
    "帝旺": "力量顶点，亦盛极而衰",
    "衰": "由盛转退，后劲减弱",
    "病": "力量疲弱，需外力扶助",
    "死": "本气无用，转靠他柱",
    "墓": "力量入库，蓄而待发",
    "绝": "本气断绝，全靠帮扶",
    "胎": "暗中蕴育，待时发动",
    "养": "受养待成，宜守不宜攻",
}


# ============================================================
# 2. 十神与五行关系
# ============================================================
def shi_shen(day_gan: str, target_gan: str) -> str:
    """以日干为基准，求目标天干的十神。"""
    if target_gan not in GAN_WU_XING:
        return ""
    me, other = GAN_WU_XING[day_gan], GAN_WU_XING[target_gan]
    same_bias = (GAN.index(day_gan) % 2) == (GAN.index(target_gan) % 2)

    if me == other:
        return "比肩" if same_bias else "劫财"
    if SHENG[other] == me:            # 生我者：印
        return "偏印" if same_bias else "正印"
    if SHENG[me] == other:            # 我生者：食伤
        return "食神" if same_bias else "伤官"
    if KE[me] == other:               # 我克者：财
        return "偏财" if same_bias else "正财"
    return "七杀" if same_bias else "正官"   # 克我者：官杀


def wu_xing_category(day_gan: str, element: str) -> str:
    """某五行相对日主的十神大类：比劫 / 印 / 食伤 / 财 / 官杀。"""
    me = GAN_WU_XING[day_gan]
    if element == me:
        return "比劫"
    if SHENG[element] == me:
        return "印"
    if SHENG[me] == element:
        return "食伤"
    if KE[me] == element:
        return "财"
    return "官杀"


# ============================================================
# 3. 神煞查表
# ============================================================
# 神煞口径来源：EightGod（Java + lunar）《神煞说明》，共 41 种 + 本模块保留的禄神 = 42 种。
# 表结构说明：
#   *_GAN_*  以年干/日干为太极点，查四支
#   *_ZHI_*  以年支/日支/月支为太极点，查其余支

# ---- 以年干、日干查地支 ----
TIAN_YI = {
    "甲": ("丑", "未"), "戊": ("丑", "未"), "庚": ("丑", "未"),
    "乙": ("子", "申"), "己": ("子", "申"),
    "丙": ("亥", "酉"), "丁": ("亥", "酉"),
    "壬": ("卯", "巳"), "癸": ("卯", "巳"),
    "辛": ("午", "寅"),
}
TAI_JI = {
    "甲": ("子", "午"), "乙": ("子", "午"),
    "丙": ("卯", "酉"), "丁": ("卯", "酉"),
    "戊": ("辰", "戌", "丑", "未"), "己": ("辰", "戌", "丑", "未"),
    "庚": ("寅", "亥"), "辛": ("寅", "亥"),
    "壬": ("巳", "申"), "癸": ("巳", "申"),
}
WEN_CHANG = {"甲": "巳", "乙": "午", "丙": "申", "丁": "酉", "戊": "申",
             "己": "酉", "庚": "亥", "辛": "子", "壬": "寅", "癸": "卯"}
LU_SHEN = {"甲": "寅", "乙": "卯", "丙": "巳", "丁": "午", "戊": "巳",
           "己": "午", "庚": "申", "辛": "酉", "壬": "亥", "癸": "子"}
# 阳干为羊刃，阴干为「阴刃」，力量较轻
YANG_REN = {"甲": "卯", "乙": "寅", "丙": "午", "丁": "巳", "戊": "午",
            "己": "巳", "庚": "酉", "辛": "申", "壬": "子", "癸": "亥"}
# 金舆（口诀「甲龙乙蛇丙戊羊，丁己猴中庚犬方，辛猪壬牛癸逢虎」→ 丁己取申）
JIN_YU = {"甲": "辰", "乙": "巳", "丙": "未", "丁": "申", "戊": "未",
          "己": "申", "庚": "戌", "辛": "亥", "壬": "丑", "癸": "寅"}
GUO_YIN = {"甲": "戌", "乙": "亥", "丙": "丑", "丁": "寅", "戊": "丑",
           "己": "寅", "庚": "辰", "辛": "巳", "壬": "未", "癸": "申"}
# 天厨贵人：甲巳、乙午、丙巳、丁午、戊申、己酉、庚亥、辛子、壬巳、癸午
TIAN_CHU = {"甲": "巳", "乙": "午", "丙": "巳", "丁": "午", "戊": "申",
            "己": "酉", "庚": "亥", "辛": "子", "壬": "巳", "癸": "午"}
# 福星贵人：甲丙见寅子、乙癸见卯丑、戊申、己未、丁亥、庚午、辛巳、壬辰
FU_XING = {"甲": ("寅", "子"), "丙": ("寅", "子"),
           "乙": ("卯", "丑"), "癸": ("卯", "丑"),
           "戊": ("申",), "己": ("未",), "丁": ("亥",),
           "庚": ("午",), "辛": ("巳",), "壬": ("辰",)}
# 红艳煞（口诀「六丙逢寅辛见鸡，壬癸见申癸见申」各本有异，此处取「壬子癸申」）
HONG_YAN = {"甲": "午", "乙": "午", "丙": "寅", "丁": "未", "戊": "辰",
            "己": "辰", "庚": "戌", "辛": "酉", "壬": "子", "癸": "申"}
# 血刃：甲卯、乙辰、丙午、丁未、戊午、己未、庚酉、辛戌、壬子、癸丑
XUE_REN = {"甲": "卯", "乙": "辰", "丙": "午", "丁": "未", "戊": "午",
           "己": "未", "庚": "酉", "辛": "戌", "壬": "子", "癸": "丑"}
# 词馆：年干/日干 → 命中所见的具体干支
CI_GUAN = {"甲": "庚寅", "乙": "辛卯", "丙": "乙巳", "丁": "戊午", "戊": "丁巳",
           "己": "庚午", "庚": "壬申", "辛": "癸酉", "壬": "癸亥", "癸": "壬戌"}

# 以月支查
TIAN_DE = {"寅": "丁", "卯": "申", "辰": "壬", "巳": "辛", "午": "亥", "未": "甲",
           "申": "癸", "酉": "寅", "戌": "丙", "亥": "乙", "子": "巳", "丑": "庚"}
# 月德：三合局 → 天干
YUE_DE = {"寅": "丙", "午": "丙", "戌": "丙",
          "申": "壬", "子": "壬", "辰": "壬",
          "亥": "甲", "卯": "甲", "未": "甲",
          "巳": "庚", "酉": "庚", "丑": "庚"}
# 天医：月支前一位
TIAN_YI_MED = {"寅": "丑", "卯": "寅", "辰": "卯", "巳": "辰", "午": "巳", "未": "午",
               "申": "未", "酉": "申", "戌": "酉", "亥": "戌", "子": "亥", "丑": "子"}
# 德秀贵人：月支三合组 → (德干, 秀干)，两组同时出现才论
DE_XIU = {
    "寅午戌": ("丙丁", "戊癸"),
    "申子辰": ("壬癸戊己", "甲己丙辛"),
    "巳酉丑": ("庚辛", "乙庚"),
    "亥卯未": ("甲乙", "丁壬"),
}
# 学堂（以年柱纳音查月日时支）
XUE_TANG = {"金": "巳", "木": "亥", "水": "申", "土": "申", "火": "寅"}
# 童子煞：月支分组 + 年纳音五行，均只查日支与时支
TONG_ZI_MONTH = (("寅卯辰申酉戌", ("寅", "子")), ("巳午未亥子丑", ("卯", "未", "辰")))
TONG_ZI_NAYIN = {"金": ("卯", "午"), "木": ("卯", "午"),
                 "水": ("酉", "戌"), "火": ("酉", "戌"), "土": ("辰", "巳")}

# 三合局 → 各神煞落支
SAN_HE_GROUP = {}
for _group, _zhi_list in {
    "申子辰": ("申", "子", "辰"),
    "寅午戌": ("寅", "午", "戌"),
    "巳酉丑": ("巳", "酉", "丑"),
    "亥卯未": ("亥", "卯", "未"),
}.items():
    for _z in _zhi_list:
        SAN_HE_GROUP[_z] = _group

YI_MA = {"申子辰": "寅", "寅午戌": "申", "巳酉丑": "亥", "亥卯未": "巳"}
TAO_HUA = {"申子辰": "酉", "寅午戌": "卯", "巳酉丑": "午", "亥卯未": "子"}
HUA_GAI = {"申子辰": "辰", "寅午戌": "戌", "巳酉丑": "丑", "亥卯未": "未"}
JIANG_XING = {"申子辰": "子", "寅午戌": "午", "巳酉丑": "酉", "亥卯未": "卯"}
JIE_SHA = {"申子辰": "巳", "寅午戌": "亥", "巳酉丑": "寅", "亥卯未": "申"}
WANG_SHEN = {"申子辰": "亥", "寅午戌": "巳", "巳酉丑": "申", "亥卯未": "寅"}
LIU_E = {"申子辰": "卯", "寅午戌": "酉", "亥卯未": "午", "巳酉丑": "子"}
ZAI_SHA = {"申子辰": "午", "寅午戌": "子", "巳酉丑": "卯", "亥卯未": "酉"}

# 以年支查
GU_CHEN = {"亥": "寅", "子": "寅", "丑": "寅",
           "寅": "巳", "卯": "巳", "辰": "巳",
           "巳": "申", "午": "申", "未": "申",
           "申": "亥", "酉": "亥", "戌": "亥"}
GUA_SU = {"亥": "戌", "子": "戌", "丑": "戌",
          "寅": "丑", "卯": "丑", "辰": "丑",
          "巳": "辰", "午": "辰", "未": "辰",
          "申": "未", "酉": "未", "戌": "未"}
HONG_LUAN = {"子": "卯", "丑": "寅", "寅": "丑", "卯": "子", "辰": "亥", "巳": "戌",
             "午": "酉", "未": "申", "申": "未", "酉": "午", "戌": "巳", "亥": "辰"}
TIAN_XI = {k: ZHI[(ZHI.index(v) + 6) % 12] for k, v in HONG_LUAN.items()}
# 披麻：子酉、丑戌、寅亥、卯子、辰丑、巳寅、午卯、未辰、申巳、酉午、戌未、亥申
PI_MA = {"子": "酉", "丑": "戌", "寅": "亥", "卯": "子", "辰": "丑", "巳": "寅",
         "午": "卯", "未": "辰", "申": "巳", "酉": "午", "戌": "未", "亥": "申"}
# 丧门：年支顺推两位
SANG_MEN = {"子": "寅", "丑": "卯", "寅": "辰", "卯": "巳", "辰": "午", "巳": "未",
            "午": "申", "未": "酉", "申": "戌", "酉": "亥", "戌": "子", "亥": "丑"}
# 吊客：年支逆推两位
DIAO_KE = {"子": "戌", "丑": "亥", "寅": "子", "卯": "丑", "辰": "寅", "巳": "卯",
           "午": "辰", "未": "巳", "申": "午", "酉": "未", "戌": "申", "亥": "酉"}
# 勾绞煞：年支顺推两位之外的另一组（子见卯、丑见辰……）
GOU_JIAO = {"子": "卯", "丑": "辰", "寅": "巳", "卯": "午", "辰": "未", "巳": "申",
            "午": "酉", "未": "戌", "申": "亥", "酉": "子", "戌": "丑", "亥": "寅"}
# 元辰：阳男阴女一表、阴男阳女一表
YUAN_CHEN_YANG = {"子": "未", "丑": "申", "寅": "酉", "卯": "戌", "辰": "亥", "巳": "子",
                  "午": "丑", "未": "寅", "申": "卯", "酉": "辰", "戌": "巳", "亥": "午"}
YUAN_CHEN_YIN = {"子": "巳", "丑": "午", "寅": "未", "卯": "申", "辰": "酉", "巳": "戌",
                 "午": "亥", "未": "子", "申": "丑", "酉": "寅", "戌": "卯", "亥": "辰"}

# 日柱 / 年柱整体神煞
KUI_GANG = {"庚辰", "庚戌", "壬辰", "戊戌"}
YIN_YANG_CUO = {"丙子", "丁丑", "戊寅", "辛卯", "壬辰", "癸巳",
                "丙午", "丁未", "戊申", "辛酉", "壬戌", "癸亥"}
SHI_LING = {"甲辰", "乙亥", "丙辰", "丁酉", "戊午", "庚戌", "庚寅", "辛亥", "壬寅", "癸未"}
SHI_E_DA_BAI = {"甲辰", "乙巳", "壬申", "丙申", "丁亥", "庚辰", "戊戌", "癸亥", "辛巳", "己丑"}
JIN_SHEN = {"乙丑", "己巳", "癸酉"}
# 天赫贵人（天赫日）：月支四季组 → 日柱定式
TIAN_HE = {"寅卯辰": "戊寅", "巳午未": "甲午", "申酉戌": "戊申", "亥子丑": "甲子"}

# 神煞释义（供模型组织白话解释，不构成结论）
SHEN_SHA_NOTE = {
    "天乙贵人": "一级吉神，主逢难有助、易得贵人提携",
    "太极贵人": "主聪慧好学、喜究事理，擅玄理与专业深耕",
    "文昌贵人": "主文思、学历、文字与专业资质",
    "天德贵人": "主福德庇护，凶事易解",
    "月德贵人": "主性情慈和、人缘与化解之力",
    "天赫贵人": "主天资聪敏、得时得助，亦名天赫日",
    "天厨贵人": "主食禄丰足、口福与俸禄之助",
    "德秀贵人": "主禀气清秀、品行端方，利于文名与口碑",
    "福星贵人": "主福分、平安顺遂，衣食无忧",
    "国印贵人": "主权责、公职与掌印之象",
    "天医": "主医药、健康调养与疗愈相关缘分",
    "禄神": "主衣食之本、俸禄与稳定收入来源",
    "羊刃": "主刚烈果决，用得宜则担当、用失宜则过刚易折",
    "阴刃": "阴干之刃，刚气较弱，多主敏锐与执拗",
    "血刃": "主外伤、手术、器械之象，宜注意操作安全",
    "金舆": "主车马、体面与配偶助益",
    "金神": "主刚锐果断，宜技术、金属机械、强执行领域",
    "驿马": "主奔波、异地、迁动与外出发展",
    "桃花": "主人缘、异性缘与才艺表现",
    "华盖": "主孤高、艺术宗教与技术专精",
    "将星": "主统御、组织与领导之能",
    "劫煞": "主竞争、耗损与突发变动",
    "灾煞": "主意外阻滞与健康起伏，宜稳中求进",
    "亡神": "主思虑深、善谋划，亦主内耗",
    "六厄": "主阻滞、进退两难之象，宜留缓冲",
    "孤辰": "主性情独立、亲缘较淡",
    "寡宿": "主独处倾向、情感表达内敛",
    "红鸾": "主婚恋喜事之动",
    "天喜": "主喜庆、添丁与情绪舒展",
    "红艳煞": "主人缘魅力与情感表达，易生情事牵动",
    "披麻": "主忧思、服丧之象，多应长辈健康之事",
    "丧门": "主孝服、忧疑，宜留意长辈与自身情绪",
    "吊客": "主吊问、外缘牵扯，忌远行冒进",
    "勾绞煞": "主牵连、纠缠与是非，事易牵扯第三方",
    "元辰": "主耗损、变动频繁，宜守成不宜躁进",
    "童子煞": "民俗说法，主幼年体弱或性情孤清，不作病灾断定",
    "学堂": "主学业、师承与专业精进",
    "词馆": "主文采、著述与文字表达之才",
    "十灵日": "主聪敏机警、直觉强，宜钻研与技艺",
    "十恶大败": "古法视为财禄易散之日，重在理财纪律，不作凶断",
    "魁罡": "主性格刚毅、行事果决，宜武职或强竞争领域",
    "天罗地网": "主行事受限、易生牵绊，宜循规渐进",
    "阴差阳错": "主婚恋波折、聚少离多之象",
}


# ============================================================
# 4. 四柱关系（合冲刑害）
# ============================================================
GAN_HE = {frozenset("甲己"): "土", frozenset("乙庚"): "金", frozenset("丙辛"): "水",
          frozenset("丁壬"): "木", frozenset("戊癸"): "火"}
GAN_CHONG = [frozenset(x) for x in ("甲庚", "乙辛", "丙壬", "丁癸")]
ZHI_HE6 = {frozenset("子丑"): "土", frozenset("寅亥"): "木", frozenset("卯戌"): "火",
           frozenset("辰酉"): "金", frozenset("巳申"): "水", frozenset("午未"): "土"}
ZHI_CHONG = [frozenset(x) for x in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")]
ZHI_HAI = [frozenset(x) for x in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")]
ZHI_XING = [frozenset(x) for x in ("寅巳", "巳申", "申寅", "丑戌", "戌未", "未丑", "子卯")]
ZHI_SELF_XING = {"辰", "午", "酉", "亥"}
SAN_HE_JU = {"申子辰": "水", "寅午戌": "火", "巳酉丑": "金", "亥卯未": "木"}
SAN_HUI_JU = {"寅卯辰": "木", "巳午未": "火", "申酉戌": "金", "亥子丑": "水"}


def _pillar_pairs() -> List[Tuple[str, str]]:
    out = []
    for i in range(4):
        for j in range(i + 1, 4):
            out.append((PILLAR_NAMES[i], PILLAR_NAMES[j]))
    return out


def build_relations(gans: Sequence[str], zhis: Sequence[str]) -> List[str]:
    """计算四柱之间的合、冲、刑、害、三合、三会。"""
    rows: List[str] = []

    for i, j in [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]:
        p1, p2 = PILLAR_NAMES[i], PILLAR_NAMES[j]
        g1, g2 = gans[i], gans[j]
        z1, z2 = zhis[i], zhis[j]

        key = frozenset(g1 + g2) if g1 != g2 else None
        if key and key in GAN_HE:
            rows.append(f"{p1}天干{g1} 与 {p2}天干{g2} 五合化{GAN_HE[key]}")
        if key and key in GAN_CHONG:
            rows.append(f"{p1}天干{g1} 与 {p2}天干{g2} 相冲")

        if z1 != z2:
            zkey = frozenset(z1 + z2)
            if zkey in ZHI_HE6:
                rows.append(f"{p1}{z1}支 与 {p2}{z2}支 六合化{ZHI_HE6[zkey]}")
            if zkey in ZHI_CHONG:
                rows.append(f"{p1}{z1}支 与 {p2}{z2}支 相冲")
            if zkey in ZHI_HAI:
                rows.append(f"{p1}{z1}支 与 {p2}{z2}支 相害")
            if zkey in ZHI_XING:
                rows.append(f"{p1}{z1}支 与 {p2}{z2}支 相刑")
        else:
            if z1 in ZHI_SELF_XING:
                rows.append(f"{p1}{z1}支 与 {p2}{z2}支 自刑")

    zhi_set = set(zhis)
    for combo, element in SAN_HE_JU.items():
        if set(combo) <= zhi_set:
            rows.append(f"地支三合局：{combo}合{element}局")
    for combo, element in SAN_HUI_JU.items():
        if set(combo) <= zhi_set:
            rows.append(f"地支三会方：{combo}会{element}方")

    return rows


# ============================================================
# 5. 神煞计算
# ============================================================
def build_shen_sha(gans: Dict[str, str], zhis: Dict[str, str], day_pillar: str,
                   gender: str = "男", year_nayin: str = "") -> Dict[str, Any]:
    """按《神煞说明》（EightGod / lunar 口径）计算 42 种神煞。

    三条约定：
      1. 「以某干/某支查地支」类，标在**被查到的那一柱**，不是起查的那一柱——
         模型看到"年柱有桃花"就知道是年支上带桃花，不必反推；
      2. 同一柱内同名神煞只记一次，溯源也只留首条；
      3. 每条都写清依据（如「以日干丁查」），模型据此解释，不必自行复算。
    """
    per_pillar: Dict[str, List[str]] = {p: [] for p in PILLAR_NAMES}
    details: List[str] = []

    day_gan = gans["日柱"]
    year_gan = gans["年柱"]
    year_zhi = zhis["年柱"]
    month_zhi = zhis["月柱"]
    day_zhi = zhis["日柱"]
    others = ("月柱", "日柱", "时柱")          # 「查其余三支」用
    day_time = ("日柱", "时柱")                # 童子煞只查日时
    nayin_wx = (year_nayin or "").strip()[-1:]  # 纳音末字即五行，如"海中金"→金

    def _add(pillar: str, name: str, why: str) -> None:
        if name in per_pillar[pillar]:
            return
        per_pillar[pillar].append(name)
        details.append(why)

    def by_zhi(targets, name: str, basis: str, pillars=PILLAR_NAMES) -> None:
        for p in pillars:
            z = zhis[p]
            if z and z in targets:
                _add(p, name, f"{p}支「{z}」见{name}（{basis}）")

    def by_gan(targets, name: str, basis: str, pillars=PILLAR_NAMES) -> None:
        for p in pillars:
            g = gans[p]
            if g and g in targets:
                _add(p, name, f"{p}干「{g}」为{name}（{basis}）")

    # —— 1. 以年干、日干查四支 ——
    for label, gan in (("年干", year_gan), ("日干", day_gan)):
        src = f"以{label}{gan}查"
        by_zhi(TIAN_YI.get(gan, ()), "天乙贵人", src)
        by_zhi(TAI_JI.get(gan, ()), "太极贵人", src)
        by_zhi((WEN_CHANG.get(gan, ""),), "文昌贵人", src)
        by_zhi((GUO_YIN.get(gan, ""),), "国印贵人", src)
        by_zhi((TIAN_CHU.get(gan, ""),), "天厨贵人", src)
        by_zhi(FU_XING.get(gan, ()), "福星贵人", src)
        ci_guan = CI_GUAN.get(gan, "")
        if ci_guan:
            for p in PILLAR_NAMES:
                if gans[p] + zhis[p] == ci_guan:
                    _add(p, "词馆", f"{p}柱「{ci_guan}」为词馆（以{label}{gan}查）")

    # —— 2. 以日干查四支（只日干）——
    src = f"以日干{day_gan}查"
    by_zhi((LU_SHEN.get(day_gan, ""),), "禄神", src)
    yang_ren = YANG_REN.get(day_gan, "")
    if yang_ren:
        by_zhi((yang_ren,), "羊刃" if GAN.index(day_gan) % 2 == 0 else "阴刃", src)
    by_zhi((JIN_YU.get(day_gan, ""),), "金舆", src)
    by_zhi((XUE_REN.get(day_gan, ""),), "血刃", src)
    by_zhi((HONG_YAN.get(day_gan, ""),), "红艳煞", src)

    # —— 3. 三合局组：年支查四支、日支查其余三支 ——
    for label, zhi, scope in (("年支", year_zhi, PILLAR_NAMES),
                              ("日支", day_zhi, ("年柱", "月柱", "时柱"))):
        group = SAN_HE_GROUP.get(zhi, "")
        if not group:
            continue
        suffix = "" if label == "年支" else "(日支查)"
        src = f"以{label}{zhi}查"
        for name, table in (("驿马", YI_MA), ("桃花", TAO_HUA),
                            ("华盖", HUA_GAI), ("将星", JIANG_XING),
                            ("劫煞", JIE_SHA), ("亡神", WANG_SHEN)):
            by_zhi((table[group],), name + suffix, src, scope)
        if label == "年支":
            by_zhi((LIU_E[group],), "六厄", src, others)
            by_zhi((ZAI_SHA[group],), "灾煞", src)

    # —— 4. 以年支查月日时 ——
    for name, table in (("孤辰", GU_CHEN), ("寡宿", GUA_SU),
                        ("红鸾", HONG_LUAN), ("天喜", TIAN_XI),
                        ("披麻", PI_MA), ("丧门", SANG_MEN),
                        ("吊客", DIAO_KE), ("勾绞煞", GOU_JIAO)):
        by_zhi((table.get(year_zhi, ""),), name, f"以年支{year_zhi}查", others)
    # 元辰分两组：阳男阴女 / 阴男阳女（阴阳取年干，与年支同气）
    yang_year = GAN.index(year_gan) % 2 == 0
    is_male = (gender or "男").strip() in ("男", "乾", "male", "1")
    same_parity = yang_year == is_male
    yuan_chen = (YUAN_CHEN_YANG if same_parity else YUAN_CHEN_YIN).get(year_zhi, "")
    by_zhi((yuan_chen,), "元辰",
           f"以年支{year_zhi}查（{'阳男阴女' if same_parity else '阴男阳女'}）", others)

    # —— 5. 以月支查 ——
    tian_de = TIAN_DE.get(month_zhi, "")
    if tian_de in GAN:
        by_gan((tian_de,), "天德贵人", f"以月支{month_zhi}查")
    elif tian_de:
        by_zhi((tian_de,), "天德贵人", f"以月支{month_zhi}查")
    by_gan((YUE_DE.get(month_zhi, ""),), "月德贵人", f"以月支{month_zhi}查")
    by_zhi((TIAN_YI_MED.get(month_zhi, ""),), "天医", f"以月支{month_zhi}查")

    # 德秀贵人：月支三合组里「德」与「秀」两类天干同时出现
    group = SAN_HE_GROUP.get(month_zhi, "")
    if group in DE_XIU:
        de_chars, xiu_chars = DE_XIU[group]
        de_hit = [g for g in gans.values() if g in de_chars]
        xiu_hit = [g for g in gans.values() if g in xiu_chars]
        if de_hit and xiu_hit:
            for p in PILLAR_NAMES:
                g = gans[p]
                if g in de_chars or g in xiu_chars:
                    role = "德" if g in de_chars else "秀"
                    _add(p, "德秀贵人",
                         f"{p}干「{g}」为德秀之{role}"
                         f"（{month_zhi}月，德见{''.join(de_hit)}、秀见{''.join(xiu_hit)}）")

    # 天赫贵人：月支四季组 + 日柱定式（标在日柱）
    for keys, target in TIAN_HE.items():
        if month_zhi in keys and day_pillar == target:
            _add("日柱", "天赫贵人", f"月支{month_zhi}见日柱{day_pillar}，成天赫日")

    # —— 6. 以年柱纳音查 ——
    if nayin_wx in XUE_TANG:
        by_zhi((XUE_TANG[nayin_wx],), "学堂",
               f"年纳音属{nayin_wx}查月日时支", others)
    for keys, targets in TONG_ZI_MONTH:
        if month_zhi in keys:
            by_zhi(targets, "童子煞", f"{month_zhi}月（{keys}）查日时支", day_time)
            break
    if nayin_wx in TONG_ZI_NAYIN:
        by_zhi(TONG_ZI_NAYIN[nayin_wx], "童子煞",
               f"年纳音属{nayin_wx}查日时支", day_time)

    # —— 7. 日柱（及年柱）整体定式 ——
    if day_pillar in KUI_GANG:
        _add("日柱", "魁罡", f"日柱{day_pillar}为魁罡")
    if day_pillar in YIN_YANG_CUO:
        _add("日柱", "阴差阳错", f"日柱{day_pillar}为阴差阳错日")
    if day_pillar in SHI_LING:
        _add("日柱", "十灵日", f"日柱{day_pillar}为十灵日")
    if day_pillar in SHI_E_DA_BAI:
        _add("日柱", "十恶大败", f"日柱{day_pillar}为十恶大败日")
    if day_pillar in JIN_SHEN:
        _add("日柱", "金神", f"日柱{day_pillar}为金神")
    if year_gan + year_zhi in JIN_SHEN:
        _add("年柱", "金神", f"年柱{year_gan}{year_zhi}为金神")
    # 天罗地网：年纳音火命见日支戌亥为天罗，水土命见日支辰巳为地网
    if nayin_wx == "火" and day_zhi in ("戌", "亥"):
        _add("日柱", "天罗地网", f"年纳音火命，日支{day_zhi}为天罗")
    elif nayin_wx in ("水", "土") and day_zhi in ("辰", "巳"):
        _add("日柱", "天罗地网", f"年纳音{nayin_wx}命，日支{day_zhi}为地网")

    notes: Dict[str, str] = {}
    for names in per_pillar.values():
        for n in names:
            key = n.replace("(日支查)", "")
            if key in SHEN_SHA_NOTE:
                notes[key] = SHEN_SHA_NOTE[key]

    return {
        "按柱分布": per_pillar,
        "溯源": details,
        "释义": notes,
    }


# ============================================================
# 6. 十二长生（只落「禄」与「绝」两个关键位）
# ============================================================
CHANG_SHENG_ORDER = ("长生", "沐浴", "冠带", "临官", "帝旺", "衰",
                     "病", "死", "墓", "绝", "胎", "养")
# 各干长生起点：阳干顺行、阴干逆行（甲长生亥、乙长生午……）
CHANG_SHENG_START = {
    "甲": "亥", "乙": "午", "丙": "寅", "丁": "酉", "戊": "寅",
    "己": "酉", "庚": "巳", "辛": "子", "壬": "申", "癸": "卯",
}


def twelve_stages(gan: str) -> Dict[str, str]:
    """某天干的十二长生表：{长生: 支, 沐浴: 支, ...}。"""
    start = ZHI.index(CHANG_SHENG_START[gan])
    step = 1 if GAN.index(gan) % 2 == 0 else -1
    return {stage: ZHI[(start + step * i) % 12] for i, stage in enumerate(CHANG_SHENG_ORDER)}


def build_twelve_stages(gans: Dict[str, str], zhis: Dict[str, str],
                        day_gan: str) -> Dict[str, Any]:
    """十二长生落位，重点给「禄（临官）」与「绝」两个位。

    两套视角分开给，别混用：
      * 本干视角——该柱天干在自己的十二宫里，坐到此支是第几宫（判断自坐强弱）；
      * 日干视角——日干在四支上的十二宫（即传统「地势」，与四柱.地势一致）。
    """
    day_stages = twelve_stages(day_gan)
    lu_jue_table = {
        g: {"禄": twelve_stages(g)["临官"], "绝": twelve_stages(g)["绝"]} for g in GAN
    }

    rows: List[Dict[str, Any]] = []
    lu_hits: List[str] = []
    jue_hits: List[str] = []
    for p in PILLAR_NAMES:
        g, z = gans[p], zhis[p]
        own = twelve_stages(g)
        stage = next((k for k, v in own.items() if v == z), "")
        rows.append({
            "柱": p,
            "天干": g,
            "地支": z,
            "本干坐此支": stage,
            "日干在此支": next((k for k, v in day_stages.items() if v == z), ""),
            "是否自坐禄": stage == "临官",
            "是否自坐绝": stage == "绝",
        })
        if stage == "临官":
            lu_hits.append(f"{p}天干{g}自坐禄（{z}）")
        if stage == "绝":
            jue_hits.append(f"{p}天干{g}自坐绝（{z}）")

    lu_zhi, jue_zhi = day_stages["临官"], day_stages["绝"]
    return {
        "说明": "十二长生以天干为体：阳干顺行、阴干逆行。禄＝临官，天干本气得力之位；"
                "绝＝本气断绝、全靠帮扶。本干坐此支＝该柱天干自己的十二宫，"
                "日干在此支＝传统「地势」，两者不是一回事。",
        "日干": day_gan,
        "日干十二宫": day_stages,
        "日干禄绝": {
            "禄在": lu_zhi,
            "命中禄位柱": [p for p in PILLAR_NAMES if zhis[p] == lu_zhi],
            "绝在": jue_zhi,
            "命中绝位柱": [p for p in PILLAR_NAMES if zhis[p] == jue_zhi],
        },
        "十干禄绝": lu_jue_table,
        "四柱定位": rows,
        "自坐禄": lu_hits or ["四柱天干均未自坐禄位"],
        "自坐绝": jue_hits or ["四柱天干均未自坐绝位"],
    }


# ============================================================
# 7. 真太阳时
# ============================================================
# 常用出生地经度（东经正值），用于真太阳时校正；同省城市可近似套用
CITY_LONGITUDE: Dict[str, float] = {
    "北京": 116.41, "上海": 121.47, "天津": 117.20, "重庆": 106.55,
    "广州": 113.26, "深圳": 114.06, "东莞": 113.75, "佛山": 113.12, "珠海": 113.58,
    "惠州": 114.42, "中山": 113.39, "江门": 113.08, "汕头": 116.68,
    "杭州": 120.15, "宁波": 121.55, "温州": 120.70, "嘉兴": 120.75, "绍兴": 120.58,
    "金华": 119.65, "台州": 121.42, "湖州": 120.09,
    "南京": 118.80, "苏州": 120.58, "无锡": 120.30, "常州": 119.97, "南通": 120.86,
    "徐州": 117.28, "扬州": 119.42, "盐城": 120.16,
    "合肥": 117.23, "芜湖": 118.38, "蚌埠": 117.39, "阜阳": 115.81,
    "福州": 119.30, "厦门": 118.09, "泉州": 118.68, "漳州": 117.65,
    "南昌": 115.89, "九江": 115.99, "赣州": 114.93,
    "济南": 117.00, "青岛": 120.38, "烟台": 121.39, "潍坊": 119.10, "临沂": 118.35,
    "威海": 122.12, "淄博": 118.05, "泰安": 117.09, "济宁": 116.59, "菏泽": 115.48,
    "郑州": 113.62, "洛阳": 112.45, "开封": 114.31, "新乡": 113.93, "南阳": 112.53,
    "武汉": 114.30, "宜昌": 111.29, "襄阳": 112.14, "十堰": 110.79,
    "长沙": 112.94, "株洲": 113.13, "衡阳": 112.57, "常德": 111.70,
    "成都": 104.07, "绵阳": 104.68, "德阳": 104.40, "宜宾": 104.64, "泸州": 105.44,
    "西安": 108.95, "咸阳": 108.71, "宝鸡": 107.24, "榆林": 109.73,
    "太原": 112.55, "大同": 113.30, "石家庄": 114.51, "保定": 115.46, "唐山": 118.18,
    "秦皇岛": 119.60, "邯郸": 114.49,
    "沈阳": 123.43, "大连": 121.62, "鞍山": 122.99, "长春": 125.32, "吉林": 126.55,
    "哈尔滨": 126.64, "大庆": 125.10, "齐齐哈尔": 123.92,
    "呼和浩特": 111.75, "包头": 109.84, "鄂尔多斯": 109.99,
    "南宁": 108.37, "桂林": 110.29, "柳州": 109.42, "北海": 109.12,
    "海口": 110.20, "三亚": 109.51, "贵阳": 106.63, "遵义": 106.93,
    "昆明": 102.83, "曲靖": 103.80, "大理": 100.23,
    "拉萨": 91.11, "兰州": 103.83, "西宁": 101.78, "银川": 106.28, "乌鲁木齐": 87.62,
    "中国香港": 114.17, "香港": 114.17, "中国澳门": 113.54, "澳门": 113.54,
    "中国台湾": 121.52, "台北": 121.52, "高雄": 120.31,
}


def resolve_city_longitude(city: str) -> Tuple[Optional[float], str]:
    """把出生地名称解析为经度。返回 (经度, 说明)。"""
    if not city:
        return None, "未提供出生地"
    raw = city.strip()
    if raw in CITY_LONGITUDE:
        return CITY_LONGITUDE[raw], f"已匹配「{raw}」"
    for key, lon in CITY_LONGITUDE.items():
        if key in raw or raw in key:
            return lon, f"按「{key}」近似取值"
    return None, f"未收录出生地「{raw}」，未做真太阳时校正"


def equation_of_time_minutes(solar: Solar) -> float:
    """均时差（分钟），近似公式，误差约 ±0.5 分钟。"""
    day_of_year = solar.getDayOfYear() if hasattr(solar, "getDayOfYear") else _day_of_year(solar)
    b = math.radians(360.0 * (day_of_year - 81) / 365.0)
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def _day_of_year(solar: Solar) -> int:
    return datetime(solar.getYear(), solar.getMonth(), solar.getDay()).timetuple().tm_yday


def true_solar_time(solar: Solar, longitude: float) -> Tuple[Solar, Dict[str, Any]]:
    """按出生地经度校正为真太阳时。longitude 为东经正值。"""
    offset = (longitude - 120.0) * 4.0 + equation_of_time_minutes(solar)
    total_minutes = solar.getHour() * 60 + solar.getMinute() + offset
    day_shift = 0
    while total_minutes < 0:
        total_minutes += 1440
        day_shift -= 1
    while total_minutes >= 1440:
        total_minutes -= 1440
        day_shift += 1
    hour = int(total_minutes // 60)
    minute = int(round(total_minutes - hour * 60))
    if minute == 60:
        minute = 0
        hour += 1
    base = Solar.fromYmdHms(solar.getYear(), solar.getMonth(), solar.getDay(), 0, 0, 0)
    if day_shift:
        base = base.next(day_shift)
    corrected = Solar.fromYmdHms(base.getYear(), base.getMonth(), base.getDay(),
                                 hour % 24, minute, 0)
    info = {
        "启用": True,
        "经度": longitude,
        "经度时差_分钟": round((longitude - 120.0) * 4.0, 1),
        "均时差_分钟": round(equation_of_time_minutes(solar), 1),
        "合计校正_分钟": round(offset, 1),
        "校正后时间": corrected.toYmdHms(),
    }
    return corrected, info


# ============================================================
# 8. 命盘主函数
# ============================================================
_PREFIX = {0: "Year", 1: "Month", 2: "Day", 3: "Time"}


def _parse_solar(year: int, month: int, day: int, hour: int, minute: int,
                 calendar_type: str, is_leap_month: bool) -> Solar:
    ct = (calendar_type or "阳历").strip()
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"日期时间不合法：{year}-{month}-{day} {hour}:{minute}")
    if ct in ("阴历", "农历", "旧历", "lunar"):
        try:
            lunar = Lunar.fromYmdHms(year, -abs(month) if is_leap_month else month,
                                     day, hour, minute, 0)
        except Exception as exc:
            raise ValueError(
                f"农历日期不存在：{year}年{'闰' if is_leap_month else ''}{month}月{day}日（{exc}）"
            )
        # 校验农历日期真实存在（闰月/大小月），防止 30 日被静默顺延
        if abs(lunar.getMonth()) != abs(month) or lunar.getDay() != day:
            raise ValueError(
                f"农历日期不存在：{year}年{'闰' if is_leap_month else ''}{month}月{day}日"
            )
        return lunar.getSolar()
    try:
        datetime(year, month, day)  # 严格校验公历大小月与闰年
    except ValueError:
        raise ValueError(f"公历日期不存在：{year}-{month}-{day}")
    return Solar.fromYmdHms(year, month, day, hour, minute, 0)


def _branch_weights(index: int, hides_len: int) -> Tuple[float, ...]:
    """单个地支的藏干权重；月支（月令）整体放大 MONTH_LING_FACTOR 倍。

    月令司权最重是有基础的：月支决定当令之气，其余三支只作辅助。
    取 3 倍后，月支一支即占全盘 3/10，月令本气（3×0.6＝1.8）
    必然高于任何天干（1.0）与其余地支本气（0.6）。
    """
    ws = HIDE_GAN_WEIGHT.get(hides_len, (1.0,))
    factor = MONTH_LING_FACTOR if index == 1 else 1.0
    return tuple(w * factor for w in ws)


RISK_LABELS = ("偏弱（异党力量占优）", "略弱（异党略占优）",
               "略强（同党略占优）", "偏强（同党力量占优）")


def _five_element_strength(gans: Sequence[str], hide_gan_lists: Sequence[Sequence[str]],
                           day_gan: str, month_zhi: str = "") -> Dict[str, Any]:
    """天干计 1.0，地支按藏干权重加权，月支再乘月令系数。

    「量化参考」只看同党/异党占比；「综合参考」再按月令增/减一档——
    得令（旺/相）上调，月令克身（死）下调，休/囚不动。
    单看占比会把「得令但财重」的盘判成偏弱，和月令结论打架，所以必须分两个口径给。
    """
    weight: Dict[str, float] = {"木": 0.0, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0}
    for g in gans:
        weight[GAN_WU_XING[g]] += 1.0
    for idx, hides in enumerate(hide_gan_lists):
        for g, w in zip(hides, _branch_weights(idx, len(hides))):
            weight[GAN_WU_XING[g]] += w
    total = sum(weight.values()) or 1.0
    percent = {k: round(v / total * 100, 1) for k, v in weight.items()}

    me = GAN_WU_XING[day_gan]
    yin = next((e for e in SHENG if SHENG[e] == me), "")   # 生我者为印
    same = round(weight[me] + weight.get(yin, 0.0), 2)
    other = round(total - same, 2)
    ratio = same / total

    if ratio >= 0.62:
        tier = 3
    elif ratio >= 0.5:
        tier = 2
    elif ratio >= 0.38:
        tier = 1
    else:
        tier = 0

    ling = _month_ling_status(day_gan, month_zhi) if month_zhi else ""
    delta = 0
    if "旺" in ling or "相" in ling:
        delta = 1
    elif "死" in ling:
        delta = -1
    final_tier = max(0, min(3, tier + delta))

    return {
        "权重方案": {
            "天干": "每个 1.0（年、月、日、时共 4.0）",
            "地支藏干": "本气 0.6 / 中气 0.25 / 余气 0.15，每支合计 1.0",
            "月令加成": f"月支整体 ×{MONTH_LING_FACTOR}（计 3.0 分），为全盘最高权重",
            "满分": round(total, 2),
        },
        "计数_天干加藏干": {k: sum(1 for g in gans if GAN_WU_XING[g] == k)
                     + sum(1 for h in hide_gan_lists for g in h if GAN_WU_XING[g] == k)
                     for k in weight},
        "加权力量": {k: round(v, 2) for k, v in weight.items()},
        "力量占比_百分比": percent,
        "日主五行": me,
        "生我者_印": yin,
        "同党_比劫加印": same,
        "异党_财官食伤": other,
        "同党占比_百分比": round(ratio * 100, 1),
        "量化参考": RISK_LABELS[tier],
        "综合参考": RISK_LABELS[final_tier],
        "综合参考说明": "＝同党占比档位按月令增减一档：月令得令（旺/相）+1，月令克身（死）-1，休/囚不变。"
                       "谈身强身弱请优先用「综合参考」，占比只作旁证。",
    }


def _month_ling_status(day_gan: str, month_zhi: str) -> str:
    me, mz = GAN_WU_XING[day_gan], ZHI_WU_XING[month_zhi]
    if mz == me:
        return "得令·旺（月令与日主同气）"
    if SHENG[mz] == me:
        return "得令·相（月令生扶日主）"
    if SHENG[me] == mz:
        return "失令·休（日主泄气于月令）"
    if KE[me] == mz:
        return "失令·囚（日主克月令，耗力）"
    return "失令·死（月令克日主，压力最大）"


def build_chart(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    gender: str = "男",
    calendar_type: str = "阳历",
    is_leap_month: bool = False,
    longitude: Optional[float] = None,
    sect: int = 2,
    dayun_rounds: int = 10,
    name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """构建完整八字命盘。

    Args:
        sect: 1=晚子时归次日（日柱按 23:00 后换日），2=晚子时仍算当日（默认）
        longitude: 出生地经度（东经为正），传入则按真太阳时校正
        dayun_rounds: 大运轮数，每轮 10 年
    """
    solar = _parse_solar(year, month, day, hour, minute, calendar_type, is_leap_month)

    solar_info: Dict[str, Any] = {"是否校正": False}
    if longitude is not None:
        solar, solar_info = true_solar_time(solar, float(longitude))
        solar_info["是否校正"] = True

    lunar = solar.getLunar()
    ec = lunar.getEightChar()
    ec.setSect(sect)

    gans: List[str] = []
    zhis: List[str] = []
    pillars: Dict[str, Any] = {}

    for idx in range(4):
        p = _PREFIX[idx]
        gan = getattr(ec, f"get{p}Gan")()
        zhi = getattr(ec, f"get{p}Zhi")()
        gans.append(gan)
        zhis.append(zhi)
        hides = getattr(ec, f"get{p}HideGan")() or []
        pillars[PILLAR_NAMES[idx]] = {
            "干支": getattr(ec, f"get{p}")(),
            "天干": gan,
            "地支": zhi,
            "天干五行": GAN_WU_XING[gan],
            "地支五行": ZHI_WU_XING[zhi],
            "天干十神": getattr(ec, f"get{p}ShiShenGan")(),
            "藏干": hides,
            "藏干十神": getattr(ec, f"get{p}ShiShenZhi")(),
            "纳音": getattr(ec, f"get{p}NaYin")(),
            "地势_长生十二神": getattr(ec, f"get{p}DiShi")(),
            "地势释义": DI_SHI_MEANING.get(getattr(ec, f"get{p}DiShi")(), ""),
            "旬": getattr(ec, f"get{p}Xun")(),
            "旬空_空亡": getattr(ec, f"get{p}XunKong")(),
        }

    day_gan = gans[2]
    hide_lists = [pillars[n]["藏干"] for n in PILLAR_NAMES]

    # —— 五行与旺衰 ——
    wu_xing = _five_element_strength(gans, hide_lists, day_gan, zhis[1])
    wu_xing["月令"] = f"{zhis[1]}月（{ZHI_WU_XING[zhis[1]]}）"
    wu_xing["日主得令情况"] = _month_ling_status(day_gan, zhis[1])
    wu_xing["五行对应十神"] = {
        e: wu_xing_category(day_gan, e) for e in ("木", "火", "土", "金", "水")
    }

    # —— 十神统计 ——
    ss_count: Dict[str, int] = {}
    ss_power: Dict[str, float] = {}
    for idx, pillar_name in enumerate(PILLAR_NAMES):
        info = pillars[pillar_name]
        if pillar_name != "日柱":
            g_ss = info["天干十神"]
            ss_count[g_ss] = ss_count.get(g_ss, 0) + 1
            ss_power[g_ss] = ss_power.get(g_ss, 0.0) + 1.0
        hides = info["藏干"]
        for h_ss, w in zip(info["藏干十神"], _branch_weights(idx, len(hides))):
            ss_count[h_ss] = ss_count.get(h_ss, 0) + 1
            ss_power[h_ss] = round(ss_power.get(h_ss, 0.0) + w, 2)
    ss_group: Dict[str, float] = {}
    for k, v in ss_power.items():
        grp = ("比劫" if k in ("比肩", "劫财") else
               "印" if k in ("正印", "偏印") else
               "食伤" if k in ("食神", "伤官") else
               "财" if k in ("正财", "偏财") else "官杀")
        ss_group[grp] = round(ss_group.get(grp, 0.0) + v, 2)

    # —— 大运与流年 ——
    gender_int = 1 if (gender or "男").strip() in ("男", "乾", "male", "1") else 0
    yun = ec.getYun(gender_int, 1)
    da_yun_rows: List[Dict[str, Any]] = []
    for dy in yun.getDaYun(dayun_rounds + 1):
        if dy.getIndex() < 1:
            continue
        gz = dy.getGanZhi()
        if not gz:
            continue
        d_gan, d_zhi = gz[0], gz[1]
        liu_nian = [
            f"{ln.getYear()}|{ln.getAge()}岁|{ln.getGanZhi()}"
            for ln in dy.getLiuNian()
        ]
        da_yun_rows.append({
            "序": dy.getIndex(),
            "干支": gz,
            "天干十神": shi_shen(day_gan, d_gan),
            "地支十神_本气": shi_shen(day_gan, _ben_qi(d_zhi)),
            "起止年": f"{dy.getStartYear()}-{dy.getEndYear()}",
            "起止年龄": f"{dy.getStartAge()}-{dy.getEndAge()}岁",
            "旬空": dy.getXunKong(),
            "流年": liu_nian,
        })

    current: Dict[str, Any] = {}
    now = now or datetime.now()
    cy = now.year
    for row in da_yun_rows:
        s, _, e = row["起止年"].partition("-")
        if int(s) <= cy <= int(e):
            current["当前年份"] = cy
            current["所处大运"] = {k: row[k] for k in ("干支", "天干十神", "起止年", "起止年龄")}
            for item in row["流年"]:
                y, age, gz = item.split("|")
                if int(y) == cy:
                    current["流年"] = {
                        "年份": int(y), "年龄": age, "干支": gz,
                        "天干十神": shi_shen(day_gan, gz[0]),
                        "地支十神_本气": shi_shen(day_gan, _ben_qi(gz[1])),
                        "与日主关系": "流年天干" + shi_shen(day_gan, gz[0]),
                    }
            break

    # —— 节气信息 ——
    prev_jie = lunar.getPrevJie()
    next_jie = lunar.getNextJie()
    jieqi = {
        "上一节": f"{prev_jie.getName()} {prev_jie.getSolar().toYmd()}",
        "下一节": f"{next_jie.getName()} {next_jie.getSolar().toYmd()}",
        "月令": f"{zhis[1]}月",
    }

    chart: Dict[str, Any] = {
        "基本信息": {
            "姓名": name or "未提供",
            "性别": "男" if gender_int == 1 else "女",
            "公历": solar.toYmdHms(),
            "农历": f"{lunar.toString()} {lunar.getTimeZhi()}时",
            "生肖": lunar.getYearShengXiao(),
            "日主": f"{day_gan}{GAN_WU_XING[day_gan]}",
            "八字": ec.toString(),
            "真太阳时校正": solar_info,
            "日柱流派": "晚子时算当日(sect=2)" if sect == 2 else "晚子时算次日(sect=1)",
            "节气": jieqi,
        },
        "四柱": pillars,
        "五行与旺衰": wu_xing,
        "十神": {
            "个数": ss_count,
            "力量": ss_power,
            "分类力量": ss_group,
            "说明": "力量＝天干计 1.0；地支藏干按本气0.6/中气0.25/余气0.15，"
                    f"月支（月令）再×{MONTH_LING_FACTOR} 加权",
        },
        "神煞": build_shen_sha(dict(zip(PILLAR_NAMES, gans)),
                              dict(zip(PILLAR_NAMES, zhis)),
                              pillars["日柱"]["干支"],
                              gender="男" if gender_int == 1 else "女",
                              year_nayin=pillars["年柱"]["纳音"]),
        "十二长生": build_twelve_stages(dict(zip(PILLAR_NAMES, gans)),
                                     dict(zip(PILLAR_NAMES, zhis)), day_gan),
        "四柱关系": build_relations(gans, zhis),
        "胎元命宫身宫": {
            "胎元": ec.getTaiYuan(),
            "胎元纳音": ec.getTaiYuanNaYin(),
            "胎息": ec.getTaiXi(),
            "命宫": ec.getMingGong(),
            "命宫纳音": ec.getMingGongNaYin(),
            "身宫": ec.getShenGong(),
            "身宫纳音": ec.getShenGongNaYin(),
        },
        "起运": {
            "顺逆": "顺排" if yun.isForward() else "逆排",
            "起运年龄": f"{yun.getStartYear()}年{yun.getStartMonth()}月{yun.getStartDay()}天",
            "起运公历": yun.getStartSolar().toYmd(),
        },
        "大运": da_yun_rows,
        "当前": current,
    }
    return chart


def _ben_qi(zhi: str) -> str:
    """取地支本气天干（用于地支十神判断）。"""
    from lunar_python.util import LunarUtil
    hides = LunarUtil.ZHI_HIDE_GAN.get(zhi) or []
    return hides[0] if hides else ""


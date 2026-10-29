# -*- coding: utf-8 -*-
"""工具层自检：不依赖界面与网络，可直接 python tests/smoke_tools.py 运行。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tools import cast_liuyao, explain_term, get_bazi_chart, query_almanac  # noqa: E402
from app.tools import liuyao  # noqa: E402
from app.storage import Store  # noqa: E402


def check_tables() -> None:
    """六十四卦名称表与八宫归属必须完整覆盖。"""
    assert len(liuyao.NAMES) == 64, f"卦名表应有 64 条，实际 {len(liuyao.NAMES)}"
    names = set(liuyao.NAMES.values())
    assert len(names) == 64, f"卦名重复，唯一名 {len(names)}"
    missing = names - set(liuyao._PALACE_OF)
    assert not missing, f"缺少宫位归属：{missing}"
    for palace, rows in liuyao.PALACES.items():
        assert len(rows) == 8, f"{palace}宫应有 8 卦"
    print("[OK] 六十四卦 / 八宫表完整")


def check_liuyao() -> None:
    for seed in (1, 7, 42, 100):
        data = json.loads(cast_liuyao.invoke(
            {"question": "这次面试能否通过", "seed": seed}))
        assert data["本卦"]["卦名"] in liuyao.NAMES.values()
        assert len(data["本卦"]["六爻"]) == 6
        if data["变卦"]:
            assert len(data["变卦"]["六爻"]) == 6
    sample = json.loads(cast_liuyao.invoke({"question": "八月签约是否顺利", "seed": 7}))
    print("[OK] 六爻：", sample["本卦"]["卦名"], "→",
          (sample["变卦"] or {}).get("卦名", "静卦"), "| 动爻", sample["动爻"])
    print("     世应:", sample["本卦"]["世爻"], sample["本卦"]["应爻"],
          "| 宫:", sample["本卦"]["卦宫"])


def check_bazi() -> None:
    data = json.loads(get_bazi_chart.invoke({
        "year": 1990, "month": 5, "day": 12, "gender": "男",
        "hour": 14, "minute": 30, "birth_city": "临沂",
    }))
    assert "错误" not in data, data.get("错误")
    print("[OK] 八字：", data["基本信息"]["八字"], "| 日主", data["基本信息"]["日主"])
    err = json.loads(get_bazi_chart.invoke({
        "year": 1990, "month": 2, "day": 30, "gender": "男"}))
    assert "错误" in err
    print("[OK] 非法日期被拒：", err["错误"])


def check_almanac() -> None:
    data = json.loads(query_almanac.invoke({"date": "2026-10-27", "with_hours": True}))
    print("[OK] 黄历：", data["农历"], "| 值神", data["值神"],
          "| 宜", "、".join(data["宜"][:4]))
    # 库返回 13 条（早子时与晚子时分开），至少覆盖十二时辰
    assert len(data.get("十二时辰", [])) >= 12


def check_glossary() -> None:
    data = json.loads(explain_term.invoke({"term": "伤官"}))
    assert data["释义"]
    fuzzy = json.loads(explain_term.invoke({"term": "贵人"}))
    assert fuzzy.get("匹配")
    print("[OK] 术语：伤官 / 贵人（模糊匹配 %d 条）" % len(fuzzy["匹配"]))


def check_storage() -> None:
    tmp = Path(tempfile.gettempdir()) / "fate_test.db"
    if tmp.exists():
        os.remove(tmp)
    store = Store(tmp)
    conv = store.create_conversation()
    store.add_message(conv["id"], "user", "测试问题")
    store.add_message(conv["id"], "assistant", "测试回答")
    title = store.maybe_auto_title(conv["id"], "测试问题")
    assert title == "测试问题"
    assert len(store.get_messages(conv["id"])) == 2
    assert store.list_conversations()[0]["msg_count"] == 2
    store.delete_conversation(conv["id"])
    assert store.stats()["messages"] == 0
    print("[OK] SQLite 会话读写与删除")
    os.remove(tmp)


if __name__ == "__main__":
    check_tables()
    check_liuyao()
    check_bazi()
    check_almanac()
    check_glossary()
    check_storage()
    print("\n全部自检通过")

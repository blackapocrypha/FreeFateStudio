# -*- coding: utf-8 -*-
"""个人信息（长期记忆）自检：校验规则、真太阳时开关、提示词注入、工具输出。

跑之前会备份已有档案，结束后原样还原，不污染用户数据。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app import agent as agent_mod  # noqa: E402
from app import profile as profile_mod  # noqa: E402
from app.server import server  # noqa: E402
from app.storage import store  # noqa: E402
from app.tools.memory import get_my_profile  # noqa: E402


def show(label: str, value) -> None:
    print(f"- {label}: {value}")


def main() -> int:
    backup = store.get_profile()
    base = server.start()
    try:
        # 1. 正常保存：有出生地，应启用真太阳时
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "男",
                "birth_place": "临沂",
            },
            timeout=10,
        )
        assert r.status_code == 200, r.text
        info = r.json()
        show("保存后 configured", info["configured"])
        show("真太阳时", info["solar_time"])
        assert info["configured"] is True
        assert info["solar_time"]["enabled"] is True
        assert abs(info["solar_time"]["longitude"] - 118.35) < 1e-6
        assert info["year"] == 1990 and info["hour"] == 14 and info["minute"] == 30

        # 2. 读回一致
        again = httpx.get(f"{base}/api/profile", timeout=10).json()
        assert again["birth_place"] == "临沂" and again["gender"] == "男"

        # 3. HTTP 健康检查暴露档案状态
        health = httpx.get(f"{base}/api/health", timeout=10).json()
        assert health["profile_ready"] is True
        show("health.profile_ready", health["profile_ready"])

        # 4. 提示词注入
        block = profile_mod.prompt_block()
        assert "出生时间：1990-05-12 14:30（公历）" in block
        assert 'birth_city="临沂"' in block
        assert "真太阳时：已启用" in block
        system_content = agent_mod._system_message().content
        assert "本人档案" in system_content and "临沂" in system_content
        show("system prompt 长度", len(system_content))
        show("提示词档案段", block.strip().splitlines()[3:8])

        # 5. 工具输出
        payload = json.loads(get_my_profile.invoke({}))
        assert payload["已填写"] is True
        assert payload["排盘入参"]["hour"] == 14
        assert payload["排盘入参"]["birth_city"] == "临沂"
        show("工具排盘入参", payload["排盘入参"])

        # 6. 出生地留空 → 不启用真太阳时
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "男",
                "birth_place": "",
            },
            timeout=10,
        )
        info = r.json()
        assert info["solar_time"]["enabled"] is False
        assert info["solar_time"]["longitude"] is None
        block = profile_mod.prompt_block()
        assert "真太阳时：未启用" in block and "birth_city" not in block
        payload = json.loads(get_my_profile.invoke({}))
        assert payload["排盘入参"]["birth_city"] is None
        show("留空时说明", info["solar_time"]["note"])

        # 7. 只填空白 → 等同于留空
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "女",
                "birth_place": "   ",
            },
            timeout=10,
        )
        assert r.json()["solar_time"]["enabled"] is False
        assert r.json()["gender"] == "女"

        # 8. 不存在的地名 → 保留输入但仍不启用真太阳时
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990-05-12",
                "birth_time": "14:30",
                "gender": "男",
                "birth_place": "瓦坎达",
            },
            timeout=10,
        )
        info = r.json()
        assert info["solar_time"]["enabled"] is False
        assert info["birth_place"] == "瓦坎达"
        assert "未收录" in info["solar_time"]["note"]
        show("不存在地名说明", info["solar_time"]["note"])

        # 9. 各类非法输入
        bad_cases = [
            ({"birth_date": "", "birth_time": "14:30", "gender": "男"}, "出生日期"),
            ({"birth_date": "1990-02-30", "birth_time": "14:30", "gender": "男"}, "真实存在"),
            ({"birth_date": "1990-5-12", "birth_time": "", "gender": "男"}, "时刻"),
            ({"birth_date": "1990-5-12", "birth_time": "25:00", "gender": "男"}, "时刻"),
            ({"birth_date": "1990-5-12", "birth_time": "14:30", "gender": ""}, "性别"),
            ({"birth_date": "1899-1-1", "birth_time": "14:30", "gender": "男"}, "年份"),
            ({"birth_date": "2999-1-1", "birth_time": "14:30", "gender": "男"}, "晚于今天"),
        ]
        for payload_in, keyword in bad_cases:
            r = httpx.put(f"{base}/api/profile", json=payload_in, timeout=10)
            detail = r.json().get("detail", "") if r.status_code == 400 else r.text
            assert r.status_code == 400, f"{payload_in} 应被拒绝，实际 {r.status_code}"
            assert keyword in detail, f"{payload_in} 提示不含「{keyword}」：{detail}"
        show("非法输入用例数", len(bad_cases))

        # 10. 规范化回填：14:5 → 14:05，1990/5/2 → 1990-05-02
        r = httpx.put(
            f"{base}/api/profile",
            json={
                "birth_date": "1990/5/2",
                "birth_time": "14:5",
                "gender": "女",
                "birth_place": "北京",
            },
            timeout=10,
        )
        info = r.json()
        assert info["birth_date"] == "1990-05-02" and info["birth_time"] == "14:05"
        show("规范化", f'{info["birth_date"]} {info["birth_time"]}')

        # 11. 清空
        r = httpx.delete(f"{base}/api/profile", timeout=10)
        assert r.json()["configured"] is False
        assert "尚未填写" in profile_mod.prompt_block()
        assert json.loads(get_my_profile.invoke({}))["已填写"] is False
        assert httpx.get(f"{base}/api/health", timeout=10).json()["profile_ready"] is False
        show("清空后", "configured=False，提示词回到未填写分支")

    finally:
        if backup:
            httpx.put(
                f"{base}/api/profile",
                json={
                    "birth_date": backup["birth_date"],
                    "birth_time": backup["birth_time"],
                    "gender": backup["gender"],
                    "birth_place": backup["birth_place"],
                },
                timeout=10,
            )
            print("已还原原档案")
        else:
            httpx.delete(f"{base}/api/profile", timeout=10)
            print("原无档案，保持为空")

    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""设置读写自检：走本地 API 改 .env，验证热重建与错误分支，最后还原原文件。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app import agent as agent_mod  # noqa: E402
from app import config  # noqa: E402
from app.server import server  # noqa: E402


def main() -> int:
    env_file = config.env_path()
    backup = env_file.read_text(encoding="utf-8") if env_file.exists() else None
    original_model = config.model_name()
    original_key = config.api_key()

    base = server.start()
    ok = True
    try:
        print("env 路径:", env_file)
        r = httpx.get(f"{base}/api/settings", timeout=5).json()
        print("初始:", r)
        assert r["model"] == original_model
        assert r["api_key_masked"], "掩码应非空"

        graph_before = agent_mod.get_graph()
        rev_before = config.config_revision()

        # 1. 改模型名 + 换 Key
        r = httpx.put(
            f"{base}/api/settings",
            json={"model": "deepseek-chat", "api_key": "sk-test-1234567890"},
            timeout=5,
        )
        print("保存:", r.status_code, r.json())
        assert r.status_code == 200
        body = r.json()
        assert body["model"] == "deepseek-chat"
        assert body["api_key_masked"] == "sk-tes…7890"
        assert config.config_revision() == rev_before + 1

        text = env_file.read_text(encoding="utf-8")
        assert "FATE_MODEL=deepseek-chat" in text, text
        assert "DEEPSEEK_API_KEY=sk-test-1234567890" in text, text
        assert "FATE_THINKING=0" in text, "其它键必须保留"

        # 2. 图应重建，checkpointer 复用
        graph_after = agent_mod.get_graph()
        assert graph_after is not graph_before, "配置变更后图必须重建"
        assert agent_mod._SAVER is not None

        # 3. 留空 Key 不得覆盖已存值
        r = httpx.put(f"{base}/api/settings", json={"model": "deepseek-v4-flash"}, timeout=5)
        assert r.json()["api_key_masked"] == "sk-tes…7890", r.json()

        # 4. 空模型名必须拒绝
        r = httpx.put(f"{base}/api/settings", json={"model": "   "}, timeout=5)
        print("空模型名:", r.status_code, r.json())
        assert r.status_code == 400

        # 5. 健康检查读到新模型
        h = httpx.get(f"{base}/api/health", timeout=5).json()
        assert h["model"] == "deepseek-v4-flash", h
        assert h["api_key_ready"] is True
        print("健康检查:", h["model"], h["api_key_ready"])
        print("全部通过")
    except AssertionError as exc:
        ok = False
        print("断言失败:", exc)
    finally:
        server.stop()
        # 还原 .env 与进程内环境变量
        if backup is not None:
            env_file.write_text(backup, encoding="utf-8")
        config.save_settings(original_model, original_key)
        if backup is not None:
            env_file.write_text(backup, encoding="utf-8")
        print("已还原:", env_file.read_text(encoding="utf-8").strip().replace("\n", " | "))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

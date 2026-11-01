# -*- coding: utf-8 -*-
"""生成 README 顶部的 preview.png。

不连服务、不调模型：直接把一段示例对话塞进界面再截图，
所以展示的是排盘样式与新的输入卡片，不代表真实回答。
按 1.64 倍缩放采集，得到 1770×1230 的清晰图。
用法：python tests/ui_preview.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["QT_QPA_PLATFORM"] = "windows"

from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402

from app.ui.theme import QSS  # noqa: E402
from app.ui.window import MainWindow  # noqa: E402

OUT = ROOT / "preview.png"
SCALE = 1.64

QUESTION = "男，1990年5月12日下午两点半，山东临沂。看事业"

ANSWER = """## 一、命局骨架

- 辛金日主生于巳月，官星当令，日支酉金为自身根气，属「身弱官旺」的格局。
- 月柱己巳、时柱乙未，土金相生的链条完整，走到金土运时力量能接上。
- 辛金喜壬水淘洗，命局缺壬，才华需要外部平台托起来，不擅长自己吆喝。

## 二、事业方向

- 命宫辛巳、身宫己丑，与月柱同气，事业能量集中在「专业能力的表达与转化」。
- 行业属性上，你的火土金偏旺，可优先考虑能源电子、传媒、工程地产、机械金融法务
  这几类中偏「技术＋交易」的岗位，比纯文科纯行政更合盘。
- 现在 37 岁（2026 丙午年，劫财坐比肩）——流年比劫极旺，这是典型的「同辈竞争加剧、
  分成变多、易有合伙邀约」的年份。今年适合守、适合把已有盘子做扎实，不适合开新的合伙摊子。

## 三、需要留意的两处结构

- **日支酉与时支未相冲相刑**：酉为夫妻宫与自身根基，未为子女宫与晚运。相冲落在自身内在状态上，
  表现为「想动、待不住」，做决定容易反复，对应到事业，就是不要在同一个时间段并行两条主线。
- **日柱丁丑为阴差阳错日**（此处以命局实盘校正后取酉为夫妻宫）：不求吉凶论，
  只提示时间安排上要留缓冲，别把日程排到极限。

## 四、时间窗：未来三年的财运节奏

| 年份 | 干支 | 十神 | 结构提示 |
|---|---|---|---|
| 2026 | 丙午 | 劫财·比肩 | 比劫最旺，竞争与分账明显；宜守成、把现有资源做深，慎合伙、慎大额支出 |
| 2027 | 丁未 | 比肩·食神 | 未土到位，食神生财；丑未冲再次引发，机会与支出同时放大，宜「先锁定再投入」 |
| 2028 | 戊申 | 伤官·正财 | 进入乙酉大运，伤官生财、正财到位，是财路上更顺的一年，适合把前两年的积累转成实际收入 |

给你一个可执行的判断标准：**2026 年是「不加杠杆的一年」**，2027 年是「先落袋再扩张的一年」，
2028 年才是「可以主动加码的一年」。这三个节奏如果走对了，39 岁后的大运承接会顺很多。

---

命理属传统文化参考，不替代医疗、法律、投资等专业决策。上面提到的具体年份，是结构上的倾向与节奏提示，
实际决策还要结合你手上的真实条件。"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow("http://127.0.0.1:1", {"model": "deepseek-v4-flash",
                                            "api_key_ready": True,
                                            "profile_ready": True})
    win.resize(1080, 748)
    win.show()

    # 侧栏塞两条示意条目，别让预览图左边空着
    for text in ("男，1990年5月12日下午两点...", "男，1990年5月12日下午两点...",
                 "简批一下我的八字"):
        win.conv_list.addItem(QListWidgetItem(text))
    win.conv_list.clearSelection()

    win.title_label.setText("今年事业与财运")
    win.area.clear()
    win.area.add_user(QUESTION)
    win.area.add_tool("排八字")
    win.area.add_assistant(ANSWER)
    win.ctx_ring.set_state({
        "tokens": 44_800, "window": 128_000, "threshold": 111_616,
        "threshold_percent": 87.2, "reserve": 16_384, "keep_recent": 20_000,
        "percent": 35.0, "enabled": True, "over": False,
    })
    win.composer.edit.setPlainText("那明年的财运呢？需要注意什么")
    win.composer.focus_input()

    # 滚到对话中段，让表格露出来
    for _ in range(60):
        app.processEvents()
        time.sleep(0.01)
    bar = win.scroll.verticalScrollBar()
    bar.setValue(int(bar.maximum() * 0.50))
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)

    # 放大绘制而不是放大截图：文字保持矢量清晰
    pm = QPixmap(int(win.width() * SCALE), int(win.height() * SCALE))
    pm.setDevicePixelRatio(SCALE)
    pm.fill(QColor("#FFFFFF"))
    win.render(pm)
    pm.save(str(OUT))
    print("已生成", OUT, pm.width(), "x", pm.height())
    return 0


if __name__ == "__main__":
    sys.exit(main())

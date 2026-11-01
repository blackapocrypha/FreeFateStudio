# -*- coding: utf-8 -*-
"""输入框右下角的上下文进度环。

对应 Pi Agent 的 compaction 机制，用户需要一眼看出「还剩多少窗口」：
  - 环长 = 上下文占用 / 模型窗口
  - 越过压缩阈值（窗口 - reserveTokens）后转成琥珀色，真到阈值会变红
  - 压缩进行中不显示比例，改成一段绕圈旋转的弧，表示正在生成摘要
和 WorkBuddy 一样，环本身不占版面，细节都在悬停提示里。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

DIAMETER = 24
_THICK = 3.0

MUTED_ARC = "#7A7A72"
WARN_ARC = "#B7791F"
DANGER_ARC = "#B03A2E"
DONE_ARC = "#2E7D4F"
TRACK = "#E6E6E1"


def fmt_tokens(value: float) -> str:
    n = float(value or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(int(n))


class ContextRing(QWidget):
    """自绘圆环；不接收焦点、不抢键盘，纯展示 + 悬停提示。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(DIAMETER, DIAMETER)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.WhatsThisCursor)
        self._percent = 0.0
        self._state: Dict[str, Any] = {}
        self._busy = False
        self._flash = 0  # 压缩完成后的绿色脉冲剩余帧
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    # ---------------- 状态 ----------------
    def apply_event(self, event: Dict[str, Any]) -> None:
        """吃一条 SSE 上下文事件（context / compacting / compacted）。"""
        kind = event.get("type")
        if kind == "compacting":
            self.set_busy(True, event)
        elif kind == "compacted":
            self.set_busy(False)
            if not event.get("skipped") and not event.get("error"):
                self._flash = 26
                self._timer.start()
            self._refresh_tooltip()
        else:
            self.set_state(event)

    def set_state(self, snapshot: Dict[str, Any]) -> None:
        if not snapshot or "percent" not in snapshot:
            return
        self._state = dict(snapshot)
        self._percent = float(snapshot.get("percent") or 0.0)
        self._refresh_tooltip()
        self.update()

    def set_busy(self, busy: bool, snapshot: Optional[Dict[str, Any]] = None) -> None:
        self._busy = busy
        if snapshot:
            self._state.update({
                "tokens": snapshot.get("tokens", self._state.get("tokens", 0)),
                "window": snapshot.get("window", self._state.get("window", 0)),
                "threshold": snapshot.get("threshold", self._state.get("threshold", 0)),
            })
        if busy:
            self._timer.start()
        elif self._flash <= 0:
            self._timer.stop()
        self._refresh_tooltip()
        self.update()

    def reset(self) -> None:
        """切到没有历史的新会话时清空。"""
        self._state = {}
        self._percent = 0.0
        self._busy = False
        self._flash = 0
        self._timer.stop()
        self._refresh_tooltip()
        self.update()

    # ---------------- 内部 ----------------
    def _arc_color(self) -> QColor:
        if self._flash > 0:
            return QColor(DONE_ARC)
        threshold_pct = float(self._state.get("threshold_percent") or 100.0)
        if self._percent >= min(100.0, threshold_pct + 0.001):
            return QColor(DANGER_ARC)
        if self._percent >= threshold_pct * 0.7:
            return QColor(WARN_ARC)
        return QColor(MUTED_ARC)

    def _refresh_tooltip(self) -> None:
        state = self._state
        if self._busy:
            before = fmt_tokens(state.get("tokens", 0))
            window = fmt_tokens(state.get("window", 0))
            self.setToolTip(
                f"正在压缩上下文…\n已用 {before} / {window} tokens\n"
                "早期对话会被压成结构化摘要，最近的原文原样保留"
            )
            return
        if not state.get("window"):
            self.setToolTip("上下文占用\n开始对话后这里会显示窗口使用率")
            return

        used = fmt_tokens(state.get("tokens", 0))
        window = fmt_tokens(state.get("window", 0))
        threshold = fmt_tokens(state.get("threshold", 0))
        keep = fmt_tokens(state.get("keep_recent", 0))
        reserve = fmt_tokens(state.get("reserve", 0))
        pct = f"{float(state.get('percent') or 0):.1f}%"
        lines = [
            f"上下文占用 {pct}",
            f"{used} / {window} tokens",
            f"压缩阈值 {threshold}（为输出预留 {reserve}）",
            f"压缩后保留最近 {keep} 的原文",
        ]
        if state.get("enabled") is False:
            lines.append("自动压缩已在 .env 中关闭（FATE_COMPACTION=0）")
        elif state.get("over"):
            lines.append("已超过阈值，下一轮发言前会自动压缩")
        self.setToolTip("\n".join(lines))

    def _tick(self) -> None:
        if self._busy:
            self._angle = (self._angle + 12.0) % 360.0
        if self._flash > 0:
            self._flash -= 1
            if self._flash <= 0 and not self._busy:
                self._timer.stop()
        self.update()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        side = min(self.width(), self.height())
        inset = _THICK / 2 + 1.0
        box = QRectF(
            (self.width() - side) / 2 + inset,
            (self.height() - side) / 2 + inset,
            side - inset * 2,
            side - inset * 2,
        )

        track_pen = QPen(QColor(TRACK), _THICK, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(box, 0, 360 * 16)

        if self._busy:
            arc_pen = QPen(QColor(WARN_ARC), _THICK, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(arc_pen)
            painter.drawArc(box, int((90 - self._angle) * 16), int(-100 * 16))
        else:
            # 最小 10 度：占用极低时也要能看见环在，否则空白会话看着像没画
            span = max(10.0, min(360.0, self._percent * 3.6))
            arc_pen = QPen(self._arc_color(), _THICK, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(arc_pen)
            # Qt 的角度以 1/16 度计，0 度在 3 点钟方向；减 90 度让起点在正上方
            painter.drawArc(box, 90 * 16, int(-span * 16))

        painter.end()

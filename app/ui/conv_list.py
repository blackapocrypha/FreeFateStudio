# -*- coding: utf-8 -*-
"""左侧会话列表：鼠标悬浮时在行尾显示「⋯」，点开是一个删除入口。

列表项仍用原生 QListWidget 绘制（背景、选中态、hover 底色全部沿用 QSS），
三个点由代理在自己的 paint 里叠加，因此不会出现「item 里塞控件导致
选中背景画不到控件底下」的问题。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QListWidget,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

DOTS_SIZE = 22
DOTS_RIGHT = 9
# 与 theme.py 里 item 的右内边距保持一致：文字提前收住，三个点不会压字
DOTS_RESERVE = 32
DOT_COLOR = "#8C8C86"


def dots_rect(item_rect: QRect) -> QRect:
    """三个点占据的矩形（相对列表项）。绘制与命中判定共用，改一处即可。"""
    return QRect(
        item_rect.right() - DOTS_RIGHT - DOTS_SIZE,
        item_rect.center().y() - DOTS_SIZE // 2,
        DOTS_SIZE,
        DOTS_SIZE,
    )


class ConvItemDelegate(QStyledItemDelegate):
    """先让原生代理把整行画完，再按悬浮态叠加三个点。"""

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: D102
        super().paint(painter, option, index)
        if not (option.state & QStyle.State_MouseOver):
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(DOT_COLOR))
        rect = dots_rect(option.rect)
        cx = rect.center().x() + 0.5
        cy = rect.center().y() + 0.5
        for dx in (-5.0, 0.0, 5.0):
            painter.drawEllipse(QPointF(cx + dx, cy), 1.6, 1.6)
        painter.restore()


class DeleteMenu(QFrame):
    """点「⋯」弹出的小面板，目前只有一个删除入口。"""

    removeConfirmed = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(
            parent.window(),
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._cid: Optional[str] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        card = QFrame()
        card.setObjectName("menuCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 36))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        box = QVBoxLayout(card)
        box.setContentsMargins(6, 6, 6, 6)
        self.btn = QPushButton("删除对话")
        self.btn.setObjectName("menuDanger")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(self._confirm)
        box.addWidget(self.btn)

    def popup_at(self, cid: str, anchor: QRect) -> None:
        self._cid = cid
        self.setFixedWidth(132)
        self.adjustSize()
        x = anchor.right() - self.width()
        y = anchor.bottom() + 4
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
            y = min(y, area.bottom() - self.height() - 8)
            y = max(area.top() + 8, y)
        self.move(x, y)
        self.show()
        self.raise_()

    def _confirm(self) -> None:
        cid = self._cid
        self.hide()
        if cid:
            self.removeConfirmed.emit(cid)


class ConvList(QListWidget):
    """会话列表。行尾三个点只在悬浮时出现，点击后弹出删除入口。"""

    deleteRequested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("convList")
        self.setFrameShape(QFrame.NoFrame)
        self.setItemDelegate(ConvItemDelegate(self))
        # 没有这两个 setMouseTracking，代理拿不到 State_MouseOver，三个点不会出现
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._menu: Optional[DeleteMenu] = None
        self._press_on_dots = False

    # ---------------- 命中判定 ----------------
    def _hits_dots(self, pos: QPoint) -> bool:
        index = self.indexAt(pos)
        if not index.isValid():
            return False
        return dots_rect(self.visualRect(index)).contains(pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._hits_dots(event.position().toPoint()):
            # 吞掉按下：点三个点时不应该顺带切换会话
            self._press_on_dots = True
            return
        self._press_on_dots = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._press_on_dots and event.button() == Qt.LeftButton:
            self._press_on_dots = False
            if self._hits_dots(event.position().toPoint()):
                self._open_menu(event.position().toPoint())
            return
        super().mouseReleaseEvent(event)

    # ---------------- 删除入口 ----------------
    def _open_menu(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        cid = index.data(Qt.UserRole) if index.isValid() else None
        if not cid:
            return
        if self._menu is None:
            self._menu = DeleteMenu(self)
            self._menu.removeConfirmed.connect(self.deleteRequested.emit)
        rect = self.visualRect(index)
        anchor = QRect(self.viewport().mapToGlobal(rect.topLeft()), rect.size())
        self._menu.popup_at(str(cid), anchor)

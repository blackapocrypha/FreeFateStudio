# -*- coding: utf-8 -*-
"""自绘单色图标。

Windows 上 "⚙" 会被 Segoe UI Emoji 接管渲染成彩色 emoji，与极简黑白风格冲突，
因此齿轮用 QPainterPath 直接画：外圈梯形齿 + 中心镂空，2 倍过采样保证高分屏清晰。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap, QPolygonF


def _clamp01(value: float) -> float:
    return 0.0 if value < 0 else (1.0 if value > 1 else value)


def _tooth_profile(angle: float, teeth: int) -> float:
    """把一个齿的相位映射成 0（齿根）→ 1（齿顶）的梯形轮廓。"""
    phase = (angle * teeth / (2 * math.pi)) % 1.0
    rise = _clamp01((phase - 0.22) / 0.16)
    fall = _clamp01((0.78 - phase) / 0.16)
    return rise * fall


def gear_pixmap(size: int, color: str, teeth: int = 8, samples: int = 160) -> QPixmap:
    scale = 2
    px = QPixmap(size * scale, size * scale)
    px.setDevicePixelRatio(scale)
    px.fill(Qt.transparent)

    center = QPointF(size / 2.0, size / 2.0)
    r_tip = size * 0.465
    r_root = size * 0.345
    r_hole = size * 0.145

    points = []
    for i in range(samples):
        angle = 2 * math.pi * i / samples
        r = r_root + (r_tip - r_root) * _tooth_profile(angle, teeth)
        points.append(
            QPointF(center.x() + r * math.sin(angle), center.y() - r * math.cos(angle))
        )

    body = QPainterPath()
    body.addPolygon(QPolygonF(points))
    body.closeSubpath()

    hole = QPainterPath()
    hole.addEllipse(
        QRectF(center.x() - r_hole, center.y() - r_hole, r_hole * 2, r_hole * 2)
    )

    shape = body.subtracted(hole)

    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(shape)
    painter.end()
    return px


def gear_icon(size: int = 18, color: str = "#8C8C86", active: str = "#17171A") -> QIcon:
    icon = QIcon()
    icon.addPixmap(gear_pixmap(size, color), QIcon.Normal)
    icon.addPixmap(gear_pixmap(size, color), QIcon.Disabled)
    icon.addPixmap(gear_pixmap(size, active), QIcon.Active)
    icon.addPixmap(gear_pixmap(size, active), QIcon.Selected)
    return icon

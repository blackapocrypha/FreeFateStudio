# -*- coding: utf-8 -*-
"""左下角设置浮层（Codex 式：小页签弹在齿轮上方）。

两个入口，手风琴式互斥展开（同时只开一个，避免面板过长顶出屏幕）：
  模型配置   模型名称 + API Key，落盘 .env
  个人信息   出生日期 / 时刻 / 性别 / 出生地，落盘 SQLite（fate.db 的 profile 表）

出生地留空、只填空格、或地名不在经度表内时，一律不启用真太阳时——
这条规则在服务端（app/profile.py）判定，界面只负责显示结果。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .client import ApiClient

PANEL_WIDTH = 296
CARD_MARGIN = 10


def _elide(text: str, width: int, mode=Qt.ElideMiddle) -> str:
    """单行省略，完整内容放 tooltip，避免路径把面板撑成两行。"""
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication

    return QFontMetrics(QApplication.font()).elidedText(text, mode, width)


class MenuRow(QFrame):
    """一行可点击的条目：左侧文字、右侧箭头。"""

    clicked = Signal()

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("settingsItem")
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(6)

        self._label = QLabel(text)
        self._label.setObjectName("menuRowText")
        self._label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._value = QLabel("")
        self._value.setObjectName("menuRowValue")
        self._value.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._chevron = QLabel("›")
        self._chevron.setObjectName("menuRowChevron")
        self._chevron.setAttribute(Qt.WA_TransparentForMouseEvents)

        row.addWidget(self._label)
        row.addStretch(1)
        row.addWidget(self._value)
        row.addSpacing(2)
        row.addWidget(self._chevron)

    def set_value(self, text: str) -> None:
        self._value.setText(text)

    def set_open(self, opened: bool) -> None:
        self._chevron.setText("˅" if opened else "›")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SettingsPopup(QFrame):
    """点击侧栏齿轮弹出的小面板。"""

    settingsSaved = Signal(dict)
    profileSaved = Signal(dict)

    def __init__(self, api: ApiClient, anchor: QWidget) -> None:
        super().__init__(
            anchor.window(),
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.api = api
        self.anchor = anchor
        self._snapshot: Dict[str, Any] = {}
        self._profile_snapshot: Dict[str, Any] = {}
        self._open_panel: Optional[str] = None
        self._closed_at = 0.0
        self._self_closing = False
        self._build()
        self.setFixedWidth(PANEL_WIDTH + CARD_MARGIN * 2)

    # ---------------- 兼容旧测试：模型表单是否展开 ----------------
    @property
    def _form_open(self) -> bool:
        return self._open_panel == "model"

    # ---------------- 构建 ----------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(CARD_MARGIN, CARD_MARGIN, CARD_MARGIN, CARD_MARGIN)

        card = QFrame()
        card.setObjectName("settingsCard")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 40))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        box = QVBoxLayout(card)
        box.setContentsMargins(8, 10, 8, 8)
        box.setSpacing(2)

        title = QLabel("设置")
        title.setObjectName("settingsTitle")
        box.addWidget(title)

        self.item = MenuRow("模型配置")
        self.item.clicked.connect(lambda: self._toggle_panel("model"))
        box.addWidget(self.item)

        self.form = self._build_model_form()
        box.addWidget(self.form)

        self.profile_item = MenuRow("个人信息")
        self.profile_item.clicked.connect(lambda: self._toggle_panel("profile"))
        box.addWidget(self.profile_item)

        self.profile_form = self._build_profile_form()
        box.addWidget(self.profile_form)

    def _build_model_form(self) -> QWidget:
        form_host = QWidget()
        form = QVBoxLayout(form_host)
        form.setContentsMargins(10, 2, 2, 4)
        form.setSpacing(3)

        provider = QLabel("DeepSeek")
        provider.setObjectName("settingsHint")
        form.addWidget(provider)

        model_label = QLabel("模型名称")
        model_label.setObjectName("fieldLabel")
        form.addWidget(model_label)

        self.model_edit = QLineEdit()
        self.model_edit.setObjectName("settingsField")
        self.model_edit.setPlaceholderText("deepseek-v4-flash")
        self.model_edit.returnPressed.connect(self._save)
        form.addWidget(self.model_edit)

        key_label = QLabel("API Key")
        key_label.setObjectName("fieldLabel")
        form.addSpacing(3)
        form.addWidget(key_label)

        self.key_edit = QLineEdit()
        self.key_edit.setObjectName("settingsField")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-…")
        self.key_edit.returnPressed.connect(self._save)
        form.addWidget(self.key_edit)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 4, 0, 0)
        bottom.setSpacing(8)
        self.status = QLabel("")
        self.status.setObjectName("settingsHint")
        self.status.setProperty("state", "idle")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)

        self.save_btn = QPushButton("保存")
        self.save_btn.setObjectName("primary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFixedWidth(72)
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.save_btn, 0, Qt.AlignRight)
        form.addLayout(bottom)

        self.path_label = QLabel("")
        self.path_label.setObjectName("settingsHint")
        self.path_label.setWordWrap(True)
        form.addWidget(self.path_label)

        form_host.setVisible(False)
        return form_host

    def _build_profile_form(self) -> QWidget:
        host = QWidget()
        form = QVBoxLayout(host)
        form.setContentsMargins(10, 2, 2, 4)
        form.setSpacing(3)

        # 日期 / 时刻同一行，省掉 60px 竖向空间
        row = QHBoxLayout()
        row.setSpacing(8)

        date_col = QVBoxLayout()
        date_col.setSpacing(3)
        date_label = QLabel("出生日期（公历）")
        date_label.setObjectName("fieldLabel")
        date_col.addWidget(date_label)
        self.date_edit = QLineEdit()
        self.date_edit.setObjectName("settingsField")
        self.date_edit.setPlaceholderText("1990-05-12")
        self.date_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9\-/.]{0,10}"), self)
        )
        self.date_edit.returnPressed.connect(self._save_profile)
        date_col.addWidget(self.date_edit)
        row.addLayout(date_col, 3)

        time_col = QVBoxLayout()
        time_col.setSpacing(3)
        time_label = QLabel("时刻")
        time_label.setObjectName("fieldLabel")
        time_col.addWidget(time_label)
        self.time_edit = QLineEdit()
        self.time_edit.setObjectName("settingsField")
        self.time_edit.setPlaceholderText("14:30")
        self.time_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9:：]{0,5}"), self)
        )
        self.time_edit.returnPressed.connect(self._save_profile)
        time_col.addWidget(self.time_edit)
        row.addLayout(time_col, 2)
        form.addLayout(row)

        gender_label = QLabel("性别")
        gender_label.setObjectName("fieldLabel")
        form.addSpacing(4)
        form.addWidget(gender_label)

        self.gender_group = QButtonGroup(self)
        self.gender_group.setExclusive(True)
        g_row = QHBoxLayout()
        g_row.setSpacing(6)
        self.male_btn = QPushButton("男")
        self.female_btn = QPushButton("女")
        for btn in (self.male_btn, self.female_btn):
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(30)
            self.gender_group.addButton(btn)
            g_row.addWidget(btn, 1)
        form.addLayout(g_row)

        place_label = QLabel("出生地（可留空）")
        place_label.setObjectName("fieldLabel")
        form.addSpacing(4)
        form.addWidget(place_label)

        self.place_edit = QLineEdit()
        self.place_edit.setObjectName("settingsField")
        self.place_edit.setPlaceholderText("如 临沂，留空则不校正真太阳时")
        self.place_edit.returnPressed.connect(self._save_profile)
        form.addWidget(self.place_edit)

        self.place_hint = QLabel("")
        self.place_hint.setObjectName("settingsHint")
        self.place_hint.setWordWrap(True)
        form.addWidget(self.place_hint)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 4, 0, 0)
        bottom.setSpacing(8)
        self.profile_status = QLabel("")
        self.profile_status.setObjectName("settingsHint")
        self.profile_status.setProperty("state", "idle")
        self.profile_status.setWordWrap(True)
        bottom.addWidget(self.profile_status, 1)

        self.profile_save_btn = QPushButton("保存")
        self.profile_save_btn.setObjectName("primary")
        self.profile_save_btn.setCursor(Qt.PointingHandCursor)
        self.profile_save_btn.setFixedWidth(72)
        self.profile_save_btn.clicked.connect(self._save_profile)
        bottom.addWidget(self.profile_save_btn, 0, Qt.AlignRight)
        form.addLayout(bottom)

        host.setVisible(False)
        return host

    # ---------------- 打开 / 收起 ----------------
    def popup(self) -> None:
        self._snapshot = self.api.settings() or {}
        self.model_edit.setText(str(self._snapshot.get("model") or ""))
        self.key_edit.clear()
        self._refresh_key_placeholder()
        path = str(self._snapshot.get("env_path") or "")
        self.path_label.setText(_elide(f"写入 {path}", 250) if path else "无法确定 .env 位置")
        self.path_label.setToolTip(path)
        self._message("")
        self.item.set_value(_elide(str(self._snapshot.get("model") or ""), 130, Qt.ElideRight))

        self._load_profile()
        self._set_panel(None)
        # 先 show 再 _fit：Qt 不会为隐藏窗口的后代派发布局请求，
        # 收起过表单再重开时 totalSizeHint 会拿到上一轮的缓存值（高度卡在 358 不回落）。
        # 这两个调用在同一轮事件循环里同步完成，不会看到中间态。
        self.show()
        self._fit()
        self.raise_()

    def toggle(self) -> None:
        if self.isVisible():
            self._self_closing = True
            self.hide()
            return
        # Qt.Popup 靠「点击外部」关闭，而那一下点击的后续事件可能又落到齿轮上，
        # 触发一次 toggle → 关掉立刻重开。用刚被外部点掉的时间戳挡掉这一次。
        if time.monotonic() - self._closed_at < 0.25:
            return
        self.popup()

    def hideEvent(self, event) -> None:  # noqa: N802
        # 只记「被外部点击/代码关掉」的时间；自己 toggle 收起不算，否则连点两下会失效
        if not self._self_closing:
            self._closed_at = time.monotonic()
        self._self_closing = False
        super().hideEvent(event)

    def _toggle_panel(self, which: str) -> None:
        self._set_panel(None if self._open_panel == which else which)

    def _set_panel(self, which: Optional[str]) -> None:
        """展开状态自己记账：浮层隐藏时 form.isVisible() 恒为 False，
        直接拿它取反会把状态搞反。"""
        self._open_panel = which
        self.form.setVisible(which == "model")
        self.profile_form.setVisible(which == "profile")
        self.item.set_open(which == "model")
        self.profile_item.set_open(which == "profile")
        self._fit()
        if which == "model":
            self.model_edit.setFocus()
            self.model_edit.selectAll()
        elif which == "profile":
            self.date_edit.setFocus()
            self.date_edit.selectAll()

    def _set_form_open(self, opened: bool) -> None:
        """旧接口保留：只控制模型配置面板。"""
        self._set_panel("model" if opened else None)

    def _fit(self) -> None:
        """按布局实际需要的尺寸钉死窗口。

        两个坑叠在一起：
        1. 顶层窗口的 adjustSize() 只增不减（实测 sizeHint 已是 95，高度仍停在 299）；
        2. 子控件 show/hide 发的是排队中的 LayoutRequest，当场读 layout 拿到的还是旧值，
           必须先把这类事件派发掉，再取 totalSizeHint。
        """
        lay = self.layout()
        self.form.updateGeometry()
        self.profile_form.updateGeometry()
        lay.invalidate()
        QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        lay.activate()
        height = max(lay.totalSizeHint().height(), self.minimumSizeHint().height())
        if height > 0:
            self.setFixedHeight(height)
        self._reposition()

    def _reposition(self) -> None:
        anchor_pos = self.anchor.mapToGlobal(QPoint(0, 0))
        x = anchor_pos.x() - CARD_MARGIN
        y = anchor_pos.y() - self.height() - 8
        screen = self.anchor.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
            y = min(y, area.bottom() - self.height() - 8)
            y = max(area.top() + 8, y)
        self.move(x, y)

    # ---------------- 模型配置 ----------------
    def _refresh_key_placeholder(self) -> None:
        masked = str(self._snapshot.get("api_key_masked") or "")
        if masked:
            self.key_edit.setPlaceholderText(f"已保存 {masked}，留空不修改")
        else:
            self.key_edit.setPlaceholderText("sk-…")

    def _message(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("state", "err" if error else ("ok" if text else "idle"))
        # 属性选择器需要重新 polish 才会生效
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _save(self) -> None:
        model = self.model_edit.text().strip()
        if not model:
            self._message("模型名称不能为空", error=True)
            return
        key = self.key_edit.text().strip()
        self.save_btn.setEnabled(False)
        try:
            snapshot = self.api.save_settings(model, key or None)
        finally:
            self.save_btn.setEnabled(True)

        if not snapshot:
            self._message("保存失败：本地服务未响应", error=True)
            return
        self._snapshot = snapshot
        self.key_edit.clear()
        self._refresh_key_placeholder()
        self.item.set_value(_elide(str(snapshot.get("model") or ""), 130, Qt.ElideRight))
        self._message("已保存，下一句话即生效")
        self.settingsSaved.emit(snapshot)

    # ---------------- 个人信息 ----------------
    def _load_profile(self) -> None:
        info = self.api.profile() or {}
        self._profile_snapshot = info
        self.date_edit.setText(str(info.get("birth_date") or ""))
        self.time_edit.setText(str(info.get("birth_time") or ""))
        self.place_edit.setText(str(info.get("birth_place") or ""))

        gender = str(info.get("gender") or "")
        self.male_btn.setChecked(gender == "男")
        self.female_btn.setChecked(gender == "女")

        self._profile_message("")
        self._refresh_place_hint()
        self._refresh_profile_value()

    def _refresh_profile_value(self) -> None:
        info = self._profile_snapshot or {}
        if info.get("configured"):
            text = f"{info.get('birth_date')} {info.get('birth_time')}"
            self.profile_item.set_value(_elide(text, 130, Qt.ElideRight))
        elif info.get("birth_date"):
            self.profile_item.set_value("信息不完整")
        else:
            self.profile_item.set_value("未填写")

    def _refresh_place_hint(self) -> None:
        solar = (self._profile_snapshot or {}).get("solar_time") or {}
        if not (self._profile_snapshot or {}).get("configured"):
            self.place_hint.setText("留空或地名查不到时不启用真太阳时")
            return
        if solar.get("enabled"):
            self.place_hint.setText(
                f"{solar.get('note')}，经度 {solar.get('longitude')}°E，已启用真太阳时"
            )
        else:
            self.place_hint.setText(str(solar.get("note") or "未启用真太阳时"))

    def _profile_message(self, text: str, error: bool = False) -> None:
        self.profile_status.setText(text)
        self.profile_status.setProperty(
            "state", "err" if error else ("ok" if text else "idle")
        )
        self.profile_status.style().unpolish(self.profile_status)
        self.profile_status.style().polish(self.profile_status)

    def _save_profile(self) -> None:
        gender = "男" if self.male_btn.isChecked() else ("女" if self.female_btn.isChecked() else "")
        self.profile_save_btn.setEnabled(False)
        try:
            info, err = self.api.save_profile(
                self.date_edit.text().strip(),
                self.time_edit.text().strip(),
                gender,
                self.place_edit.text().strip(),
            )
        finally:
            self.profile_save_btn.setEnabled(True)

        if err or not info:
            self._profile_message(err or "保存失败：本地服务未响应", error=True)
            return

        self._profile_snapshot = info
        # 规范化回填（14:5 → 14:05，1990/5/2 → 1990-05-02）
        self.date_edit.setText(str(info.get("birth_date") or ""))
        self.time_edit.setText(str(info.get("birth_time") or ""))
        self._refresh_place_hint()
        self._refresh_profile_value()
        if info.get("solar_time", {}).get("enabled"):
            self._profile_message("已保存，之后说「我」即按此排盘")
        else:
            self._profile_message("已保存（未启用真太阳时）")
        self.profileSaved.emit(info)

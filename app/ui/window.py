# -*- coding: utf-8 -*-
"""主窗口：左侧会话列表 + 右侧对话流，Codex 式极简排布。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextOption
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_SUBTITLE, APP_TITLE
from . import md
from .client import ApiClient, ChatWorker
from .context_ring import ContextRing
from .conv_list import ConvList
from .icons import gear_icon
from .settings_popup import SettingsPopup
from .theme import MUTED


# ------------------------------------------------------------
# 基础部件
# ------------------------------------------------------------
class ChatText(QTextBrowser):
    """按内容高度自适应的富文本块（不出现内部滚动条）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("background: transparent; border: none;")
        self.document().setDocumentMargin(0)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().contentsChanged.connect(self._sync_height)
        self._syncing = False

    def set_markdown(self, text: str) -> None:
        self.setHtml(md.to_html(text))

    def set_html_doc(self, html: str) -> None:
        self.setHtml(html)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_height()

    def _sync_height(self) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            width = max(80, self.viewport().width())
            self.document().setTextWidth(width)
            height = int(self.document().size().height()) + 2
            if abs(height - self.height()) > 1:
                self.setFixedHeight(height)
        finally:
            self._syncing = False


class UserBubble(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setMaximumWidth(620)
        self.setStyleSheet(
            "background:#F0F0EC; border-radius:10px; padding:10px 14px;"
            "color:#17171A; font-size:13px;"
        )


class ToolChip(QLabel):
    def __init__(self, label: str) -> None:
        super().__init__(f"{label}")
        self.setStyleSheet(
            f"color:{MUTED}; font-size:11px; background:transparent;"
            "border:1px solid #E8E8E4; border-radius:9px; padding:2px 8px;"
        )
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class Composer(QFrame):
    """输入卡片：输入区在上，上下文环与发送键收在框内右下角。

    这样排是为了对齐主流 Agent 产品的手感——按钮不再挂在框外，
    多行输入时卡片整体长高、按钮始终贴住底边；空内容时按钮置灰不可点。
    """

    submitted = Signal()

    _MIN_EDIT = 26
    _MAX_EDIT = 150

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("composerCard")
        self.setProperty("active", False)

        box = QVBoxLayout(self)
        box.setContentsMargins(15, 12, 10, 9)
        box.setSpacing(7)

        self.edit = QTextEdit()
        self.edit.setObjectName("composer")
        self.edit.setPlaceholderText(
            "想问点什么…  说「我」默认按档案排盘　Enter 发送 / Shift+Enter 换行"
        )
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.edit.setFrameShape(QFrame.NoFrame)
        self.edit.setFixedHeight(self._MIN_EDIT)
        self.edit.textChanged.connect(self._auto_grow)
        self.edit.installEventFilter(self)
        box.addWidget(self.edit)

        # 底部操作条：右侧放环与发送键，左侧留给以后的附件入口
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        self.actions.addStretch(1)
        box.addLayout(self.actions)

        # 点击卡片留白处也应回到输入区，否则按钮周围一圈点了没反应
        self.setFocusProxy(self.edit)

    # -- 对外接口保持和原来的 QTextEdit 一致，窗口里的调用不用改 --
    def toPlainText(self) -> str:  # noqa: N802
        return self.edit.toPlainText()

    def clear(self) -> None:
        self.edit.clear()

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget, 0, Qt.AlignVCenter)

    def set_placeholder(self, text: str) -> None:
        self.edit.setPlaceholderText(text)

    def focus_input(self) -> None:
        """把光标交给真正的输入区（卡片的焦点代理，显式调用更直观）。"""
        self.edit.setFocus()

    # -- 内部 --
    def _auto_grow(self) -> None:
        doc_h = int(self.edit.document().size().height()) + 4
        height = max(self._MIN_EDIT, min(self._MAX_EDIT, doc_h))
        if height != self.edit.height():
            self.edit.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 窗口改宽后换行位置变了，固定高度得跟着重算，否则会出现空行或截字
        self._auto_grow()

    def _set_active(self, active: bool) -> None:
        if bool(self.property("active")) == active:
            return
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.edit:
            etype = event.type()
            if etype == QEvent.FocusIn:
                self._set_active(True)
            elif etype == QEvent.FocusOut:
                self._set_active(False)
            elif etype == QEvent.KeyPress:
                if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
                    event.modifiers() & Qt.ShiftModifier
                ):
                    self.submitted.emit()
                    return True
        return super().eventFilter(obj, event)


# ------------------------------------------------------------
# 消息区
# ------------------------------------------------------------
class MessageArea(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("messagesHost")
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(56, 30, 56, 26)
        self.vbox.setSpacing(18)
        self.vbox.addStretch(1)
        self._stream_widget: Optional[ChatText] = None

    # -- 基础操作 --
    def _insert(self, widget: QWidget, alignment=None) -> None:
        if alignment is None:
            self.vbox.insertWidget(self.vbox.count() - 1, widget)
        else:
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            if alignment == "right":
                row.addStretch(1)
                row.addWidget(widget)
            else:
                row.addWidget(widget)
                row.addStretch(1)
            self.vbox.insertWidget(self.vbox.count() - 1, holder)

    def clear(self) -> None:
        while self.vbox.count() > 1:
            item = self.vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                # 仅 takeAt 只是从布局摘除，控件仍会显示在容器上，必须解除父子关系
                w.setParent(None)
                w.deleteLater()
        self._stream_widget = None

    def show_empty_state(self, configured: bool = False) -> None:
        self.clear()
        hint = ChatText()
        hint.set_html_doc(md.empty_state(configured))
        hint.setMaximumWidth(560)
        self._insert(hint)

    # -- 消息 --
    def add_user(self, text: str) -> None:
        self._insert(UserBubble(text), "right")

    def add_assistant(self, text: str) -> None:
        """回放历史消息用：一次性渲染完整回答。"""
        widget = ChatText()
        widget.set_markdown(text)
        self._insert(widget)

    def add_tool(self, label: str) -> None:
        chip = ToolChip(f"调用 {label}")
        self._insert(chip)

    def add_notice(self, text: str) -> None:
        """系统动作提示（如上下文压缩），与工具调用区分开。"""
        self._insert(ToolChip(text))

    def add_error(self, text: str) -> None:
        lab = QLabel(f"⚠ {text}")
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#B03A2E; font-size:12px; background:transparent;")
        self._insert(lab)

    def start_assistant(self) -> ChatText:
        widget = ChatText()
        widget.set_html_doc(
            f"<html><body style='color:{MUTED}; font-size:13px;'>思考中…</body></html>"
        )
        self._insert(widget)
        self._stream_widget = widget
        return widget

    def drop_empty_stream(self) -> None:
        if self._stream_widget is not None:
            self._stream_widget.deleteLater()
            self._stream_widget = None


# ------------------------------------------------------------
# 主窗口
# ------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, base_url: str, health: Dict[str, Any]) -> None:
        super().__init__()
        self.api = ApiClient(base_url)
        self.base_url = base_url
        self.health = health or {}
        self.current_id: Optional[str] = None
        self.worker: Optional[ChatWorker] = None
        self.settings_popup: Optional[SettingsPopup] = None
        self._buf = ""
        self._dirty = False
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(90)
        self._render_timer.timeout.connect(self._flush_render)

        # 窗口标题自己带「程序名 · 中文名」，不再依赖 Qt 追加的 applicationDisplayName，
        # 否则标题栏会出现「FreeFateStudio - FreeFateStudio 命理工作台」这种重复。
        self.setWindowTitle(f"{APP_TITLE} · {APP_SUBTITLE}")
        self.resize(1120, 780)
        self.setMinimumSize(900, 620)

        self._build_ui()
        self._bind_shortcuts()
        self.refresh_conversations()
        self._update_gear()
        self._show_empty()

    # ---------------- 构建界面 ----------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        row.addWidget(self._build_sidebar())
        row.addWidget(self._build_main(), 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(248)
        box = QVBoxLayout(side)
        box.setContentsMargins(14, 18, 14, 14)
        box.setSpacing(10)

        brand = QLabel("FreeFateStudio")
        brand.setObjectName("brand")
        sub = QLabel("命理工作台 · FATE STUDIO")
        sub.setObjectName("brandSub")
        box.addWidget(brand)
        box.addWidget(sub)

        self.new_btn = QPushButton("+  新对话")
        self.new_btn.setObjectName("primary")
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(lambda: self.new_conversation())
        box.addWidget(self.new_btn)

        section = QLabel("历史会话")
        section.setObjectName("sectionTitle")
        box.addSpacing(6)
        box.addWidget(section)

        self.conv_list = ConvList()
        self.conv_list.itemClicked.connect(self._on_conv_clicked)
        self.conv_list.deleteRequested.connect(self._delete_conversation)
        box.addWidget(self.conv_list, 1)

        self.gear_btn = QPushButton()
        self.gear_btn.setObjectName("gearBtn")
        self.gear_btn.setIcon(gear_icon(18))
        self.gear_btn.setIconSize(QSize(18, 18))
        self.gear_btn.setFixedSize(28, 28)
        self.gear_btn.setCursor(Qt.PointingHandCursor)
        self.gear_btn.clicked.connect(self.open_settings)

        self.key_warn = QLabel("未配置 API Key")
        self.key_warn.setObjectName("warnTiny")
        self.key_warn.setVisible(False)

        footer = QWidget()
        fbox = QHBoxLayout(footer)
        fbox.setContentsMargins(0, 6, 0, 0)
        fbox.setSpacing(6)
        fbox.addWidget(self.gear_btn)
        fbox.addWidget(self.key_warn)
        fbox.addStretch(1)
        box.addWidget(footer)
        return side

    def _build_main(self) -> QWidget:
        main = QWidget()
        box = QVBoxLayout(main)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(52)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(28, 0, 18, 0)
        self.title_label = QLabel("新对话")
        self.title_label.setObjectName("chatTitle")
        hbox.addWidget(self.title_label)
        hbox.addStretch(1)
        box.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area = MessageArea()
        self.scroll.setWidget(self.area)
        box.addWidget(self.scroll, 1)

        wrap = QFrame()
        wrap.setObjectName("composerWrap")
        wbox = QVBoxLayout(wrap)
        wbox.setContentsMargins(56, 8, 56, 14)
        wbox.setSpacing(8)

        self.composer = Composer()
        self.composer.submitted.connect(self.send_message)
        self.composer.edit.textChanged.connect(self._refresh_send)

        # 上下文进度环与发送键都在框内右下角，和主流 Agent 输入框一致
        self.ctx_ring = ContextRing()
        self.composer.add_action(self.ctx_ring)

        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("send")
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolTip("发送（Enter）")
        self.send_btn.clicked.connect(self.send_message)
        self.composer.add_action(self.send_btn)
        wbox.addWidget(self.composer)

        hint = QLabel("内容由 AI 生成，命理属传统文化参考，不替代医疗、法律、投资决策")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        wbox.addWidget(hint)
        box.addWidget(wrap)
        self._refresh_send()
        return main

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.new_conversation())
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.composer.focus_input())

    # ---------------- 会话列表 ----------------
    def refresh_conversations(self, select_id: Optional[str] = None) -> None:
        convs = self.api.list_conversations()
        self.conv_list.blockSignals(True)
        self.conv_list.clear()
        for conv in convs:
            item = QListWidgetItem(self._conv_title(conv))
            item.setData(Qt.UserRole, conv["id"])
            item.setToolTip(conv.get("updated_at", ""))
            self.conv_list.addItem(item)
            if conv["id"] == (select_id or self.current_id):
                self.conv_list.setCurrentItem(item)
        self.conv_list.blockSignals(False)

    @staticmethod
    def _conv_title(conv: Dict[str, Any]) -> str:
        title = conv.get("title") or "新对话"
        return title if len(title) <= 16 else title[:16] + "…"

    def _show_empty(self) -> None:
        """空会话提示按「档案是否填好」给不同引导。"""
        self.area.show_empty_state(bool(self.health.get("profile_ready")))

    def _on_conv_clicked(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.UserRole)
        if cid and cid != self.current_id:
            self.load_conversation(cid)

    def new_conversation(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        conv = self.api.create_conversation()
        if not conv:
            QMessageBox.warning(self, "无法创建会话", "本地服务未响应，请重启程序。")
            return
        self.current_id = conv["id"]
        self.refresh_conversations(select_id=self.current_id)
        self.title_label.setText("新对话")
        self.ctx_ring.reset()
        self._show_empty()
        self.composer.focus_input()

    def _delete_conversation(self, cid: str) -> None:
        """删除指定会话（入口在列表行尾的「⋯」里，不再放在右上角）。"""
        if not cid:
            return
        if not self.api.delete_conversation(cid):
            QMessageBox.warning(self, "删除失败", "本地服务未响应，会话未删除。")
            return
        if cid == self.current_id:
            self.current_id = None
            self.title_label.setText("新对话")
            self.ctx_ring.reset()
            self._show_empty()
        self.refresh_conversations()

    def load_conversation(self, cid: str) -> None:
        self.current_id = cid
        conv_title = "新对话"
        for conv in self.api.list_conversations():
            if conv["id"] == cid:
                conv_title = conv.get("title") or "新对话"
                break
        self.title_label.setText(
            conv_title if len(conv_title) <= 26 else conv_title[:26] + "…"
        )

        messages = self.api.messages(cid)
        self.area.clear()
        if not messages:
            self._show_empty()
            self._sync_context()
            return
        for msg in messages:
            if msg["role"] == "user":
                self.area.add_user(msg["content"])
            else:
                self.area.add_assistant(msg["content"])
        self._scroll_bottom()
        self._sync_context()

    def _sync_context(self) -> None:
        """切会话时先给进度环一个初值，避免显示上一个会话的占用。"""
        if not self.current_id:
            self.ctx_ring.reset()
            return
        snapshot = self.api.context(self.current_id)
        if snapshot:
            self.ctx_ring.set_state(snapshot)
        else:
            self.ctx_ring.reset()

    # ---------------- 发送 ----------------
    def send_message(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        text = self.composer.toPlainText().strip()
        if not text:
            return

        if not self.current_id:
            conv = self.api.create_conversation()
            if not conv:
                QMessageBox.warning(self, "无法创建会话", "本地服务未响应，请重启程序。")
                return
            self.current_id = conv["id"]
            self.refresh_conversations(select_id=self.current_id)
            self.area.clear()

        self.area.add_user(text)
        self.composer.clear()

        self._buf = ""
        self.area.start_assistant()
        self.ctx_ring.set_busy(False)
        self._scroll_bottom()

        self.worker = ChatWorker(self.base_url, self.current_id, text)
        self.worker.token.connect(self._on_token)
        self.worker.tool.connect(self._on_tool)
        self.worker.reset.connect(self._on_reset)
        self.worker.meta.connect(self._on_meta)
        self.worker.context.connect(self._on_context)
        self.worker.error.connect(self._on_error)
        self.worker.done.connect(self._on_done)
        self.worker.start()
        self._refresh_send()

    def _refresh_send(self) -> None:
        """空内容或正在生成时发送键置灰，避免点了个没反应。"""
        busy = self.worker is not None and self.worker.isRunning()
        ready = bool(self.composer.toPlainText().strip())
        self.send_btn.setEnabled(ready and not busy)

    def _on_token(self, text: str) -> None:
        self._buf += text
        self._dirty = True
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_render(self) -> None:
        self._render_timer.stop()
        if not self._dirty:
            return
        self._dirty = False
        widget = self.area._stream_widget
        if widget is None:
            return
        stick = self._at_bottom()
        widget.set_markdown(self._buf or "…")
        if stick:
            self._scroll_bottom()

    def _on_tool(self, label: str) -> None:
        self.area.add_tool(label)
        self._scroll_bottom()

    def _on_context(self, event: Dict[str, Any]) -> None:
        """上下文事件：更新右下角进度环，压缩完成时在对话里留一行痕迹。"""
        self.ctx_ring.apply_event(event)
        if event.get("type") != "compacted":
            return
        if event.get("error"):
            self.area.add_notice(f"上下文压缩失败，本轮按原文继续：{event['error']}")
        elif not event.get("skipped"):
            before = float(event.get("before") or 0)
            after = float(event.get("after") or 0)
            self.area.add_notice(
                f"已压缩上下文 {before / 1000:.1f}K → {after / 1000:.1f}K tokens"
                f"（{event.get('summarized', 0)} 条旧消息转摘要，"
                f"保留最近 {event.get('kept', 0)} 条原文）"
            )
        self._scroll_bottom()

    def _on_reset(self) -> None:
        """模型决定调用工具：丢弃此前的过渡语，等工具结果后的正式回答。"""
        self._buf = ""
        widget = self.area._stream_widget
        if widget is not None:
            widget.set_html_doc(
                f"<html><body style='color:{MUTED}; font-size:13px;'>资料整理中…</body></html>"
            )

    def _on_meta(self, meta: Dict[str, Any]) -> None:
        title = meta.get("title")
        if title:
            self.title_label.setText(title if len(title) <= 26 else title[:26] + "…")
            self.refresh_conversations(select_id=self.current_id)

    def _on_error(self, message: str) -> None:
        self.area.drop_empty_stream()
        self.area.add_error(message)
        self._scroll_bottom()

    def _on_done(self) -> None:
        if self._dirty:
            self._flush_render()
        widget = self.area._stream_widget
        if widget is not None and not self._buf.strip():
            widget.deleteLater()
            self.area._stream_widget = None
        self.area._stream_widget = None
        # 流被中断时 compacted 可能没到，这里兜一下，别让环一直转圈
        self.ctx_ring.set_busy(False)
        self.worker = None
        self._refresh_send()
        self.refresh_conversations(select_id=self.current_id)
        self._scroll_bottom()

    # ---------------- 辅助 ----------------
    def _at_bottom(self) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 48

    def _scroll_bottom(self) -> None:
        def _do() -> None:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(0, _do)
        QTimer.singleShot(60, _do)

    def _update_gear(self) -> None:
        model = self.health.get("model") or "deepseek"
        ready = bool(self.health.get("api_key_ready"))
        profile = "已填写" if self.health.get("profile_ready") else "未填写"
        port = self.base_url.rsplit(":", 1)[-1]
        tip = f"设置\n模型 {model}\n本人档案 {profile}\n本地服务 127.0.0.1:{port}"
        if not ready:
            tip += "\n⚠ 未配置 API Key"
        self.gear_btn.setToolTip(tip)
        self.key_warn.setVisible(not ready)

    # ---------------- 设置 ----------------
    def open_settings(self) -> None:
        if self.settings_popup is None:
            self.settings_popup = SettingsPopup(self.api, self.gear_btn)
            self.settings_popup.settingsSaved.connect(self._on_settings_saved)
            self.settings_popup.profileSaved.connect(self._on_profile_saved)
        self.settings_popup.toggle()

    def _on_settings_saved(self, snapshot: Dict[str, Any]) -> None:
        latest = self.api.health()
        if latest:
            self.health = latest
        else:
            self.health["model"] = snapshot.get("model", self.health.get("model"))
            self.health["api_key_ready"] = bool(snapshot.get("api_key_set"))
        self._update_gear()

    def _on_profile_saved(self, info: Dict[str, Any]) -> None:
        """档案变更后刷新健康快照，齿轮提示同步显示「已填写」。"""
        latest = self.api.health()
        if latest:
            self.health = latest
        else:
            self.health["profile_ready"] = bool(info.get("configured"))
        self._update_gear()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1500)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._drop_settings()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        self._drop_settings()
        super().moveEvent(event)

    def _drop_settings(self) -> None:
        """浮层是独立顶层窗口、钉子在一个固定坐标上，主窗一动它就错位，直接收起。"""
        pop = getattr(self, "settings_popup", None)
        if pop is not None and pop.isVisible():
            pop.hide()

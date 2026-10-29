# -*- coding: utf-8 -*-
"""Codex 风格极简主题：黑白灰、细边框、无渐变、字距克制。"""

from __future__ import annotations

BG = "#FAFAF9"
SIDEBAR_BG = "#F7F7F5"
PANEL = "#FFFFFF"
BORDER = "#E8E8E4"
BORDER_SOFT = "#EFEFEA"
TEXT = "#17171A"
TEXT_SUB = "#4A4A45"
MUTED = "#8C8C86"
ACCENT = "#111111"
HOVER = "#EFEFEC"
SELECTED = "#E7E7E3"
USER_BUBBLE = "#F0F0EC"

FONT_UI = '"Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif'
FONT_MONO = '"Cascadia Mono", "Consolas", "SFMono-Regular", monospace'

QSS = f"""
* {{
    font-family: {FONT_UI};
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, #root {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR_BG}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ font-size: 14px; font-weight: 600; letter-spacing: 1px; }}
QLabel#brandSub {{ color: {MUTED}; font-size: 11px; letter-spacing: .5px; }}
QLabel#sectionTitle {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
QLabel#chatTitle {{ font-size: 14px; font-weight: 600; }}
QLabel#statusBar {{ color: {MUTED}; font-size: 11px; }}
QLabel#hint {{ color: {MUTED}; font-size: 11px; }}

QPushButton#primary {{
    background: {ACCENT}; color: #FFFFFF; border: none; border-radius: 8px;
    padding: 8px 12px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: #2C2C29; }}
QPushButton#primary:pressed {{ background: #000000; }}
QPushButton#primary:disabled {{ background: #D6D6D1; color: {BG}; }}

QPushButton#ghost {{
    background: transparent; border: none; color: {MUTED};
    padding: 5px 9px; border-radius: 6px;
}}
QPushButton#ghost:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#danger:hover {{ background: #FBEDEA; color: #B03A2E; }}

QPushButton#send {{
    background: {ACCENT}; color: #FFFFFF; border: none; border-radius: 14px;
    font-size: 15px; font-weight: 700;
}}
QPushButton#send:hover {{ background: #2C2C29; }}
QPushButton#send:disabled {{ background: #D6D6D1; color: {BG}; }}

QListWidget#convList {{
    background: transparent; border: none; outline: none;
}}
QListWidget#convList::item {{
    /* 右侧留出 32px 给悬浮时的「⋯」，文字提前收住不会压到点上 */
    padding: 9px 32px 9px 10px; border-radius: 8px; color: {TEXT_SUB}; margin: 1px 0;
}}
QListWidget#convList::item:hover {{ background: {HOVER}; }}
QListWidget#convList::item:selected {{ background: {SELECTED}; color: {TEXT}; }}

QFrame#header {{ background: {BG}; border-bottom: 1px solid {BORDER_SOFT}; }}
QFrame#composerWrap {{ background: {BG}; }}
QTextEdit#composer {{
    background: {PANEL}; border: 1px solid #E3E3DE; border-radius: 12px;
    padding: 10px 12px; color: {TEXT}; selection-background-color: #DCDCD5;
}}
QTextEdit#composer:focus {{ border: 1px solid #C6C6BF; }}

QScrollArea {{ border: none; background: transparent; }}
QWidget#messagesHost {{ background: {BG}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D8D8D2; border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #C2C2BA; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QScrollBar:horizontal {{ height: 0; }}

QToolTip {{
    background: #1F1F1D; color: #F5F5F2; border: none;
    padding: 6px 8px; border-radius: 6px;
}}

/* ---- 左下角设置 ---- */
QPushButton#gearBtn {{
    background: transparent; border: none; color: {MUTED};
    font-size: 15px; border-radius: 8px; padding: 0px;
}}
QPushButton#gearBtn:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#gearBtn:pressed {{ background: {SELECTED}; }}
QLabel#warnTiny {{ color: #B03A2E; font-size: 11px; }}

QFrame#settingsCard {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QLabel#settingsTitle {{
    color: {MUTED}; font-size: 11px; letter-spacing: 1px;
    padding: 2px 10px 4px 10px;
}}
QFrame#settingsItem {{
    background: transparent; border: none; border-radius: 8px;
}}
QFrame#settingsItem:hover {{ background: {HOVER}; }}
QLabel#fieldLabel {{ color: {TEXT_SUB}; font-size: 11px; padding-left: 2px; }}
QLabel#menuRowText {{ background: transparent; }}
QLabel#menuRowValue {{ color: {MUTED}; font-size: 11px; background: transparent; }}
QLabel#menuRowChevron {{ color: #B3B3AC; font-size: 12px; background: transparent; }}
QLineEdit#settingsField {{
    background: {BG}; border: 1px solid #E3E3DE; border-radius: 8px;
    padding: 7px 9px; color: {TEXT}; selection-background-color: #DCDCD5;
}}
QLineEdit#settingsField:focus {{ border: 1px solid #C6C6BF; background: {PANEL}; }}
QLabel#settingsHint {{ color: {MUTED}; font-size: 11px; }}
QLabel#settingsHint[state="ok"] {{ color: #2E7D4F; font-size: 11px; }}
QLabel#settingsHint[state="err"] {{ color: #B03A2E; font-size: 11px; }}

/* ---- 性别二选一 ---- */
QPushButton#segBtn {{
    background: {BG}; border: 1px solid #E3E3DE; border-radius: 8px;
    color: {TEXT_SUB}; font-size: 12px; padding: 0px;
}}
QPushButton#segBtn:hover {{ background: {HOVER}; }}
QPushButton#segBtn:checked {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #FFFFFF; font-weight: 600;
}}

/* ---- 会话行尾的删除入口 ---- */
QFrame#menuCard {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QPushButton#menuDanger {{
    background: transparent; border: none; border-radius: 6px;
    color: #B03A2E; font-size: 13px; text-align: left; padding: 0 10px;
}}
QPushButton#menuDanger:hover {{ background: #FBEDEA; }}
"""

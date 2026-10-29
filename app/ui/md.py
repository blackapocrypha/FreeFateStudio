# -*- coding: utf-8 -*-
"""Markdown → QTextBrowser 可渲染的 HTML。

Qt 的富文本只支持 CSS 2.1 子集，且表格边框对 border-collapse 支持不完整，
所以这里对 <td>/<th> 逐个补内联样式，保证表格一定有框线。
"""

from __future__ import annotations

import re

import markdown

from .theme import BORDER, FONT_MONO, FONT_UI, MUTED, TEXT

_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]

_CSS = f"""
body {{ font-family: {FONT_UI}; font-size: 14px; color: {TEXT}; }}
p {{ margin: 0 0 9px 0; }}
h1 {{ font-size: 18px; font-weight: 600; margin: 16px 0 8px 0; }}
h2 {{ font-size: 16px; font-weight: 600; margin: 16px 0 8px 0; }}
h3 {{ font-size: 14px; font-weight: 600; margin: 12px 0 6px 0; }}
h4 {{ font-size: 13px; font-weight: 600; margin: 10px 0 6px 0; }}
ul, ol {{ margin: 0 0 9px 0; padding-left: 20px; }}
li {{ margin: 3px 0; }}
strong {{ font-weight: 600; }}
em {{ font-style: italic; }}
code {{
    font-family: {FONT_MONO}; font-size: 12px;
    background-color: #F4F4F0; color: #2A2A26;
}}
pre {{
    font-family: {FONT_MONO}; font-size: 12px;
    background-color: #F7F7F3; border: 1px solid {BORDER};
    padding: 10px; margin: 8px 0;
}}
pre code {{ background-color: transparent; }}
blockquote {{
    border-left: 2px solid #DCDCD5; margin: 8px 0; padding: 2px 0 2px 10px;
    color: #5A5A55;
}}
hr {{ border: none; border-top: 1px solid {BORDER}; margin: 14px 0; }}
a {{ color: {TEXT}; text-decoration: underline; }}
table {{ margin: 8px 0; }}
"""

_CELL_BASE = "border:1px solid %s; padding:6px 10px; vertical-align:top;" % BORDER
_TH_EXTRA = "background-color:#F7F7F3; font-weight:600;"
_TABLE_EXTRA = "width:100%; border-collapse:collapse;"


def _merge_style(attrs: str, extra: str) -> str:
    m = re.search(r'style="([^"]*)"', attrs)
    if m:
        return attrs.replace(m.group(0), 'style="%s %s"' % (m.group(1), extra))
    return '%s style="%s"' % (attrs, extra)


def _style_tables(html: str) -> str:
    html = re.sub(
        r"<table([^>]*)>",
        lambda m: "<table%s>" % _merge_style(m.group(1), _TABLE_EXTRA),
        html,
    )
    html = re.sub(
        r"<th([^>]*)>",
        lambda m: "<th%s>" % _merge_style(m.group(1), _CELL_BASE + _TH_EXTRA),
        html,
    )
    html = re.sub(
        r"<td([^>]*)>",
        lambda m: "<td%s>" % _merge_style(m.group(1), _CELL_BASE),
        html,
    )
    return html


def to_html(text: str) -> str:
    """把模型输出的 Markdown 转成可直接 setHtml 的完整文档。"""
    raw = text or ""
    try:
        body = markdown.markdown(raw, extensions=_EXTENSIONS)
    except Exception:
        body = "<p>%s</p>" % raw.replace("&", "&amp;").replace("<", "&lt;")
    body = _style_tables(body)
    return (
        "<html><head><meta charset='utf-8'><style>%s</style></head>"
        "<body>%s</body></html>" % (_CSS, body)
    )


def to_plain(text: str) -> str:
    """去掉 Markdown 标记的纯文本，用于会话标题等场景。"""
    t = re.sub(r"[`*_>#]+", "", text or "")
    t = re.sub(r"\|.*\|", "", t)
    return " ".join(t.split())


def empty_state(configured: bool = False) -> str:
    """空会话提示。档案已填好时不必再教用户怎么自报出生信息。"""
    if configured:
        body = (
            '<p style="font-size:13px;">个人信息已就绪，直接问就行，例如：</p>'
            '<p style="font-size:13px; color:#4A4A45;">「我今年的运势怎么样」「我的八字适合做什么」</p>'
            '<p style="font-size:13px;">也可以只问一件事：「这次面试能过吗」「下周哪几天适合签合同」。</p>'
        )
    else:
        body = (
            '<p style="font-size:13px;">两种开始方式：</p>'
            '<p style="font-size:13px;">① 左下角齿轮 → 个人信息，填一次出生时间与性别，'
            '以后说「我」就按这份档案算；</p>'
            '<p style="font-size:13px;">② 直接描述出生信息，例如：</p>'
            '<p style="font-size:13px; color:#4A4A45;">「男，1990年5月12日下午两点半，生在山东临沂」</p>'
            '<p style="font-size:13px;">也可以只问一件事：「这次面试能过吗」「下周哪几天适合签合同」。</p>'
        )
    return (
        f'<html><body style="font-family:{FONT_UI}; color:{MUTED};">{body}</body></html>'
    )


EMPTY_STATE = empty_state(False)

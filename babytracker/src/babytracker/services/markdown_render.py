"""Markdown-Rendering für Journal-Bodies."""

from __future__ import annotations

import markdown as _md

_renderer = _md.Markdown(
    extensions=["nl2br", "sane_lists", "fenced_code", "tables"],
    output_format="html5",
)


def render(text: str) -> str:
    if not text:
        return ""
    _renderer.reset()
    return _renderer.convert(text)

"""Plain-text clean-up for text the model writes for users (Step 26)."""

import re

_MARKDOWN = re.compile(r"(\*\*|__|`)")
_CURRENCY = re.compile(r"[€$£¥]\s?(?=[\d(-])")


def plain_text(text: str) -> str:
    """No Markdown markers and no currency signs, which the Northwind data does not have
    (Step 26 walk-through: "**€27,537.13**"; clarifying questions with "**revenue**")."""
    return _CURRENCY.sub("", _MARKDOWN.sub("", text)).strip()

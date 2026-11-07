"""Mask sensitive values before they reach logs, traces, the LLM or the audit tables (§27).

Masked: e-mail addresses, phone numbers, card and bank-account style digit runs, IBANs,
API keys and bearer tokens, passwords in ``key=value`` text, and passwords inside
connection strings. Business values (amounts, dates, IDs such as order numbers) are kept.
"""

import re
from typing import Any

_RULES: list[tuple[re.Pattern[str], str]] = [
    # user:password@host in connection strings
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s@]+:)([^@\s]+)(@)"), r"\1[MASKED]\3"),
    # password=..., secret: ..., api_key="..."
    (
        re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"),
        r"\1\2[MASKED]",
    ),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{10,}"), "Bearer [MASKED]"),
    (re.compile(r"\b(sk|pk|ls|lsv2)[-_][A-Za-z0-9_-]{12,}\b"), "[MASKED_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"), "[MASKED_TOKEN]"),  # noqa: E501
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[MASKED_EMAIL]"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{1,4}){3,8}\b"), "[MASKED_IBAN]"),
    # 13-19 digits, optionally grouped (cards, bank accounts)
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[MASKED_NUMBER]"),
]  # fmt: skip


# Phone-like runs: digits with spaces, dashes, dots or brackets, 7 to 15 digits in total.
_PHONE_CANDIDATE = re.compile(r"(?<![\w.,])\+?\(?\d[\d\s().-]{5,}\d(?![\w,])")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _mask_phone(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = sum(ch.isdigit() for ch in text)
    has_separator = any(ch in " ().-" for ch in text.strip()) or text.startswith("+")
    if " - " in text:  # a range such as "10248 - 10250", not a phone number
        return text
    if not 7 <= digits <= 15 or not has_separator or _DATE.match(text.strip()):
        return text
    trailing = text[len(text.rstrip()) :]
    return "[MASKED_PHONE]" + trailing


def mask_text(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return _PHONE_CANDIDATE.sub(_mask_phone, text)


def mask_value(value: Any) -> Any:  # noqa: ANN401 (masks JSON-like data of any shape)
    """Mask every string inside dicts, lists and tuples (keys are kept)."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_value(v) for v in value]
    return value

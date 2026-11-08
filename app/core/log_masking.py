"""Mask sensitive values in every log record (brief §27, Step 24).

``install_log_masking`` wraps the logging record factory, so every record created by any
logger (ours, uvicorn's, SQLAlchemy's) has its message and traceback passed through
``mask_text`` before any handler formats it. E-mail addresses, phone numbers, card and
bank numbers, keys, tokens and passwords in connection strings never reach the logs.
"""

import logging
import traceback
from typing import Any

from app.core.masking import mask_text

_installed = False


def _mask_args_in_place(record: logging.LogRecord) -> bool:
    """Mask each string argument, keeping their number (formatters such as uvicorn's
    access log unpack them). True when the formatted message is then clean."""
    if not isinstance(record.args, tuple) or not isinstance(record.msg, str):
        return False
    record.msg = mask_text(record.msg)
    record.args = tuple(mask_text(a) if isinstance(a, str) else a for a in record.args)
    try:
        message = record.getMessage()
    except Exception:
        return False
    return mask_text(message) == message


def mask_record(record: logging.LogRecord) -> logging.LogRecord:
    try:
        message = record.getMessage()
    except Exception:  # a broken format string: keep the raw message
        message = str(record.msg)
        record.msg, record.args = mask_text(message), ()
    else:
        masked = mask_text(message)
        # Leave clean records untouched (found in the Step 26 walk-through: emptying the
        # arguments broke uvicorn's access log on every request).
        if masked != message and not _mask_args_in_place(record):
            record.msg, record.args = masked, ()
    if record.exc_info and record.exc_info[1] is not None:
        record.exc_text = mask_text("".join(traceback.format_exception(*record.exc_info)).rstrip())
        record.exc_info = None
    return record


def install_log_masking() -> None:
    """Install the masking record factory once per process (idempotent)."""
    global _installed
    if _installed:
        return
    original = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:  # noqa: ANN401
        return mask_record(original(*args, **kwargs))

    logging.setLogRecordFactory(factory)
    _installed = True

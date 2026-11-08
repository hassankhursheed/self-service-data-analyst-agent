"""LangSmith tracing with redaction (brief §27, Step 24).

Tracing is switched on by the LANGSMITH_* environment variables. When it is on, every
graph run happens inside a ``tracing_context`` whose client hides result rows and masks
strings in all traced inputs and outputs (``redact_for_trace``), so personal values a
user may see in a table never reach LangSmith.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any

from app.core.config import Settings
from app.core.masking import redact_for_trace

PLACEHOLDERS = {"", "CHANGE_ME"}


def tracing_enabled(settings: Settings) -> bool:
    key = settings.langsmith_api_key.get_secret_value() if settings.langsmith_api_key else ""
    return settings.langsmith_tracing and key not in PLACEHOLDERS


def redacting_client(settings: Settings) -> Any | None:  # noqa: ANN401 (langsmith.Client)
    """A LangSmith client that redacts everything it uploads, or None when tracing is off."""
    if not tracing_enabled(settings) or settings.langsmith_api_key is None:
        return None
    from langsmith import Client

    return Client(
        api_key=settings.langsmith_api_key.get_secret_value(),
        api_url=settings.langsmith_endpoint,
        hide_inputs=redact_for_trace,
        hide_outputs=redact_for_trace,
    )


@contextmanager
def redacted_tracing(client: Any | None) -> Iterator[None]:  # noqa: ANN401
    """Trace through ``client`` (redacting) when one is given; otherwise change nothing."""
    if client is None:
        with nullcontext():
            yield
        return
    from langsmith.run_helpers import tracing_context

    with tracing_context(client=client):
        yield

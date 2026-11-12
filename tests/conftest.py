"""Settings shared by all tests."""

import asyncio
import os
import sys
from collections.abc import Callable, Mapping

import pytest

# Tests never send anything to LangSmith, whatever the local .env says. Environment
# variables win over .env (app/core/config.py), so this turns off agent tracing and the
# evaluation upload for every test. Without it, each local pytest run uploaded an
# "eval-api-run-..." project and traced test questions into the real project.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["LANGCHAIN_TRACING_V2"] = "false"


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """psycopg's async mode cannot use Windows' default Proactor loop; use the selector loop."""
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}

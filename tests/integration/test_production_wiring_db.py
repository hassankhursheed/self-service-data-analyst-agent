"""Step 23: the production wiring (default_deps) against the real database, no LLM call.

The unit tests use fakes for every dependency; this checks the real loaders and the
read-only executor that the API uses: the semantic layer and the verified library come
from the database (app role), and SQL runs as analytics_ro with the user's row rules.
"""

import pytest

from app.agent.audit import DatabaseAuditSink
from app.agent.deps import default_deps
from app.core.config import Settings
from app.core.context import UserContext
from app.core.enums import RegionCode, RoleName
from scripts.seed import SeedSummary

pytestmark = pytest.mark.integration


async def test_default_deps_load_real_data_and_run_read_only(
    settings: Settings, seeded: SeedSummary
) -> None:
    deps = default_deps()
    assert isinstance(deps.audit, DatabaseAuditSink)

    layer = await deps.load_semantic()
    assert {"orders", "customers", "products"} <= set(layer.tables)
    assert "revenue" in layer.metrics

    library = await deps.load_verified()
    assert len(library) >= 15
    assert all(example.is_active for example in library)

    europe = UserContext(
        username="sales.europe", role=RoleName.SALES_MANAGER, region=RegionCode.EUROPE
    )
    result = await deps.executor(
        "SELECT count(DISTINCT c.country) AS countries FROM customers c",
        europe,
        deps.statement_timeout_ms,
        deps.row_limit,
    )
    assert result.rows == [(15,)]  # only Europe's 15 countries through the secure views
    finance = UserContext(username="finance", role=RoleName.FINANCE_ANALYST)
    everyone = await deps.executor(
        "SELECT count(DISTINCT c.country) AS countries FROM customers c",
        finance,
        deps.statement_timeout_ms,
        deps.row_limit,
    )
    assert everyone.rows == [(21,)]

"""Step 26 extra: load-test statistics and report."""

import datetime as dt

from eval.load_test import Sample, load_settings, markdown, percentile, summarise


def sample(seconds: float, status: str = "ANSWERED", http: int = 200) -> Sample:
    return Sample(user=0, account="finance", http_status=http, status=status, seconds=seconds)


def test_summary_counts_outcomes_and_latency() -> None:
    samples = [sample(1.0), sample(2.0), sample(3.0), sample(10.0, "FAILED", 500)]
    report = summarise(samples, users=2, per_user=2, latency=1.0, wall=6.0)
    assert report.total == 4
    assert report.statuses == {"ANSWERED": 3, "FAILED": 1}
    assert report.errors == 1
    assert report.p50_s == 2.5
    assert report.max_s == 10.0
    assert report.throughput_per_minute == 40.0
    assert percentile([], 0.95) == 0.0
    text = markdown(report, dt.datetime(2026, 11, 8, tzinfo=dt.UTC))
    assert "| Concurrent users | 2 |" in text


def test_load_settings_raise_limits_only_for_the_run() -> None:
    from pydantic import SecretStr

    from app.core.config import Settings

    url = SecretStr("postgresql+asyncpg://u:p@localhost:5433/northwind")
    base = Settings(
        postgres_user="u",
        postgres_password=SecretStr("p"),
        app_database_url=url,
        analytics_database_url=url,
        jwt_secret_key=SecretStr("k" * 40),
    )
    raised = load_settings(base)
    assert raised.api.rate_limits.questions_per_minute > base.api.rate_limits.questions_per_minute
    assert raised.alerts.enabled is False
    assert base.api.rate_limits.questions_per_minute == 20  # the real settings are unchanged

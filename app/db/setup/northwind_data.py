"""Northwind preparation: the one-time date shift and the sales-region mapping.

These are the only writes to Northwind data, done by the seed script as the owner.
The application itself never writes to Northwind tables.
"""

from pathlib import Path

import psycopg
from psycopg import sql
from pydantic import BaseModel, ConfigDict, model_validator

from app.core.config import PROJECT_ROOT
from app.core.enums import RegionCode
from app.core.yaml_config import load_yaml_model

REGIONS_FILE = PROJECT_ROOT / "config" / "regions.yaml"
SHIFT_KEY = "date_shift_years"

# Every date column in Northwind (docs/data-setup.md).
DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders": ("order_date", "required_date", "shipped_date"),
    "employees": ("birth_date", "hire_date"),
}


class SeedError(Exception):
    """The seed cannot continue safely."""


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: RegionCode
    name: str
    countries: list[str]


class RegionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    regions: list[Region]

    @model_validator(mode="after")
    def _each_country_once(self) -> "RegionsConfig":
        seen: set[str] = set()
        for region in self.regions:
            for country in region.countries:
                if country in seen:
                    raise ValueError(f"country {country!r} is mapped to more than one region")
                seen.add(country)
        if {r.code for r in self.regions} != set(RegionCode):
            raise ValueError("every region code must be configured exactly once")
        return self


def load_regions(path: Path = REGIONS_FILE) -> RegionsConfig:
    return load_yaml_model(path, RegionsConfig)


def ensure_analytics_schema(conn: psycopg.Connection) -> None:
    """Schema for setup metadata and the region mapping (owned by the owner role)."""
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS analytics")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analytics.data_setup ("
            " key text PRIMARY KEY,"
            " value text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )


def apply_date_shift(conn: psycopg.Connection, years: int) -> bool:
    """Shift every Northwind date forward by ``years``, exactly once.

    Returns True when the shift was applied now, False when it was already applied.
    Raises SeedError if a different shift was applied before.
    """
    with conn.transaction():
        conn.execute("LOCK TABLE analytics.data_setup IN EXCLUSIVE MODE")
        row = conn.execute(
            "SELECT value FROM analytics.data_setup WHERE key = %s", (SHIFT_KEY,)
        ).fetchone()
        if row is not None:
            if int(row[0]) != years:
                raise SeedError(
                    f"dates were already shifted by {row[0]} years; config asks for {years}. "
                    "Reset the database (docker compose down -v) to change the shift."
                )
            return False
        for table, columns in DATE_COLUMNS.items():
            assignments = sql.SQL(", ").join(
                sql.SQL("{col} = ({col} + make_interval(years => %(y)s))::date").format(
                    col=sql.Identifier(col)
                )
                for col in columns
            )
            conn.execute(
                sql.SQL("UPDATE public.{table} SET {assignments}").format(
                    table=sql.Identifier(table), assignments=assignments
                ),
                {"y": years},
            )
        conn.execute(
            "INSERT INTO analytics.data_setup (key, value) VALUES (%s, %s)",
            (SHIFT_KEY, str(years)),
        )
        return True


def applied_date_shift(conn: psycopg.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM analytics.data_setup WHERE key = %s", (SHIFT_KEY,)
    ).fetchone()
    return int(row[0]) if row else None


def sync_regions(conn: psycopg.Connection, config: RegionsConfig) -> dict[str, int]:
    """Upsert the region mapping and its lookup views. Returns customers per region."""
    mapping = [(c, r.code.value) for r in config.regions for c in r.countries]
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analytics.sales_regions ("
            " code text PRIMARY KEY, name text NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS analytics.country_region ("
            " country text PRIMARY KEY,"
            " region_code text NOT NULL REFERENCES analytics.sales_regions (code))"
        )
        for region in config.regions:
            conn.execute(
                "INSERT INTO analytics.sales_regions (code, name) VALUES (%s, %s) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name",
                (region.code.value, region.name),
            )
        conn.execute(
            "DELETE FROM analytics.country_region WHERE NOT (country = ANY(%s))",
            ([c for c, _ in mapping],),
        )
        for country, code in mapping:
            conn.execute(
                "INSERT INTO analytics.country_region (country, region_code) VALUES (%s, %s) "
                "ON CONFLICT (country) DO UPDATE SET region_code = EXCLUDED.region_code",
                (country, code),
            )
        conn.execute(
            "CREATE OR REPLACE VIEW analytics.customer_regions AS "
            "SELECT c.customer_id, cr.region_code "
            "FROM public.customers c JOIN analytics.country_region cr ON cr.country = c.country"
        )
        conn.execute(
            "CREATE OR REPLACE VIEW analytics.order_regions AS "
            "SELECT o.order_id, cr.customer_id, cr.region_code "
            "FROM public.orders o JOIN analytics.customer_regions cr "
            "ON cr.customer_id = o.customer_id"
        )
        unmapped = conn.execute(
            "SELECT DISTINCT c.country FROM public.customers c "
            "LEFT JOIN analytics.country_region cr ON cr.country = c.country "
            "WHERE cr.country IS NULL ORDER BY 1"
        ).fetchall()
        if unmapped:
            raise SeedError(
                "customer countries without a region: " + ", ".join(str(r[0]) for r in unmapped)
            )
    rows = conn.execute(
        "SELECT region_code, count(*) FROM analytics.customer_regions GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {str(code): int(n) for code, n in rows}

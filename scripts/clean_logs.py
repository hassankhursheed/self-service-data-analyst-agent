"""Remove logs older than the retention period (config/app.yaml ``retention.log_days``).

    python -m scripts.clean_logs              # dry run: shows what would be removed
    python -m scripts.clean_logs --yes        # remove them
    python -m scripts.clean_logs --days 30    # another period for this run

Run it daily (cron, or a Railway cron service; docs/deployment.md). Conversations,
questions, runs and the Northwind data are never touched.
"""

import argparse
import sys

from app.core.config import get_settings
from app.db.setup.log_retention import clean_logs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="really delete (default: dry run)")
    parser.add_argument("--days", type=int, help="keep this many days instead of the config")
    args = parser.parse_args()
    report = clean_logs(get_settings(), apply=args.yes, days=args.days)
    print(f"Logs older than {report.cutoff:%Y-%m-%d %H:%M} UTC")
    print("Removed:" if report.applied else "Would remove (dry run, nothing changed):")
    for table, count in report.counts.items():
        print(f"  {table:<18} {count}")
    if not report.applied:
        print("Run again with --yes to remove them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

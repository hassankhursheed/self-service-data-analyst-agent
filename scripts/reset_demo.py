"""Reset the demo data safely (Step 25, docs/deployment.md).

    python -m scripts.reset_demo                 # dry run: shows what would be removed
    python -m scripts.reset_demo --yes           # remove demo activity and re-seed
    python -m scripts.reset_demo --yes --keep-eval

Never touches the Northwind data. Removes conversations, questions, runs, feedback,
errors, the audit log, alerts, checkpoints, non-demo users and (unless --keep-eval)
evaluation runs, then runs the seed so the demo accounts and the verified library are
back to their seeded state.
"""

import argparse
import sys

from app.core.config import get_settings
from app.db.setup.reset_demo import reset_demo


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--yes", action="store_true", help="really reset (default: dry run)")
    parser.add_argument("--keep-eval", action="store_true", help="keep evaluation runs")
    args = parser.parse_args()
    settings = get_settings()
    print(
        f"Database {settings.postgres_db} on {settings.postgres_host}:{settings.postgres_port} "
        f"(APP_ENV={settings.app_env})"
    )
    report = reset_demo(settings, apply=args.yes, keep_eval=args.keep_eval)
    print("Removed:" if report.applied else "Would remove (dry run, nothing changed):")
    for name, count in report.counts.items():
        print(f"  {name:<20} {count}")
    if report.removed_users:
        print(f"  users: {', '.join(report.removed_users)}")
    if report.applied:
        print("Demo reset and re-seeded. Northwind data was not touched.")
    else:
        print("Run again with --yes to reset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

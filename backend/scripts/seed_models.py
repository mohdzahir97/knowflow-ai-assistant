"""Populate the model catalogue from the providers' built-in defaults.

The migration seeds an existing installation. This script covers the other
cases: a database created with `create_all` rather than migrations, a
provider added by a later release whose models are missing, or an operator
who wants to start over.

Additive by default - existing rows are left exactly as they are, including
ones that were disabled deliberately. `--reset` is the destructive variant
and says so.

Usage
-----
    python scripts/seed_models.py                # add anything missing
    python scripts/seed_models.py --reset        # wipe and re-seed
    python scripts/seed_models.py --list         # show the catalogue
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.provider_model import ProviderModel  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.model_catalog import get_model_catalog_service  # noqa: E402


def _list() -> int:
    with SessionLocal() as db:
        rows = get_model_catalog_service().list_all(db)
        if not rows:
            print("The catalogue is empty. The providers' built-in defaults are being used.")
            print("Run this script without --list to populate it.")
            return 0

        current_group = None
        for row in rows:
            group = (row.kind.value, row.provider)
            if group != current_group:
                print(f"\n{row.kind.value} / {row.provider}")
                current_group = group
            status = "" if row.is_enabled else "   (disabled)"
            label = f" [{row.display_name}]" if row.display_name else ""
            print(f"  {row.model_name}{label}{status}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the provider model catalogue.")
    parser.add_argument("--reset", action="store_true", help="delete every row first, then re-seed")
    parser.add_argument("--list", action="store_true", help="print the catalogue and exit")
    args = parser.parse_args()

    if args.list:
        return _list()

    with SessionLocal() as db:
        if args.reset:
            existing = db.query(ProviderModel).count()
            print(f"--reset: deleting {existing} existing row(s), including any you added or disabled.")
        added = get_model_catalog_service().seed_defaults(db, overwrite=args.reset)

    print(f"{added} model(s) added.")
    print("Restart the API, or edit through the admin UI, for changes to take effect immediately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

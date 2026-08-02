"""Create, verify, or restore a bounded PostgreSQL custom-format archive."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.app.infrastructure.postgres_backup import PostgresBackupRunner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("dump", "verify", "restore"),
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL URL; password is read into PGPASSWORD, never logged.",
    )
    parser.add_argument("--backup", type=Path, help="Existing custom-format archive.")
    parser.add_argument("--output", type=Path, help="Destination archive for dump.")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--allow-destructive-restore",
        action="store_true",
        help="Allow pg_restore --clean --if-exists for an isolated target.",
    )
    args = parser.parse_args()
    runner = PostgresBackupRunner(timeout_seconds=args.timeout)

    if args.operation == "dump":
        if not args.database_url or args.output is None:
            parser.error("dump requires --database-url and --output")
        archive = runner.dump(args.database_url, args.output)
        print(
            json.dumps(
                {
                    "operation": "dump",
                    "archive": str(archive),
                    "bytes": archive.stat().st_size,
                }
            )
        )
        return 0

    if args.backup is None:
        parser.error(f"{args.operation} requires --backup")
    if args.operation == "verify":
        print(
            json.dumps({"operation": "verify", "objects": runner.verify(args.backup)})
        )
        return 0

    if not args.database_url:
        parser.error("restore requires --database-url")
    runner.restore(
        args.database_url,
        args.backup,
        destructive=args.allow_destructive_restore,
    )
    print(json.dumps({"operation": "restore", "status": "ok"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

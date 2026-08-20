"""Create deterministic demo tenants and users without storing plaintext passwords."""

from __future__ import annotations

import argparse
import os

from src.app.infrastructure.factory import build_identity_repository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", help="demo password; use a secret outside Git")
    args = parser.parse_args()
    password = args.password or os.getenv("SEED_IDENTITY_PASSWORD")
    if not password:
        raise SystemExit(
            "provide --password or SEED_IDENTITY_PASSWORD; "
            "password must contain at least 12 characters"
        )
    repository = build_identity_repository()
    if repository is None:
        raise SystemExit("DATABASE_URL is required")
    try:
        repository.upsert_tenant("tenant-a", "robotics-a", "智扫通华东服务中心")
        repository.upsert_tenant("tenant-b", "robotics-b", "智扫通华南服务中心")
        repository.upsert_user(
            "demo-admin",
            "admin@example.com",
            "平台管理员",
            password,
        )
        repository.upsert_user(
            "demo-agent-a",
            "agent-a@example.com",
            "华东客服",
            password,
        )
        repository.upsert_user(
            "demo-agent-b",
            "agent-b@example.com",
            "华南客服",
            password,
        )
        repository.upsert_membership("demo-admin", "tenant-a", "admin")
        repository.upsert_membership("demo-admin", "tenant-b", "admin")
        repository.upsert_membership("demo-agent-a", "tenant-a", "service_agent")
        repository.upsert_membership("demo-agent-b", "tenant-b", "service_agent")
    finally:
        repository.close()
    print("identity demo data seeded")


if __name__ == "__main__":
    main()

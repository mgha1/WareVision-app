#!/usr/bin/env python3

"""List all tables in the Oracle ADB schema.

This script uses python-oracledb (thin mode) with wallet-based mTLS.
It talks directly to the same database your Oracle MCP server uses.
"""

import os
import sys
from typing import List

import oracledb


# Oracle ADB connection details
DB_USER = "HKTR1G4"
DB_PASSWORD = "Hk1_ySVtqYZp-Dayk_zl"
DB_DSN = "hkt202602_high"
WALLET_DIR = "/home/opc/wallet"


def fetch_tables() -> List[str]:
    """Connect to Oracle and return table names from USER_TABLES."""
    # Recommended for wallet / tnsnames lookup
    os.environ["TNS_ADMIN"] = WALLET_DIR

    with oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        wallet_location=WALLET_DIR,
        wallet_password="",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM user_tables
                ORDER BY table_name
                """
            )
            return [row[0] for row in cur.fetchall()]


def main() -> int:
    try:
        tables = fetch_tables()
    except Exception as exc:
        print(f"❌ Failed to connect/query Oracle DB: {exc}", file=sys.stderr)
        return 1

    print(f"Connected as: {DB_USER}")
    print(f"Tables found: {len(tables)}")
    print("-" * 40)

    for table in tables:
        print(table)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
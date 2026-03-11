"""
Query Fabric SQL endpoint for customer_snapshots table.

Prerequisites:
  1. brew install openssl          (macOS one-time)
  2. pip install mssql-python python-dotenv
  3. az login                      (authenticate with Azure Entra ID)
  4. Copy .env.example → .env and fill in your values (or rely on defaults below)

Connection string parts come from Fabric portal:
  Database Settings → Connection strings → ODBC tab

Authentication uses ActiveDirectoryDefault which picks up your 'az login' token.

References:
  - https://learn.microsoft.com/fabric/database/sql/connect-python
  - https://learn.microsoft.com/azure/azure-sql/database/azure-sql-python-quickstart
  - https://learn.microsoft.com/fabric/database/sql/authentication
"""

import argparse
from os import getenv
from dotenv import load_dotenv
from mssql_python import connect

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration – override via .env or environment variables
# ---------------------------------------------------------------------------
FABRIC_SERVER = getenv(
    "FABRIC_SQL_SERVER",
    "tymdrsbdpxrexhktg6x5png2xa-pome2etdktvudoewgwiabd6w2u.datawarehouse.fabric.microsoft.com",
)
FABRIC_DATABASE = getenv("FABRIC_SQL_DATABASE", "postgres-mirror")

# Build ODBC-style connection string for mssql-python
# ActiveDirectoryDefault uses the token from 'az login' on macOS/Linux
CONNECTION_STRING = (
    f"Server={FABRIC_SERVER},1433;"
    f"Database={FABRIC_DATABASE};"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Authentication=ActiveDirectoryDefault;"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Fabric SQL endpoint")
    parser.add_argument("--flatten", action="store_true", help="Print each row as key: value pairs")
    args = parser.parse_args()

    print(f"Connecting to {FABRIC_SERVER} / {FABRIC_DATABASE} ...")

    conn = connect(CONNECTION_STRING)
    cursor = conn.cursor()

    # Query the mirrored postgres table
    # Fabric exposes mirrored schemas as-is; the postgres public schema
    # appears as [_public] in the SQL analytics endpoint.
    sql = "SELECT TOP 10 * FROM [_public].[customer_snapshots]"
    print(f"\nExecuting: {sql}\n")

    cursor.execute(sql)

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()

    if args.flatten:
        for row in rows:
            print(", ".join(f'"{col}":{val}' for col, val in zip(columns, row)))
    else:
        print(" | ".join(columns))
        print("-" * (len(" | ".join(columns))))
        for row in rows:
            print(" | ".join(str(v) for v in row))

    cursor.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()

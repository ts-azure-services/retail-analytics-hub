"""
Test script for local SQL Server in Docker.

Usage:
  1. Start the container:  docker compose -f temp-stash/docker-compose.yml up -d
  2. Wait ~10s for SQL Server to initialize
  3. Run this script:      python temp-stash/test_local_sqlserver.py

This script:
  - Connects to the local SQL Server (SA account) via pymssql/FreeTDS
  - Creates a test database and table
  - Inserts 10 sample rows
  - Queries them back and prints them
  - Cleans up the test database
"""

import time
import pymssql

# Local SQL Server connection (matches docker-compose.yml)
SERVER = "localhost"
PORT = 1433
USER = "sa"
PASSWORD = "DevPass#2026!"

SAMPLE_DATA = [
    ("Alice", "alice@example.com", 4.5),
    ("Bob", "bob@example.com", 3.8),
    ("Carol", "carol@example.com", 4.9),
    ("Dave", "dave@example.com", 2.1),
    ("Eve", "eve@example.com", 3.5),
    ("Frank", "frank@example.com", 4.0),
    ("Grace", "grace@example.com", 4.7),
    ("Hank", "hank@example.com", 3.2),
    ("Ivy", "ivy@example.com", 4.3),
    ("Jack", "jack@example.com", 3.9),
]


def wait_for_server(max_retries: int = 10, delay: int = 3) -> None:
    """Wait for SQL Server to be ready."""
    for attempt in range(1, max_retries + 1):
        try:
            conn = pymssql.connect(
                server=SERVER, port=PORT, user=USER, password=PASSWORD,
                database="master", login_timeout=5,
            )
            conn.close()
            print("SQL Server is ready.")
            return
        except Exception as e:
            print(f"Waiting for SQL Server... (attempt {attempt}/{max_retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("SQL Server did not become ready in time.")


def main() -> None:
    wait_for_server()

    # --- Setup: create database and table ---
    print("\n1. Creating test database and table...")
    conn = pymssql.connect(
        server=SERVER, port=PORT, user=USER, password=PASSWORD,
        database="master", autocommit=True,
    )
    cursor = conn.cursor()

    cursor.execute("""
        IF DB_ID('TestDB') IS NOT NULL
            DROP DATABASE TestDB
    """)
    cursor.execute("CREATE DATABASE TestDB")
    cursor.close()
    conn.close()

    # Connect to the new database
    conn = pymssql.connect(
        server=SERVER, port=PORT, user=USER, password=PASSWORD,
        database="TestDB", autocommit=True,
    )
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE CustomerReviews (
            Id INT IDENTITY(1,1) PRIMARY KEY,
            Name NVARCHAR(100),
            Email NVARCHAR(200),
            Rating DECIMAL(2,1)
        )
    """)
    print("   Table 'CustomerReviews' created.")

    # --- Insert 10 rows ---
    print("\n2. Inserting 10 rows...")
    for name, email, rating in SAMPLE_DATA:
        cursor.execute(
            "INSERT INTO CustomerReviews (Name, Email, Rating) VALUES (%s, %s, %s)",
            (name, email, rating),
        )
    print("   10 rows inserted.")

    # --- Query them back ---
    print("\n3. Querying all rows...\n")
    cursor.execute("SELECT Id, Name, Email, Rating FROM CustomerReviews")

    columns = [col[0] for col in cursor.description]
    rows = cursor.fetchall()
    print(" | ".join(columns))
    print("-" * 60)

    for row in rows:
        print(" | ".join(str(v) for v in row))

    # --- Cleanup ---
    cursor.close()
    conn.close()

    print("\n4. Cleaning up (dropping TestDB)...")
    conn = pymssql.connect(
        server=SERVER, port=PORT, user=USER, password=PASSWORD,
        database="master", autocommit=True,
    )
    cursor = conn.cursor()
    cursor.execute("DROP DATABASE TestDB")
    cursor.close()
    conn.close()

    print("Done.")


if __name__ == "__main__":
    main()

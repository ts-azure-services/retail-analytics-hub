"""DuckDB helpers for the customer_reviews and raw_reviews tables."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from agents.shared.config import get_settings

_DDL = """\
CREATE TABLE IF NOT EXISTS customer_reviews (
    id                  INTEGER PRIMARY KEY,
    review_text         VARCHAR NOT NULL,
    sentiment_category  VARCHAR,
    sentiment_score     DOUBLE,
    status              VARCHAR NOT NULL DEFAULT 'To be processed',
    chatbot_statement   VARCHAR,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at        TIMESTAMP,
    error_message       VARCHAR,
    retry_count         INTEGER DEFAULT 0,
    last_retry_at       TIMESTAMP
);
"""

_RAW_DDL = """\
CREATE TABLE IF NOT EXISTS raw_reviews (
    id          INTEGER PRIMARY KEY,
    review_text VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed    BOOLEAN DEFAULT FALSE
);
"""


def _connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(get_settings().customer_reviews_db)


def init_schema() -> None:
    """Create the customer_reviews and raw_reviews tables if they don't exist."""
    con = _connect()
    try:
        con.execute(_DDL)
        con.execute(_RAW_DDL)
    finally:
        con.close()


def insert_review(review_id: int, review_text: str) -> None:
    """Insert a new review with status 'To be processed'."""
    con = _connect()
    try:
        con.execute(
            "INSERT INTO customer_reviews (id, review_text, status) VALUES (?, ?, ?)",
            [review_id, review_text, "To be processed"],
        )
    finally:
        con.close()


def update_review_result(
    review_id: int,
    *,
    sentiment_category: str,
    sentiment_score: float,
    status: str,
    chatbot_statement: str | None = None,
) -> None:
    """Update a review with analysis results."""
    con = _connect()
    try:
        con.execute(
            """
            UPDATE customer_reviews
            SET sentiment_category = ?,
                sentiment_score    = ?,
                status             = ?,
                chatbot_statement  = ?,
                processed_at       = ?
            WHERE id = ?
            """,
            [
                sentiment_category,
                sentiment_score,
                status,
                chatbot_statement,
                datetime.now(timezone.utc),
                review_id,
            ],
        )
    finally:
        con.close()


def mark_error(review_id: int, error_message: str) -> None:
    """Mark a review as incomplete processing with an error message."""
    con = _connect()
    try:
        con.execute(
            """
            UPDATE customer_reviews
            SET status        = 'incomplete processing',
                error_message = ?,
                retry_count   = retry_count + 1,
                last_retry_at = ?
            WHERE id = ?
            """,
            [error_message, datetime.now(timezone.utc), review_id],
        )
    finally:
        con.close()


def get_retryable_reviews(max_retries: int = 3) -> list[dict]:
    """Return reviews that are eligible for retry."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT id, review_text, retry_count
            FROM customer_reviews
            WHERE status IN ('incomplete processing', 'To be processed')
              AND retry_count < ?
            ORDER BY id
            """,
            [max_retries],
        ).fetchall()
        return [
            {"id": r[0], "review_text": r[1], "retry_count": r[2]} for r in rows
        ]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# raw_reviews helpers (local mode staging table)
# ---------------------------------------------------------------------------


def get_pending_raw_reviews(limit: int = 20) -> list[dict]:
    """Return unconsumed raw reviews for processing."""
    con = _connect()
    try:
        rows = con.execute(
            """
            SELECT id, review_text
            FROM raw_reviews
            WHERE consumed = FALSE
            ORDER BY id
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        return [{"id": r[0], "review_text": r[1]} for r in rows]
    finally:
        con.close()


def mark_raw_review_consumed(review_id: int) -> None:
    """Mark a raw review as consumed after successful processing."""
    con = _connect()
    try:
        con.execute(
            "UPDATE raw_reviews SET consumed = TRUE WHERE id = ?",
            [review_id],
        )
    finally:
        con.close()

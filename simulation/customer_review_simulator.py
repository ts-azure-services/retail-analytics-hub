"""Customer review simulator.

Populates the customer_reviews table in the event_hubs DuckDB database
with all canned reviews in a single batch.

Usage:
    uv run python -m simulation.customer_review_simulator
    uv run python -m simulation.customer_review_simulator --db /path/to/event_hubs.duckdb
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CANNED_REVIEWS = [
    "Honestly one of the worst chocolates I've tried. It tasted stale and had a strange waxy texture.",
    "Not impressed. The chocolate was overly sweet and the flavor felt artificial.",
    "I expected more richness, but it was pretty bland and didn't melt nicely.",
    "The chocolate itself was okay, but the aftertaste was oddly bitter.",
    "It's decent chocolate. Nothing special, but it's fine for a quick snack.",
    "Pretty good overall. Smooth texture, though I wish the cocoa flavor was a bit stronger.",
    "Nice creamy texture and balanced sweetness. I'd definitely buy this again.",
    "Really enjoyable chocolate—rich, smooth, and not too sweet.",
    "This chocolate is fantastic. Deep cocoa flavor and melts perfectly.",
    "Absolutely delicious. Smooth, rich, and easily one of the best chocolates I've had.",
]

_DEFAULT_DB = str(Path(__file__).resolve().parents[1] / "event_hubs.duckdb")

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


def seed_reviews(db_path: str) -> None:
    """Insert all canned reviews into the customer_reviews table."""
    con = duckdb.connect(db_path)
    try:
        con.execute(_DDL)

        row = con.execute("SELECT COALESCE(MAX(id), 0) FROM customer_reviews").fetchone()
        next_id = row[0] + 1

        for i, review_text in enumerate(CANNED_REVIEWS):
            review_id = next_id + i
            con.execute(
                "INSERT INTO customer_reviews (id, review_text, status) VALUES (?, ?, ?)",
                [review_id, review_text, "To be processed"],
            )
            logger.info("Inserted review %d: %.60s...", review_id, review_text)

        logger.info("Seeded %d reviews into %s", len(CANNED_REVIEWS), db_path)
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Customer review simulator")
    parser.add_argument(
        "--db",
        type=str,
        default=_DEFAULT_DB,
        help="Path to event_hubs DuckDB file (default: event_hubs.duckdb)",
    )
    args = parser.parse_args()

    logger.info("Seeding reviews into %s", args.db)
    seed_reviews(args.db)
    logger.info("Done")


if __name__ == "__main__":
    main()

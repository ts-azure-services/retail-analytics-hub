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
    "honestly the sea salt caramel ones were kinda disappointing. caramel tasted weird.",
    "that 85% dark bar is just straight bitter… not enjoyable at all.",
    "the espresso bites tasted burnt to me.",
    "those cherry cordials were way too syrupy.",
    "orange peel chocolate sounded good but the peel was super chewy.",
    "raspberry dark chocolate bar was kinda sour.",
    "almond bark had too many almonds and barely any chocolate.",
    "the mint thins taste fake… like toothpaste.",
    "regular milk chocolate bar was just meh. nothing special.",
    "peanut clusters were stale when I opened the bag.",
    "caramel squares were messy and stuck to my teeth.",
    "honeycomb chocolate barely had any crunch.",
    "hazelnut bar tasted waxy.",
    "pretzel bites were soft instead of crunchy.",
    "toffee squares were way too hard.",
    "chocolate raisins had a weird taste.",
    "white chocolate raspberry bark was just sugar overload.",
    "macadamia white chocolate had stale nuts.",
    "lemon truffles tasted artificial.",
    "coconut white chocolate was greasy.",
    "strawberry cream chocolates were way too sweet.",
    "peppermint white chocolate had way too much mint.",
    "pistachio chocolate barely had pistachios.",
    "cranberry chocolate was super tart.",
    "champagne truffles didn’t really taste like champagne.",
    "salted caramel truffles were too salty for me.",
    "lavender truffles honestly tasted like soap.",
    "earl grey truffles were kinda strange.",
    "bourbon truffles were way too strong.",
    "matcha truffles tasted grassy.",
    "hazelnut praline truffles were okay but too sugary.",
    "passion fruit truffles were kinda sour.",
    "the big milk chocolate bar was fine but basic.",
    "almond dark chocolate bar was decent.",
    "sea salt caramel bar had uneven caramel.",
    "cookie crunch bar was a bit stale tasting.",
    "mint dark chocolate bar was okay.",
    "raspberry dark chocolate was pretty tart.",
    "peanut butter chocolate bar was salty.",
    "toffee crunch bar stuck in my teeth.",
    "cherry cordial box was kinda hit or miss.",
    "cream center assortment was average.",
    "caramel filled chocolates were decent.",
    "nut clusters were alright.",
    "fruit cream chocolates were a little sweet.",
    "coffee cream chocolates were pretty good actually.",
    "nougat chocolates were soft but mild.",
    "marzipan chocolate was fine but dense.",
    "coconut bonbons were sweeter than expected.",
    "peanut butter cups were good but not amazing.",
    "plain milk chocolate bar was smooth.",
    "peanut clusters were actually pretty tasty.",
    "almond bark had a nice crunch.",
    "chocolate orange peel had a nice citrus kick.",
    "raspberry dark chocolate was kinda nice.",
    "mint thins were refreshing.",
    "hazelnut milk chocolate bar was good.",
    "pretzel chocolate bites had a good sweet/salty thing going.",
    "toffee milk chocolate squares were crunchy.",
    "chocolate raisins make a good snack.",
    "raspberry white chocolate bark was pretty good.",
    "macadamia white chocolate was rich.",
    "lemon truffles were bright and citrusy.",
    "coconut white chocolate tasted tropical.",
    "strawberry cream chocolates were smooth.",
    "peppermint white chocolate was nice and cool.",
    "pistachio chocolate had good texture.",
    "cranberry white chocolate had a nice tartness.",
    "champagne truffles felt fancy.",
    "salted caramel truffles were really nice.",
    "lavender honey truffles were surprisingly good.",
    "earl grey truffles had a cool tea flavor.",
    "bourbon truffles had a deep flavor.",
    "matcha truffles were interesting actually.",
    "hazelnut praline truffles were rich.",
    "passion fruit truffles had a fun tropical taste.",
    "big milk chocolate bar melts really well.",
    "dark almond bar had great roasted almond flavor.",
    "caramel sea salt bar is addictive.",
    "cookie crunch chocolate bar was fun to eat.",
    "mint dark chocolate bar is super refreshing.",
    "raspberry dark chocolate bar was really good.",
    "peanut butter chocolate bar was creamy.",
    "toffee crunch bar had great texture.",
    "cherry cordial box was delicious.",
    "cream assortment had some really good ones.",
    "caramel chocolates were super smooth.",
    "nut clusters were awesome.",
    "fruit cream chocolates were surprisingly good.",
    "coffee cream chocolates were perfect with coffee.",
    "nougat chocolates were soft and tasty.",
    "marzipan chocolates were great if you like almond flavor.",
    "coconut bonbons were really good.",
    "peanut butter cups were dangerously addictive.",
    "sea salt caramel dark chocolates are amazing.",
    "that 85% dark bar is intense but really good.",
    "espresso dark chocolate bites are fantastic.",
    "cherry cordials were incredible.",
    "orange peel dark chocolate was amazing.",
    "the raspberry dark chocolate is honestly one of my favorites."
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

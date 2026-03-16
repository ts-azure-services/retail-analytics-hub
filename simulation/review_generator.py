"""Review generator — seed raw review events for Agent 3 processing.

Works in both local and cloud mode:
  Local (default):  Inserts into the ``raw_reviews`` table in event_hubs.duckdb.
                    Agent 3 polls this table, processes, and writes to
                    ``customer_reviews``.
  Cloud:            Publishes events to the ``raw-reviews`` Azure EventHub.
                    Agent 3 consumes, processes, and publishes to the
                    ``processed-reviews`` EventHub.

Two generation modes:
  --mode canned   Use the built-in CANNED_REVIEWS list (fast, no API cost).
  --mode llm      Call gpt-4o-mini to generate novel reviews from product
                  descriptions (richer, more varied).

Usage:
    # Local — batch insert into DuckDB
    uv run python -m simulation.review_generator --mode canned

    # Local — drip feed, one review every 5 seconds
    uv run python -m simulation.review_generator --mode canned --drip 5

    # Cloud — publish to EventHub
    uv run python -m simulation.review_generator --mode canned

    # LLM-generated reviews (requires AZURE_OPENAI_ENDPOINT in env)
    uv run python -m simulation.review_generator --mode llm --count 20
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load env files (local.env first, fabric.env for cloud-specific vars)
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / "local.env")
load_dotenv(_REPO_ROOT / "fabric.env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chocolate product catalogue (used by LLM mode prompt)
# ---------------------------------------------------------------------------
PRODUCT_CATALOGUE = [
    {"name": "Sea Salt Caramel Bar", "description": "Dark chocolate bar with a gooey salted caramel centre."},
    {"name": "85% Dark Cocoa Bar", "description": "Intense single-origin 85% cacao dark chocolate."},
    {"name": "Espresso Dark Bites", "description": "Bite-sized dark chocolates infused with espresso."},
    {"name": "Cherry Cordials", "description": "Milk chocolate shells filled with cherry cream liqueur."},
    {"name": "Orange Peel Dark Chocolate", "description": "Candied orange peel dipped in 70% dark chocolate."},
    {"name": "Raspberry Dark Chocolate Bar", "description": "Dark chocolate bar with freeze-dried raspberry pieces."},
    {"name": "Almond Bark", "description": "Roasted almond clusters in milk chocolate."},
    {"name": "Mint Thins", "description": "Crisp dark chocolate wafers with peppermint cream."},
    {"name": "Milk Chocolate Bar", "description": "Classic creamy milk chocolate bar, 100g."},
    {"name": "Peanut Clusters", "description": "Roasted peanuts in milk chocolate clusters."},
    {"name": "Caramel Squares", "description": "Chewy caramel wrapped in milk chocolate."},
    {"name": "Honeycomb Chocolate", "description": "Crunchy honeycomb pieces coated in milk chocolate."},
    {"name": "Hazelnut Milk Bar", "description": "Smooth milk chocolate with whole roasted hazelnuts."},
    {"name": "Pretzel Chocolate Bites", "description": "Crunchy pretzel pieces in dark chocolate."},
    {"name": "Toffee Crunch Bar", "description": "Butter toffee shards in milk chocolate."},
    {"name": "Lavender Honey Truffles", "description": "Creamy ganache truffles with lavender and wildflower honey."},
    {"name": "Earl Grey Truffles", "description": "White chocolate ganache infused with Earl Grey tea."},
    {"name": "Bourbon Truffles", "description": "Dark chocolate truffles with a bourbon-infused centre."},
    {"name": "Matcha Truffles", "description": "White chocolate truffles dusted with Japanese matcha."},
    {"name": "Passion Fruit Truffles", "description": "Tangy passion fruit ganache in dark chocolate shells."},
]

# ---------------------------------------------------------------------------
# Canned reviews (single source of truth — previously in customer_review_simulator.py)
# ---------------------------------------------------------------------------
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
    "champagne truffles didn't really taste like champagne.",
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
    "the raspberry dark chocolate is honestly one of my favorites.",
]

# ---------------------------------------------------------------------------
# LLM review generation
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a customer who just purchased a chocolate product. Write a short,
casual customer review (1-3 sentences) for the product described below.
Randomly vary between very negative, negative, neutral, positive, and very
positive sentiment. Be authentic — use informal language, occasional typos,
and the tone of a real online review. Return ONLY the review text, nothing
else."""


def _generate_llm_reviews(count: int) -> list[str]:
    """Call Azure OpenAI gpt-4o-mini to generate *count* novel reviews."""
    from azure.identity import DefaultAzureCredential
    from openai import AzureOpenAI

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    if not endpoint:
        logger.error("AZURE_OPENAI_ENDPOINT not set — cannot use LLM mode")
        sys.exit(1)

    credential = DefaultAzureCredential()
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=lambda: credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
    )

    deployment = os.getenv("GPT_4O_MINI_DEPLOYMENT", "gpt-4o-mini")
    reviews: list[str] = []

    for _ in range(count):
        product = random.choice(PRODUCT_CATALOGUE)
        user_prompt = (
            f"Product: {product['name']}\n"
            f"Description: {product['description']}\n\n"
            "Write your review:"
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=1.0,
            max_tokens=150,
        )
        review_text = resp.choices[0].message.content.strip()
        reviews.append(review_text)
        logger.info("Generated LLM review: %.80s...", review_text)

    return reviews


# ---------------------------------------------------------------------------
# Target detection
# ---------------------------------------------------------------------------

_DEFAULT_DB = str(_REPO_ROOT / "event_hubs.duckdb")


def _is_cloud_target() -> bool:
    """True when EventHub namespace + raw hub are configured."""
    return bool(os.getenv("EVENTHUB_NAMESPACE") and os.getenv("EVENTHUB_RAW_NAME"))


# ---------------------------------------------------------------------------
# Local publisher — insert into raw_reviews table in DuckDB
# ---------------------------------------------------------------------------

_RAW_DDL = """\
CREATE TABLE IF NOT EXISTS raw_reviews (
    id          INTEGER PRIMARY KEY,
    review_text VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed    BOOLEAN DEFAULT FALSE
);
"""


def _seed_local(reviews: list[str], *, drip_seconds: float = 0) -> None:
    """Insert reviews into the raw_reviews table in event_hubs.duckdb."""
    import duckdb

    db_path = os.getenv("EVENT_HUBS_DB", _DEFAULT_DB)
    con = duckdb.connect(db_path)
    try:
        con.execute(_RAW_DDL)
        row = con.execute("SELECT COALESCE(MAX(id), 0) FROM raw_reviews").fetchone()
        next_id = row[0] + 1

        for i, text in enumerate(reviews):
            review_id = next_id + i
            con.execute(
                "INSERT INTO raw_reviews (id, review_text, consumed) VALUES (?, ?, FALSE)",
                [review_id, text],
            )
            logger.info("Inserted raw review %d: %.60s…", review_id, text)
            if drip_seconds > 0 and i < len(reviews) - 1:
                con.close()
                time.sleep(drip_seconds)
                con = duckdb.connect(db_path)

        logger.info("Seeded %d raw reviews into %s", len(reviews), db_path)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Cloud publisher — publish to raw-reviews EventHub
# ---------------------------------------------------------------------------


def _seed_cloud(reviews: list[str], *, drip_seconds: float = 0) -> None:
    """Publish review events to the raw-reviews EventHub."""
    from azure.eventhub import EventHubProducerClient, EventData
    from azure.identity import DefaultAzureCredential

    namespace = os.getenv("EVENTHUB_NAMESPACE", "")
    raw_hub = os.getenv("EVENTHUB_RAW_NAME", "")
    fqns = namespace if ".servicebus.windows.net" in namespace else f"{namespace}.servicebus.windows.net"

    producer = EventHubProducerClient(
        fully_qualified_namespace=fqns,
        eventhub_name=raw_hub,
        credential=DefaultAzureCredential(),
    )

    try:
        if drip_seconds > 0:
            for i, text in enumerate(reviews, start=1):
                event_body = json.dumps({
                    "id": i,
                    "review_text": text,
                    "status": "To be processed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                batch = producer.create_batch()
                batch.add(EventData(event_body))
                producer.send_batch(batch)
                logger.info("Sent review %d/%d", i, len(reviews))
                if i < len(reviews):
                    time.sleep(drip_seconds)
        else:
            batch = producer.create_batch()
            for i, text in enumerate(reviews, start=1):
                event_body = json.dumps({
                    "id": i,
                    "review_text": text,
                    "status": "To be processed",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                try:
                    batch.add(EventData(event_body))
                except ValueError:
                    producer.send_batch(batch)
                    batch = producer.create_batch()
                    batch.add(EventData(event_body))
                logger.info("Queued review %d/%d", i, len(reviews))
            producer.send_batch(batch)

        logger.info("Published %d reviews to raw-reviews EventHub", len(reviews))
    finally:
        producer.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate raw review events (local DuckDB or cloud EventHub)"
    )
    parser.add_argument(
        "--mode",
        choices=["canned", "llm"],
        default="canned",
        help="Review generation mode (default: canned)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of reviews to generate in LLM mode (default: 20)",
    )
    parser.add_argument(
        "--drip",
        type=float,
        default=0,
        help="Seconds between events (0 = batch send, default: 0)",
    )
    args = parser.parse_args()

    if args.mode == "llm":
        logger.info("Generating %d reviews via gpt-4o-mini", args.count)
        reviews = _generate_llm_reviews(args.count)
    else:
        reviews = list(CANNED_REVIEWS)
        random.shuffle(reviews)
        logger.info("Using %d canned reviews (shuffled)", len(reviews))

    if _is_cloud_target():
        logger.info("Cloud target detected — publishing to EventHub")
        _seed_cloud(reviews, drip_seconds=args.drip)
    else:
        logger.info("Local target — inserting into raw_reviews (DuckDB)")
        _seed_local(reviews, drip_seconds=args.drip)


if __name__ == "__main__":
    main()

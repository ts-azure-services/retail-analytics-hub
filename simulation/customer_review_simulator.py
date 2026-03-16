"""Customer review simulator — DEPRECATED.

This module is superseded by ``simulation.cloud_review_generator`` which
seeds raw reviews into both local (raw_reviews DuckDB table) and cloud
(EventHub) targets.  Agent 3 picks up from raw_reviews and populates
customer_reviews automatically.

Use instead:
    uv run python -m simulation.cloud_review_generator --mode canned
    uv run python -m simulation.cloud_review_generator --mode llm --count 20

The CANNED_REVIEWS list has been moved to cloud_review_generator.py.
This file re-exports it for backward compatibility only.
"""

from __future__ import annotations

import warnings

# Re-export from the canonical location for backward compatibility
from simulation.cloud_review_generator import CANNED_REVIEWS  # noqa: F401


def main() -> None:
    warnings.warn(
        "customer_review_simulator is deprecated",
        DeprecationWarning,
        stacklevel=2,
    )
    from simulation.cloud_review_generator import main as generator_main
    generator_main()


if __name__ == "__main__":
    main()

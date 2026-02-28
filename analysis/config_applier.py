"""
Apply sweep recommendations to simulation config.

Reads a recommendations.json file (produced by sweep_recommend.py) and
either previews changes or writes a config_overrides.json file that
SimulationConfig loads at construction time.

Usage:
    # Preview what would change
    uv run python analysis/config_applier.py --preview recommendations.json

    # Apply to config_overrides.json
    uv run python analysis/config_applier.py --apply recommendations.json

    # Apply only engagement params
    uv run python analysis/config_applier.py --apply recommendations.json --workflow engagement
"""

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERRIDES_PATH = REPO_ROOT / "config_overrides.json"

# Import config classes to read current defaults
sys.path.insert(0, str(REPO_ROOT))
from simulation.shared.config import (
    DistributionConfig,
    EngagementAssumptions,
    InventoryAssumptions,
    OmnichannelAssumptions,
)

SECTION_CLASSES = {
    "distributions": DistributionConfig,
    "omnichannel": OmnichannelAssumptions,
    "inventory": InventoryAssumptions,
    "engagement": EngagementAssumptions,
}


def get_current_defaults() -> dict[str, dict[str, any]]:
    """Read current dataclass defaults for comparison."""
    defaults = {}
    for section_name, cls in SECTION_CLASSES.items():
        instance = cls()
        section_defaults = {}
        for f in fields(cls):
            section_defaults[f.name] = getattr(instance, f.name)
        defaults[section_name] = section_defaults
    return defaults


def load_recommendations(path: str) -> dict:
    """Load recommendations.json."""
    with open(path) as f:
        return json.load(f)


def extract_overrides(
    recs: dict,
    workflow_filter: str | None = None,
    use_midpoint_for_ranges: bool = True,
) -> dict[str, dict[str, any]]:
    """Extract config overrides from recommendations.

    For fixed recommendations: use the recommended value.
    For range recommendations: use the midpoint (or the value from the
    top-scoring scenario).
    """
    overrides: dict[str, dict[str, any]] = {}

    for sweep_name, sweep_data in recs.get("sweeps", {}).items():
        wtype = sweep_data.get("workflow_type", "")

        if workflow_filter and workflow_filter != wtype:
            continue

        by_section = sweep_data.get("recommendations_by_section", {})
        top_params = sweep_data.get("top_params", {})

        for section_name, params in by_section.items():
            if section_name == "unknown":
                continue

            for param_name, rec in params.items():
                if rec["type"] == "fixed":
                    value = rec["value"]
                elif use_midpoint_for_ranges:
                    # Use the value from the top-scoring scenario
                    value = top_params.get(param_name)
                    if value is None:
                        value = (rec["min"] + rec["max"]) / 2
                else:
                    continue  # Skip ranges

                overrides.setdefault(section_name, {})[param_name] = value

    return overrides


def preview_changes(recs: dict, workflow_filter: str | None = None):
    """Show what would change without modifying files."""
    overrides = extract_overrides(recs, workflow_filter)
    defaults = get_current_defaults()

    print()
    print("=" * 80)
    print("  CONFIG CHANGE PREVIEW")
    if workflow_filter:
        print(f"  (filtered to: {workflow_filter})")
    print("=" * 80)

    any_changes = False
    for section_name in sorted(overrides.keys()):
        section_overrides = overrides[section_name]
        section_defaults = defaults.get(section_name, {})

        print(f"\n  [{section_name}]")
        for param, new_value in sorted(section_overrides.items()):
            current = section_defaults.get(param, "???")
            changed = current != new_value
            marker = " *" if changed else ""
            if isinstance(new_value, float):
                print(f"    {param}: {current} -> {new_value:.4g}{marker}")
            else:
                print(f"    {param}: {current} -> {new_value}{marker}")
            if changed:
                any_changes = True

    if not any_changes:
        print("\n  No changes detected (all values match current defaults).")

    print()
    print("=" * 80)

    # Show existing overrides file if present
    if OVERRIDES_PATH.exists():
        print(f"\n  Note: Existing overrides file found at {OVERRIDES_PATH}")
        with open(OVERRIDES_PATH) as f:
            existing = json.load(f)
        n_existing = sum(len(v) for v in existing.values() if isinstance(v, dict))
        print(f"  It contains {n_existing} override(s) which will be merged.")

    print()


def apply_overrides(recs: dict, workflow_filter: str | None = None):
    """Write config_overrides.json to project root."""
    new_overrides = extract_overrides(recs, workflow_filter)

    # Merge with existing overrides if present
    if OVERRIDES_PATH.exists():
        with open(OVERRIDES_PATH) as f:
            existing = json.load(f)
        # New values take precedence
        for section, params in new_overrides.items():
            if section in existing and isinstance(existing[section], dict):
                existing[section].update(params)
            else:
                existing[section] = params
        merged = existing
    else:
        merged = new_overrides

    with open(OVERRIDES_PATH, "w") as f:
        json.dump(merged, f, indent=2, default=str)

    n_params = sum(len(v) for v in merged.values() if isinstance(v, dict))
    print(f"\nWrote {n_params} override(s) to {OVERRIDES_PATH}")
    print("These will be loaded automatically by SimulationConfig on next run.")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Preview or apply sweep recommendations to config"
    )
    parser.add_argument(
        "recommendations_file",
        type=str,
        help="Path to recommendations.json",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true", help="Preview changes without applying")
    mode.add_argument("--apply", action="store_true", help="Write config_overrides.json")

    parser.add_argument(
        "--workflow",
        type=str,
        default=None,
        choices=["omnichannel", "inventory", "engagement"],
        help="Apply only recommendations for this workflow",
    )

    args = parser.parse_args()

    recs = load_recommendations(args.recommendations_file)

    if not recs.get("sweeps"):
        print("No sweep recommendations found in the file.")
        sys.exit(1)

    if args.preview:
        preview_changes(recs, args.workflow)
    elif args.apply:
        preview_changes(recs, args.workflow)
        apply_overrides(recs, args.workflow)


if __name__ == "__main__":
    main()

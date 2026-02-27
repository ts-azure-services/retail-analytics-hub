#!/usr/bin/env python3
"""
Train ML models on simulation data.

Usage:
    python analysis/train_models.py --scenarios all
    python analysis/train_models.py --scenarios conversion_0001,conversion_0002
    python analysis/train_models.py --model conversion --scenarios all
    python analysis/train_models.py --model-group omnichannel
    python analysis/train_models.py --model-group inventory
    python analysis/train_models.py --model-group engagement
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from simulation.ml import (
    # Omnichannel models
    ConversionModel,
    ValueModel,
    DemandForecastModel,
    FulfillmentModel,
    # Inventory models
    StockoutModel,
    LeadTimeModel,
    # Engagement models
    ChurnModel,
    CampaignResponseModel,
    CLVModel,
)
from simulation.ml.data_prep import DataExtractor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Model output directory
MODELS_DIR = Path(__file__).parent.parent / "models"

# Model groups for workflow-specific training
MODEL_GROUPS = {
    "omnichannel": ["conversion", "value", "demand", "fulfillment"],
    "inventory": ["stockout", "lead_time"],
    "engagement": ["churn", "campaign_response", "clv"],
}

ALL_MODELS = ["conversion", "value", "demand", "fulfillment",
              "stockout", "lead_time",
              "churn", "campaign_response", "clv"]


def get_scenario_ids(scenarios_arg: str) -> Optional[List[str]]:
    """Parse scenario IDs from command line argument."""
    if scenarios_arg == "all":
        return None  # Use all available scenarios

    return [s.strip() for s in scenarios_arg.split(",")]


def train_conversion_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the conversion model."""
    logger.info("Training Conversion Model...")

    model = ConversionModel()
    metrics = model.train(scenario_ids)

    # Save model
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"conversion_{timestamp}.joblib"
    model.save(str(model_path))

    # Also save as 'latest'
    latest_path = output_dir / "conversion_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "conversion",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


def train_value_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the value model."""
    logger.info("Training Value Model...")

    model = ValueModel()
    metrics = model.train(scenario_ids)

    # Save model
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"value_{timestamp}.joblib"
    model.save(str(model_path))

    # Also save as 'latest'
    latest_path = output_dir / "value_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "value",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


def train_demand_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the demand forecast model."""
    logger.info("Training Demand Forecast Model...")

    try:
        model = DemandForecastModel()
        metrics = model.train(scenario_ids)

        # Save model
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_path = output_dir / f"demand_{timestamp}.json"
        model.save(str(model_path))

        # Also save as 'latest'
        latest_path = output_dir / "demand_latest.json"
        model.save(str(latest_path))

        return {
            "model": "demand",
            "path": str(model_path),
            "metrics": metrics,
        }
    except ImportError as e:
        logger.warning(f"Skipping demand model: {e}")
        return {
            "model": "demand",
            "error": str(e),
            "skipped": True,
        }
    except ValueError as e:
        logger.warning(f"Skipping demand model: {e}")
        return {
            "model": "demand",
            "error": str(e),
            "skipped": True,
        }


def train_fulfillment_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the fulfillment model."""
    logger.info("Training Fulfillment Model...")

    model = FulfillmentModel()
    metrics = model.train(scenario_ids)

    # Save model
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"fulfillment_{timestamp}.joblib"
    model.save(str(model_path))

    # Also save as 'latest'
    latest_path = output_dir / "fulfillment_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "fulfillment",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


# ===== INVENTORY WORKFLOW MODELS =====

def train_stockout_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the stockout prediction model."""
    logger.info("Training Stockout Model...")

    model = StockoutModel()
    metrics = model.train(scenario_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"stockout_{timestamp}.joblib"
    model.save(str(model_path))

    latest_path = output_dir / "stockout_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "stockout",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


def train_lead_time_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the lead time prediction model."""
    logger.info("Training Lead Time Model...")

    model = LeadTimeModel()
    metrics = model.train(scenario_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"lead_time_{timestamp}.joblib"
    model.save(str(model_path))

    latest_path = output_dir / "lead_time_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "lead_time",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


# ===== ENGAGEMENT WORKFLOW MODELS =====

def train_churn_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the churn prediction model."""
    logger.info("Training Churn Model...")

    model = ChurnModel()
    metrics = model.train(scenario_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"churn_{timestamp}.joblib"
    model.save(str(model_path))

    latest_path = output_dir / "churn_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "churn",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


def train_campaign_response_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the campaign response model."""
    logger.info("Training Campaign Response Model...")

    model = CampaignResponseModel()
    metrics = model.train(scenario_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"campaign_response_{timestamp}.joblib"
    model.save(str(model_path))

    latest_path = output_dir / "campaign_response_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "campaign_response",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


def train_clv_model(
    scenario_ids: Optional[List[str]],
    output_dir: Path,
) -> dict:
    """Train and save the CLV prediction model."""
    logger.info("Training CLV Model...")

    model = CLVModel()
    metrics = model.train(scenario_ids)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = output_dir / f"clv_{timestamp}.joblib"
    model.save(str(model_path))

    latest_path = output_dir / "clv_latest.joblib"
    model.save(str(latest_path))

    return {
        "model": "clv",
        "path": str(model_path),
        "metrics": metrics,
        "feature_importance": model.get_feature_importance(),
    }


# Model training function map
TRAIN_FUNCTIONS = {
    "conversion": train_conversion_model,
    "value": train_value_model,
    "demand": train_demand_model,
    "fulfillment": train_fulfillment_model,
    "stockout": train_stockout_model,
    "lead_time": train_lead_time_model,
    "churn": train_churn_model,
    "campaign_response": train_campaign_response_model,
    "clv": train_clv_model,
}


def print_summary(results: List[dict]) -> None:
    """Print training summary."""
    print("\n" + "=" * 60)
    print("TRAINING SUMMARY")
    print("=" * 60)

    for result in results:
        model_name = result["model"]
        print(f"\n{model_name.upper()} MODEL")
        print("-" * 40)

        if result.get("skipped"):
            print(f"  Skipped: {result.get('error', 'Unknown reason')}")
            continue

        if result.get("error"):
            print(f"  Error: {result['error']}")
            continue

        print(f"  Path: {result['path']}")

        metrics = result.get("metrics", {})
        for key, value in metrics.items():
            if isinstance(value, float):
                if key.endswith("_samples"):
                    print(f"  {key}: {int(value)}")
                elif key in ["mae", "rmse", "mape"]:
                    print(f"  {key}: {value:.2f}")
                else:
                    print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")

        importance = result.get("feature_importance", {})
        if importance:
            print("  Feature Importance:")
            sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
            for feature, score in sorted_features[:5]:
                print(f"    {feature}: {score:.4f}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Train ML models on simulation data")

    parser.add_argument(
        "--scenarios",
        type=str,
        default="all",
        help="Comma-separated scenario IDs, or 'all' for all scenarios"
    )
    parser.add_argument(
        "--model",
        type=str,
        choices=ALL_MODELS + ["all"],
        default=None,
        help="Single model to train"
    )
    parser.add_argument(
        "--model-group",
        type=str,
        choices=["omnichannel", "inventory", "engagement", "all"],
        default=None,
        help="Train all models in a workflow group"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(MODELS_DIR),
        help="Output directory for models"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine which models to train
    models_to_train = []

    if args.model_group:
        if args.model_group == "all":
            models_to_train = ALL_MODELS
        else:
            models_to_train = MODEL_GROUPS.get(args.model_group, [])
    elif args.model:
        if args.model == "all":
            models_to_train = ALL_MODELS
        else:
            models_to_train = [args.model]
    else:
        # Default: train all models
        models_to_train = ALL_MODELS

    # Parse scenarios
    scenario_ids = get_scenario_ids(args.scenarios)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check data availability
    extractor = DataExtractor()
    stats = extractor.get_dataset_stats()
    extractor.close()

    print("\n" + "=" * 60)
    print("ML MODEL TRAINING")
    print("=" * 60)
    print(f"Scenarios: {args.scenarios}")
    print(f"Models: {', '.join(models_to_train)}")
    print(f"Output: {output_dir}")
    print("\nData Statistics:")
    print(f"  Scenarios: {stats['scenarios']['total']} ({stats['scenarios']['completed']} completed)")
    print(f"  Journeys: {stats['journeys']['total']} ({stats['journeys']['completed']} completed)")
    print(f"  Orders: {stats['orders']['total']}")
    print(f"  Hourly Demand: {stats['hourly_demand']['total']}")
    print("=" * 60)

    # Train models
    results = []

    for model_name in models_to_train:
        train_fn = TRAIN_FUNCTIONS.get(model_name)
        if train_fn:
            try:
                result = train_fn(scenario_ids, output_dir)
                results.append(result)
            except Exception as e:
                logger.error(f"{model_name} model training failed: {e}")
                results.append({"model": model_name, "error": str(e)})

    # Print summary
    print_summary(results)

    # Save training summary
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = output_dir / f"training_summary_{timestamp}.json"

    # Convert metrics to JSON-serializable format
    serializable_results = []
    for result in results:
        r = result.copy()
        if "metrics" in r:
            r["metrics"] = {k: float(v) if isinstance(v, (int, float)) else v
                          for k, v in r["metrics"].items()}
        if "feature_importance" in r:
            r["feature_importance"] = {k: float(v) for k, v in r["feature_importance"].items()}
        serializable_results.append(r)

    with open(summary_path, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "scenarios": args.scenarios,
            "models_trained": models_to_train,
            "results": serializable_results,
        }, f, indent=2)

    print(f"\nSummary saved to: {summary_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

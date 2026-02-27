"""
ML pipeline for simulation data analysis.

This module provides:
- Data extraction from simulation databases
- ML models for prediction and forecasting
- Training utilities

Supported workflows:
- Omnichannel: Conversion, Value, Demand, Fulfillment models
- Inventory: Stockout, Lead Time models
- Engagement: Churn, Campaign Response, CLV models
"""

from .data_prep import (
    DataExtractor,
    # Omnichannel
    get_conversion_dataset,
    get_order_value_dataset,
    get_demand_forecast_dataset,
    get_fulfillment_dataset,
    # Inventory
    get_stockout_dataset,
    get_lead_time_dataset,
    get_inventory_demand_dataset,
    # Engagement
    get_churn_dataset,
    get_campaign_response_dataset,
    get_clv_dataset,
)

# Omnichannel models
from .conversion_model import ConversionModel
from .value_model import ValueModel
from .demand_forecast import DemandForecastModel
from .fulfillment_model import FulfillmentModel

# Inventory models
from .stockout_model import StockoutModel
from .lead_time_model import LeadTimeModel

# Engagement models
from .churn_model import ChurnModel
from .campaign_response_model import CampaignResponseModel
from .clv_model import CLVModel

__all__ = [
    # Data extraction
    "DataExtractor",
    # Omnichannel datasets
    "get_conversion_dataset",
    "get_order_value_dataset",
    "get_demand_forecast_dataset",
    "get_fulfillment_dataset",
    # Inventory datasets
    "get_stockout_dataset",
    "get_lead_time_dataset",
    "get_inventory_demand_dataset",
    # Engagement datasets
    "get_churn_dataset",
    "get_campaign_response_dataset",
    "get_clv_dataset",
    # Omnichannel models
    "ConversionModel",
    "ValueModel",
    "DemandForecastModel",
    "FulfillmentModel",
    # Inventory models
    "StockoutModel",
    "LeadTimeModel",
    # Engagement models
    "ChurnModel",
    "CampaignResponseModel",
    "CLVModel",
]

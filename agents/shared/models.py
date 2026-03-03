"""Pydantic models for inter-agent data exchange."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────

class TabId(str, Enum):
    MAIN = "main"
    OMNICHANNEL = "omnichannel"
    CUSTOMER_ENGAGEMENT = "customer-engagement"
    INVENTORY_REPLENISHMENT = "inventory-replenishment"


class QuestionType(str, Enum):
    DRIVER_ANALYSIS = "driver_analysis"
    COMPARISON = "comparison"
    TREND = "trend"
    ANOMALY = "anomaly"
    GENERAL = "general"


class DecisionDomain(str, Enum):
    REVENUE = "revenue"
    OPERATIONS = "operations"
    CUSTOMER = "customer"
    INVENTORY = "inventory"
    CROSS_FUNCTIONAL = "cross_functional"


class TimeHorizon(str, Enum):
    IMMEDIATE = "immediate"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Agent 1 Models ────────────────────────────────────────────────

class IntentResult(BaseModel):
    """Output from the Intent classification agent."""
    tab: TabId
    metric_ids: list[str] = Field(default_factory=list)
    question_type: QuestionType = QuestionType.GENERAL
    original_question: str = ""
    clarified_question: str = ""


class DriverInfo(BaseModel):
    """A single metric driver with analysis."""
    name: str
    value: str
    contribution_pct: Optional[float] = None
    trend: str = "neutral"
    change_pct: Optional[float] = None
    explanation: str = ""


class PlannerResult(BaseModel):
    """Output from the Planner agent (Agent 1)."""
    metric_id: str = ""
    metric_label: str = ""
    current_value: str = ""
    previous_value: str = ""
    change_pct: Optional[float] = None
    drivers: list[DriverInfo] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)
    data_summary: str = ""


class ExplainerResponse(BaseModel):
    """Final formatted response from Agent 1."""
    headline: str
    explanation: str
    drivers: list[DriverInfo] = Field(default_factory=list)
    actionable_insight: str = ""
    word_count: int = 0


# ── Agent 2 Models ────────────────────────────────────────────────

class NarrativeIntentResult(BaseModel):
    """Output from the Narrative Intent classification agent."""
    decision_domain: DecisionDomain = DecisionDomain.CROSS_FUNCTIONAL
    time_horizon: TimeHorizon = TimeHorizon.SHORT_TERM
    urgency: Urgency = Urgency.MEDIUM
    sub_questions: list[str] = Field(default_factory=list)
    original_question: str = ""
    tabs_to_query: list[TabId] = Field(default_factory=list)


class NarrativePlannerResult(BaseModel):
    """Output from the Narrative Planner agent."""
    datasets: dict = Field(default_factory=dict)
    data_summary: str = ""
    metrics_gathered: list[str] = Field(default_factory=list)
    time_range: str = ""


class AnalysisResult(BaseModel):
    """Output from the Analyzer agent."""
    causal_chains: list[str] = Field(default_factory=list)
    correlations: list[str] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    reasoning: str = ""


class NarrativeResponse(BaseModel):
    """Final formatted response from Agent 2."""
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    narrative: str = ""


# ── API Request/Response Models ───────────────────────────────────

class ChatRequest(BaseModel):
    """Incoming chat request from the dashboard."""
    message: str
    active_tab: str = "main"
    current_view: str = "dashboard"
    selected_metric_id: Optional[str] = None
    session_id: str = ""


class ChatResponse(BaseModel):
    """Outgoing chat response to the dashboard."""
    response: str
    agent: str = ""
    metadata: dict = Field(default_factory=dict)


class NarrativeRequest(BaseModel):
    """Request for a business narrative."""
    message: str = "Generate a business narrative"
    session_id: str = ""
    focus_areas: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    agent: str = ""
    version: str = "0.1.0"

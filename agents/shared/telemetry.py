"""OpenTelemetry bootstrap for all agents.

Call ``configure_telemetry(app, service_name)`` once at startup.

Export target is chosen automatically:
  1. APPLICATIONINSIGHTS_CONNECTION_STRING → Azure Monitor exporter (cloud)
  2. OTEL_EXPORTER_OTLP_ENDPOINT → OTLP/gRPC to collector / Aspire (local)
  3. Neither → console exporter (bare-metal local dev)

Note: opentelemetry-sdk is pinned to <1.39.0 for compatibility with
azure-monitor-opentelemetry v1.8.2 (pulled by agent-framework).
Remove the pin once the distro ships a fix for the LogData import.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

_configured = False


def configure_telemetry(app: FastAPI, service_name: str) -> None:
    """Set up OTEL tracing, metrics, and log correlation for a FastAPI app.

    Never raises — telemetry failures are logged but do not crash the agent.
    """
    global _configured
    if _configured:
        return
    _configured = True

    try:
        _configure_telemetry_inner(app, service_name)
    except Exception:
        logger.exception("OpenTelemetry setup failed — continuing without telemetry")


def _configure_telemetry_inner(app: FastAPI, service_name: str) -> None:
    from .config import get_settings
    settings = get_settings()

    resource = Resource.create({SERVICE_NAME: service_name})

    # ── Determine exporters ──────────────────────────────────────
    conn_str = settings.applicationinsights_connection_string
    otlp_endpoint = settings.otel_exporter_otlp_endpoint

    if conn_str:
        # Cloud: export to Azure Monitor / Application Insights
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorTraceExporter,
            AzureMonitorMetricExporter,
        )
        span_exporter = AzureMonitorTraceExporter(connection_string=conn_str)
        metric_exporter = AzureMonitorMetricExporter(connection_string=conn_str)
        logger.info("OTEL → Azure Monitor (Application Insights)")
    elif otlp_endpoint:
        # Local: export to OTLP collector / Aspire dashboard
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
        logger.info("OTEL → OTLP endpoint %s", otlp_endpoint)
    else:
        # Fallback: console (useful for bare-metal dev without Docker)
        span_exporter = ConsoleSpanExporter()
        metric_exporter = ConsoleMetricExporter()
        logger.info("OTEL → console (no exporter configured)")

    # ── Traces ───────────────────────────────────────────────────
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # ── Metrics ──────────────────────────────────────────────────
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    # ── Auto-instrumentation ─────────────────────────────────────
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=True)

    logger.info("OpenTelemetry configured for %s", service_name)

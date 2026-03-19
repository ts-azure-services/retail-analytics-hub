/**
 * OpenTelemetry bootstrap for the Express dashboard server.
 *
 * Must be loaded before the app via --import flag:
 *   NODE_OPTIONS='--import ./server/tracing.js' tsx server/index.ts
 *
 * Export target is chosen automatically:
 *   1. APPLICATIONINSIGHTS_CONNECTION_STRING → Azure Monitor (cloud)
 *   2. OTEL_EXPORTER_OTLP_ENDPOINT → OTLP exporter (Aspire / collector)
 *   3. Neither → console exporter (bare-metal local dev)
 */

import { NodeSDK } from '@opentelemetry/sdk-node'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'
import { Resource } from '@opentelemetry/resources'
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions'
import { ConsoleSpanExporter, type SpanExporter } from '@opentelemetry/sdk-trace-node'
import {
  type MetricReader,
  ConsoleMetricExporter,
  PeriodicExportingMetricReader,
} from '@opentelemetry/sdk-metrics'

const serviceName = process.env.OTEL_SERVICE_NAME ?? 'dashboard'
const appInsightsConnStr = process.env.APPLICATIONINSIGHTS_CONNECTION_STRING ?? ''
const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? ''

let traceExporter: SpanExporter
let metricReader: MetricReader

if (appInsightsConnStr) {
  // Cloud: export to Azure Monitor / Application Insights
  const { AzureMonitorTraceExporter } = await import(
    '@azure/monitor-opentelemetry-exporter'
  )
  const { AzureMonitorMetricExporter } = await import(
    '@azure/monitor-opentelemetry-exporter'
  )
  traceExporter = new AzureMonitorTraceExporter({
    connectionString: appInsightsConnStr,
  }) as unknown as SpanExporter
  metricReader = new PeriodicExportingMetricReader({
    exporter: new AzureMonitorMetricExporter({
      connectionString: appInsightsConnStr,
    }) as any,
    exportIntervalMillis: 60_000,
  })
  console.log('[tracing] OTEL → Azure Monitor (Application Insights)')
} else if (otlpEndpoint) {
  // Local: export to OTLP collector / Aspire dashboard
  const { OTLPTraceExporter } = await import(
    '@opentelemetry/exporter-trace-otlp-grpc'
  )
  const { OTLPMetricExporter } = await import(
    '@opentelemetry/exporter-metrics-otlp-grpc'
  )
  traceExporter = new OTLPTraceExporter({ url: otlpEndpoint })
  metricReader = new PeriodicExportingMetricReader({
    exporter: new OTLPMetricExporter({ url: otlpEndpoint }),
    exportIntervalMillis: 60_000,
  })
  console.log(`[tracing] OTEL → OTLP endpoint ${otlpEndpoint}`)
} else {
  // Fallback: console
  traceExporter = new ConsoleSpanExporter()
  metricReader = new PeriodicExportingMetricReader({
    exporter: new ConsoleMetricExporter(),
    exportIntervalMillis: 60_000,
  })
  console.log('[tracing] OTEL → console (no exporter configured)')
}

const sdk = new NodeSDK({
  resource: new Resource({ [ATTR_SERVICE_NAME]: serviceName }),
  traceExporter,
  metricReader,
  instrumentations: [
    getNodeAutoInstrumentations({
      // Disable fs instrumentation to reduce noise
      '@opentelemetry/instrumentation-fs': { enabled: false },
    }),
  ],
})

sdk.start()

process.on('SIGTERM', () => {
  sdk.shutdown().then(
    () => console.log('[tracing] SDK shut down'),
    (err: unknown) => console.error('[tracing] SDK shutdown error', err),
  )
})

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

const serviceName = process.env.OTEL_SERVICE_NAME ?? 'dashboard'
const appInsightsConnStr = process.env.APPLICATIONINSIGHTS_CONNECTION_STRING ?? ''
const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT ?? ''

let traceExporter: SpanExporter

if (appInsightsConnStr) {
  // Cloud: export to Azure Monitor / Application Insights
  const { AzureMonitorTraceExporter } = await import(
    '@azure/monitor-opentelemetry-exporter'
  )
  traceExporter = new AzureMonitorTraceExporter({
    connectionString: appInsightsConnStr,
  }) as unknown as SpanExporter
  console.log('[tracing] OTEL → Azure Monitor (Application Insights)')
} else if (otlpEndpoint) {
  // Local: export to OTLP collector / Aspire dashboard
  const { OTLPTraceExporter } = await import(
    '@opentelemetry/exporter-trace-otlp-grpc'
  )
  traceExporter = new OTLPTraceExporter({ url: otlpEndpoint })
  console.log(`[tracing] OTEL → OTLP endpoint ${otlpEndpoint}`)
} else {
  // Fallback: console
  traceExporter = new ConsoleSpanExporter()
  console.log('[tracing] OTEL → console (no exporter configured)')
}

const sdk = new NodeSDK({
  resource: new Resource({ [ATTR_SERVICE_NAME]: serviceName }),
  traceExporter,
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

import express from 'express'
import cors from 'cors'
import path from 'path'
import { initDb, initReviewsDb, executeTabMetrics, executeReviewsQuery, closeDb, closeReviewsDb } from './query-executor.js'
import { validTabIds } from '../shared/metric-queries.js'

const PORT = Number(process.env.DASHBOARD_API_PORT ?? 3001)
const DB_PATH = process.env.LOCAL_POSTGRES_DB ?? path.resolve(import.meta.dirname, '../../local_postgres.duckdb')
const REVIEWS_DB_PATH = process.env.EVENT_HUBS_DB ?? path.resolve(import.meta.dirname, '../../event_hubs.duckdb')
const AGENT3_URL = process.env.AGENT3_URL ?? 'http://localhost:8003'
const AGENT2_URL = process.env.AGENT2_URL ?? 'http://localhost:8002'

let cachedDigest: { narrative: string; summary: string; key_findings: string[]; recommendations: string[]; risk_flags: string[]; generated_at: string } | null = null
let digestGenerating = false

const app = express()

const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS
app.use(
  cors({
    origin: ALLOWED_ORIGINS
      ? ALLOWED_ORIGINS.split(',').map((o) => o.trim())
      : /^https?:\/\/localhost(:\d+)?$/,
  })
)
app.use(express.json())

app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok' })
})

app.get('/api/metrics/:tab', async (req, res) => {
  const { tab } = req.params
  if (!validTabIds.includes(tab as any)) {
    res.status(400).json({ error: `Invalid tab: ${tab}` })
    return
  }
  try {
    const results = await executeTabMetrics(tab)
    res.json(results)
  } catch (err: unknown) {
    console.error('[server] query error:', err)
    res.status(500).json({ error: 'Query execution failed' })
  }
})

app.get('/api/reviews', async (req, res) => {
  const filter = (req.query.filter as string) || 'all'
  try {
    const rows = await executeReviewsQuery(filter)
    res.json(rows)
  } catch (err: unknown) {
    console.error('[server] reviews query error:', err)
    res.status(500).json({ error: 'Reviews query failed' })
  }
})

app.get('/api/digest', (_req, res) => {
  if (cachedDigest) {
    res.json({ status: 'ready', ...cachedDigest })
  } else if (digestGenerating) {
    res.json({ status: 'generating' })
  } else {
    res.json({ status: 'none' })
  }
})

async function triggerAgent2() {
  try {
    digestGenerating = true
    console.log(`[server] Triggering Agent 2 at ${AGENT2_URL}/narrative ...`)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 300_000) // 5 min
    const res = await fetch(`${AGENT2_URL}/narrative`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: 'Generate a comprehensive business narrative covering revenue, operations, customer engagement, and inventory health.',
        session_id: `digest-startup-${Date.now()}`,
        focus_areas: ['revenue', 'operations', 'customer', 'inventory'],
      }),
      signal: controller.signal,
    })
    clearTimeout(timeout)
    if (res.ok) {
      const data = await res.json()
      cachedDigest = {
        narrative: data.narrative || data.summary || '',
        summary: data.summary || '',
        key_findings: data.key_findings || [],
        recommendations: data.recommendations || [],
        risk_flags: data.risk_flags || [],
        generated_at: new Date().toISOString(),
      }
      console.log('[server] Agent 2 digest pre-generated and cached')
    } else {
      console.warn(`[server] Agent 2 returned status ${res.status}`)
    }
  } catch {
    console.warn('[server] Agent 2 not reachable — digest will be generated on demand')
  } finally {
    digestGenerating = false
  }
}

async function triggerAgent3() {
  try {
    console.log(`[server] Triggering Agent 3 at ${AGENT3_URL}/retry ...`)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10_000)
    const res = await fetch(`${AGENT3_URL}/retry`, {
      method: 'POST',
      signal: controller.signal,
    })
    clearTimeout(timeout)
    if (res.ok) {
      const data = await res.json()
      console.log(`[server] Agent 3 triggered — total: ${data.total}, succeeded: ${data.succeeded}, failed: ${data.failed}`)
    } else {
      console.warn(`[server] Agent 3 returned status ${res.status}`)
    }
  } catch {
    console.warn('[server] Agent 3 not reachable — reviews will be processed when the agent comes online')
  }
}

async function start() {
  console.log(`[server] DB path: ${DB_PATH}`)
  await initDb(DB_PATH)
  try {
    await initReviewsDb(REVIEWS_DB_PATH)
  } catch (err) {
    console.warn(`[server] Reviews DB not available at ${REVIEWS_DB_PATH} — customer-reviews tab will use seed data only`)
  }

  // Serve static frontend in production
  if (process.env.NODE_ENV === 'production') {
    const staticDir = path.resolve(import.meta.dirname, '.')
    app.use(express.static(staticDir))
    app.get('/*any', (_req, res) => {
      res.sendFile(path.join(staticDir, 'index.html'))
    })
  }

  app.listen(PORT, () => {
    console.log(`[server] Listening on http://localhost:${PORT}`)
  })

  // Fire-and-forget: trigger Agent 3 to process pending reviews on startup
  triggerAgent3()

  // Fire-and-forget: trigger Agent 2 to pre-generate digest on startup
  triggerAgent2()
}

process.on('SIGINT', async () => {
  await closeDb()
  await closeReviewsDb()
  process.exit(0)
})

start().catch((err) => {
  console.error('[server] Failed to start:', err)
  process.exit(1)
})

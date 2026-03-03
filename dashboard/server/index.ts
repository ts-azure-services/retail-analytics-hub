import express from 'express'
import cors from 'cors'
import path from 'path'
import { initDb, executeTabMetrics, closeDb } from './query-executor.js'
import { validTabIds } from '../shared/metric-queries.js'

const PORT = Number(process.env.DASHBOARD_API_PORT ?? 3001)
const DB_PATH = process.env.LOCAL_POSTGRES_DB ?? path.resolve(import.meta.dirname, '../../local_postgres.duckdb')

const app = express()

app.use(cors({ origin: /^https?:\/\/localhost(:\d+)?$/ }))
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

async function start() {
  console.log(`[server] DB path: ${DB_PATH}`)
  await initDb(DB_PATH)
  app.listen(PORT, () => {
    console.log(`[server] Listening on http://localhost:${PORT}`)
  })
}

process.on('SIGINT', async () => {
  await closeDb()
  process.exit(0)
})

start().catch((err) => {
  console.error('[server] Failed to start:', err)
  process.exit(1)
})

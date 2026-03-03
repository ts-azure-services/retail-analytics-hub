import { Database } from 'duckdb-async'
import { getQueriesForTab } from '../shared/metric-queries.js'

export interface MetricResult {
  metricId: string
  value: number | null
  error?: string
}

let db: Database | null = null

export async function initDb(dbPath: string): Promise<void> {
  db = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
  console.log(`[query-executor] Opened ${dbPath} (read-only)`)
}

export async function closeDb(): Promise<void> {
  if (db) {
    await db.close()
    db = null
  }
}

export async function executeTabMetrics(tabId: string): Promise<MetricResult[]> {
  if (!db) throw new Error('Database not initialised')

  const queries = getQueriesForTab(tabId)
  if (queries.length === 0) return []

  const conn = await db.connect()
  try {
    const results = await Promise.allSettled(
      queries.map(async (q): Promise<MetricResult> => {
        try {
          const rows = await conn.all(q.sql)
          const raw = rows[0]?.value
          const value = raw == null ? null : Number(raw)
          return { metricId: q.id, value: Number.isFinite(value!) ? value : null }
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err)
          console.error(`[query-executor] ${q.id}: ${msg}`)
          return { metricId: q.id, value: null, error: msg }
        }
      })
    )

    return results.map((r) =>
      r.status === 'fulfilled'
        ? r.value
        : { metricId: 'unknown', value: null, error: String((r as PromiseRejectedResult).reason) }
    )
  } finally {
    await conn.close()
  }
}

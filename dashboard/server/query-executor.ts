import { Database } from 'duckdb-async'
import pg from 'pg'
import { getQueriesForTab } from '../shared/metric-queries.js'

const FABRIC_SQL_ENDPOINT = process.env.FABRIC_SQL_ENDPOINT || ''

export interface MetricResult {
  metricId: string
  value: number | null
  error?: string
}

// ── DuckDB state (local) ────────────────────────────────────────
let db: Database | null = null
let reviewsDb: Database | null = null

// ── Postgres pool (Fabric cloud) ────────────────────────────────
let pgPool: pg.Pool | null = null

export async function initDb(dbPath: string): Promise<void> {
  if (FABRIC_SQL_ENDPOINT) {
    if (!pgPool) {
      pgPool = new pg.Pool({ connectionString: FABRIC_SQL_ENDPOINT })
      console.log('[query-executor] Connected to Fabric SQL endpoint')
    }
    return
  }
  db = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
  console.log(`[query-executor] Opened ${dbPath} (read-only)`)
}

export async function initReviewsDb(dbPath: string): Promise<void> {
  // Always use DuckDB for reviews — even in cloud mode the reviews DB is
  // bundled in the container (KQL-sourced data, not in Fabric SQL endpoint).
  reviewsDb = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
  console.log(`[query-executor] Opened reviews DB ${dbPath} (read-only)`)
}

export async function closeDb(): Promise<void> {
  if (pgPool) {
    await pgPool.end()
    pgPool = null
  }
  if (db) {
    await db.close()
    db = null
  }
}

export async function closeReviewsDb(): Promise<void> {
  if (reviewsDb) {
    await reviewsDb.close()
    reviewsDb = null
  }
}

/** Run a single SQL query via the active driver. */
async function queryRows(sql: string, useReviewsDb = false): Promise<Record<string, unknown>[]> {
  // Reviews always use the bundled DuckDB (even in cloud mode)
  if (useReviewsDb) {
    if (!reviewsDb) throw new Error('Reviews database not initialised')
    const conn = await reviewsDb.connect()
    try {
      return (await conn.all(sql)) as Record<string, unknown>[]
    } finally {
      await conn.close()
    }
  }
  if (pgPool) {
    const { rows } = await pgPool.query(sql)
    return rows
  }
  if (!db) throw new Error('Database not initialised')
  const conn = await db.connect()
  try {
    return (await conn.all(sql)) as Record<string, unknown>[]
  } finally {
    await conn.close()
  }
}

export async function executeTabMetrics(tabId: string): Promise<MetricResult[]> {
  const queries = getQueriesForTab(tabId)
  if (queries.length === 0) return []

  const isReviews = tabId === 'customer-reviews'
  if (!pgPool && !(isReviews ? reviewsDb : db)) throw new Error('Database not initialised')

  const results = await Promise.allSettled(
    queries.map(async (q): Promise<MetricResult> => {
      try {
        const rows = await queryRows(q.sql, isReviews)
        const raw = (rows[0] as any)?.value
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
}

export interface ReviewRecord {
  id: number
  review_text: string
  sentiment_category: string | null
  sentiment_score: number | null
  status: string
  chatbot_statement: string | null
  created_at: string | null
  processed_at: string | null
}

export async function executeReviewsQuery(filter: string): Promise<ReviewRecord[]> {
  if (!pgPool && !reviewsDb) throw new Error('Reviews database not initialised')

  let sql = `SELECT id, review_text, sentiment_category, sentiment_score,
                    status, chatbot_statement, created_at, processed_at
             FROM customer_reviews`

  if (filter === 'positive') {
    sql += ` WHERE sentiment_category IN ('positive', 'very_positive')`
  } else if (filter === 'negative') {
    sql += ` WHERE sentiment_category IN ('negative', 'very_negative')`
  } else if (filter === 'needs_review') {
    sql += ` WHERE status = 'Needing human review'`
  }

  sql += ` ORDER BY id DESC LIMIT 200`

  return (await queryRows(sql, true)) as ReviewRecord[]
}

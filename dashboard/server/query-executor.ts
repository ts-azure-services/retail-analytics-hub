import { Database } from 'duckdb-async'
import { getQueriesForTab } from '../shared/metric-queries.js'

export interface MetricResult {
  metricId: string
  value: number | null
  error?: string
}

let db: Database | null = null
let reviewsDb: Database | null = null

export async function initDb(dbPath: string): Promise<void> {
  db = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
  console.log(`[query-executor] Opened ${dbPath} (read-only)`)
}

export async function initReviewsDb(dbPath: string): Promise<void> {
  reviewsDb = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
  console.log(`[query-executor] Opened reviews DB ${dbPath} (read-only)`)
}

export async function closeDb(): Promise<void> {
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

export async function executeTabMetrics(tabId: string): Promise<MetricResult[]> {
  const activeDb = tabId === 'customer-reviews' ? reviewsDb : db
  if (!activeDb) throw new Error('Database not initialised')

  const queries = getQueriesForTab(tabId)
  if (queries.length === 0) return []

  const conn = await activeDb.connect()
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
  if (!reviewsDb) throw new Error('Reviews database not initialised')

  const conn = await reviewsDb.connect()
  try {
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

    const rows = await conn.all(sql)
    return rows as ReviewRecord[]
  } finally {
    await conn.close()
  }
}

import { Database } from 'duckdb-async'
import pg from 'pg'
import { getQueriesForTab, type SqlDialect } from '../shared/metric-queries.js'

const FABRIC_SQL_ENDPOINT = process.env.FABRIC_SQL_ENDPOINT || ''
const FABRIC_KQL_CLUSTER_URI = process.env.FABRIC_KQL_CLUSTER_URI || ''
const FABRIC_KQL_DATABASE = process.env.FABRIC_KQL_DATABASE || ''
const FABRIC_KQL_TABLE = process.env.FABRIC_KQL_TABLE || 'CustomerReviews'

/** Active SQL dialect: mssql when Fabric SQL endpoint is configured. */
const dialect: SqlDialect = FABRIC_SQL_ENDPOINT ? 'mssql' : 'postgres'

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

// ── KQL client (Fabric RTI for reviews) ─────────────────────────
let kustoClient: any = null

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
  if (FABRIC_KQL_CLUSTER_URI) {
    // KQL mode — connect to Fabric Real-Time Intelligence
    try {
      const { DefaultAzureCredential } = await import('@azure/identity')
      const { KustoClient, KustoConnectionStringBuilder } = await import('azure-kusto-data')
      const credential = new DefaultAzureCredential()
      const kcsb = KustoConnectionStringBuilder.withAadManagedIdentities(FABRIC_KQL_CLUSTER_URI)
      kustoClient = new KustoClient(kcsb)
      console.log(`[query-executor] Connected to KQL: ${FABRIC_KQL_CLUSTER_URI} / ${FABRIC_KQL_DATABASE}`)
    } catch (err) {
      console.warn('[query-executor] KQL client init failed, falling back to DuckDB:', err)
      reviewsDb = await Database.create(dbPath, { access_mode: 'READ_ONLY' })
    }
    return
  }
  // Local mode — use DuckDB
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
  if (kustoClient) {
    kustoClient = null
  }
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

/** Run a KQL query against the Fabric KQL database. */
async function queryKql(kql: string): Promise<Record<string, unknown>[]> {
  if (!kustoClient) throw new Error('KQL client not initialised')
  const response = await kustoClient.execute(FABRIC_KQL_DATABASE, kql)
  const table = response.primaryResults[0]
  const columns = table.columns.map((c: any) => c.name)
  const rows: Record<string, unknown>[] = []
  for (const row of table.rows()) {
    const obj: Record<string, unknown> = {}
    for (const col of columns) {
      obj[col] = row[col]
    }
    rows.push(obj)
  }
  return rows
}

export async function executeTabMetrics(tabId: string): Promise<MetricResult[]> {
  // Customer reviews in cloud mode → use KQL
  if (tabId === 'customer-reviews' && kustoClient) {
    return executeReviewsMetricsViaKql()
  }

  const queries = getQueriesForTab(tabId, dialect)
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

/** Execute customer reviews metrics via KQL. */
async function executeReviewsMetricsViaKql(): Promise<MetricResult[]> {
  const table = FABRIC_KQL_TABLE

  const kqlQueries: { id: string; kql: string }[] = [
    { id: 'cr-total-reviews', kql: `${table} | count | project value = Count` },
    {
      id: 'cr-positive-pct',
      kql: `${table} | summarize total = count(), pos = countif(sentiment_category in ('positive', 'very_positive')) | project value = pos * 100.0 / total`,
    },
    {
      id: 'cr-negative-pct',
      kql: `${table} | summarize total = count(), neg = countif(sentiment_category in ('negative', 'very_negative')) | project value = neg * 100.0 / total`,
    },
    {
      id: 'cr-avg-score',
      kql: `${table} | where isnotnull(sentiment_score) | summarize value = avg(sentiment_score)`,
    },
    {
      id: 'cr-needs-review',
      kql: `${table} | where status == 'Needing human review' | count | project value = Count`,
    },
    {
      id: 'cr-processed-pct',
      kql: `${table} | summarize total = count(), processed = countif(status == 'processed for response') | project value = processed * 100.0 / total`,
    },
  ]

  const results = await Promise.allSettled(
    kqlQueries.map(async (q): Promise<MetricResult> => {
      try {
        const rows = await queryKql(q.kql)
        const raw = (rows[0] as any)?.value
        const value = raw == null ? null : Number(raw)
        return { metricId: q.id, value: Number.isFinite(value!) ? value : null }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        console.error(`[query-executor] KQL ${q.id}: ${msg}`)
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
  // KQL mode
  if (kustoClient) {
    return executeReviewsQueryViaKql(filter)
  }

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

/** Execute reviews list query via KQL. */
async function executeReviewsQueryViaKql(filter: string): Promise<ReviewRecord[]> {
  const table = FABRIC_KQL_TABLE
  let kql = `${table} | project id, review_text, sentiment_category, sentiment_score, status, chatbot_statement, created_at, processed_at`

  if (filter === 'positive') {
    kql += ` | where sentiment_category in ('positive', 'very_positive')`
  } else if (filter === 'negative') {
    kql += ` | where sentiment_category in ('negative', 'very_negative')`
  } else if (filter === 'needs_review') {
    kql += ` | where status == 'Needing human review'`
  }

  kql += ` | sort by id desc | take 200`

  return (await queryKql(kql)) as ReviewRecord[]
}

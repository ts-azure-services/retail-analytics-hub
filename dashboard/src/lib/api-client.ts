export interface MetricResultDTO {
  metricId: string
  value: number | null
  error?: string
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

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:3001'

export async function fetchTabMetrics(tabId: string): Promise<MetricResultDTO[]> {
  const res = await fetch(`${API_BASE}/api/metrics/${encodeURIComponent(tabId)}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export async function fetchReviewRecords(filter: 'all' | 'positive' | 'negative' = 'all'): Promise<ReviewRecord[]> {
  const res = await fetch(`${API_BASE}/api/reviews?filter=${encodeURIComponent(filter)}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export interface DigestResult {
  status: 'ready' | 'generating' | 'none'
  narrative?: string
  summary?: string
  key_findings?: string[]
  recommendations?: string[]
  risk_flags?: string[]
  generated_at?: string
}

export async function fetchDigest(): Promise<DigestResult> {
  const res = await fetch(`${API_BASE}/api/digest`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

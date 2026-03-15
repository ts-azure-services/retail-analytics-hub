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

export async function fetchReviewRecords(filter: 'all' | 'positive' | 'negative' | 'needs_review' = 'all'): Promise<ReviewRecord[]> {
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

// ── SSE streaming chat ──────────────────────────────────────────

export interface SSECallbacks {
  onStatus?: (message: string) => void
  onChunk?: (text: string) => void
  onDone?: (data: { response: string; agent: string; metadata: Record<string, unknown> }) => void
  onError?: (message: string) => void
}

/**
 * Call the Agent 1 streaming endpoint and invoke callbacks for each SSE event.
 * Returns the full response text on success, or null if streaming fails.
 */
export async function streamChat(
  body: Record<string, unknown>,
  callbacks: SSECallbacks,
  signal?: AbortSignal,
): Promise<string | null> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok || !res.body) return null

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let fullResponse = ''
  let currentEvent = ''
  let dataBuffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const text = decoder.decode(value, { stream: true })
    const lines = text.split('\n')

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataBuffer += line.slice(6)
      } else if (line === '' && dataBuffer) {
        // Empty line = end of SSE message
        const data = dataBuffer
        dataBuffer = ''

        switch (currentEvent) {
          case 'status': {
            try {
              const parsed = JSON.parse(data)
              callbacks.onStatus?.(parsed.message || data)
            } catch {
              callbacks.onStatus?.(data)
            }
            break
          }
          case 'chunk': {
            fullResponse += (fullResponse ? ' ' : '') + data
            callbacks.onChunk?.(fullResponse)
            break
          }
          case 'done': {
            try {
              const parsed = JSON.parse(data)
              callbacks.onDone?.(parsed)
              fullResponse = parsed.response || fullResponse
            } catch {
              callbacks.onDone?.({ response: fullResponse, agent: 'explainer', metadata: {} })
            }
            break
          }
          case 'error': {
            try {
              const parsed = JSON.parse(data)
              callbacks.onError?.(parsed.message || data)
            } catch {
              callbacks.onError?.(data)
            }
            break
          }
        }
        currentEvent = ''
      }
    }
  }

  return fullResponse || null
}

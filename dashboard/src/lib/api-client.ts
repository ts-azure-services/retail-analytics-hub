export interface MetricResultDTO {
  metricId: string
  value: number | null
  error?: string
}

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:3001'

export async function fetchTabMetrics(tabId: string): Promise<MetricResultDTO[]> {
  const res = await fetch(`${API_BASE}/api/metrics/${encodeURIComponent(tabId)}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json()
}

export interface MetricData {
  id: string
  label: string
  value: number
  previousValue: number
  unit: string
  format: 'number' | 'currency' | 'percentage'
  trend: 'up' | 'down' | 'neutral'
  changePercent: number
  icon: string
  invertTrend?: boolean
  sparklineData?: number[]
  forecast?: {
    value: number
    variance: number
    variancePercent: number
  }
}

export interface MetricDriver {
  id: string
  label: string
  value: number
  contribution: number
  trend: 'up' | 'down' | 'neutral'
  changePercent: number
  description: string
  format: 'number' | 'currency' | 'percentage'
}

export interface MetricBreakdown {
  metricId: string
  drivers: MetricDriver[]
  insights: string[]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export interface DashboardConfig {
  visibleMetrics: string[]
  refreshInterval: number
}

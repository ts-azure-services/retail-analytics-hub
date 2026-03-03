import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchTabMetrics, MetricResultDTO } from '../lib/api-client'
import { MetricData } from '../lib/types'
import {
  generateMockMetrics,
  generateOmnichannelMetrics,
  generateCustomerEngagementMetrics,
  generateInventoryReplenishmentMetrics,
} from '../lib/metric-registry'

type TabId = 'main' | 'omnichannel' | 'customer-engagement' | 'inventory-replenishment'

function getSeedMetrics(tabId: TabId): MetricData[] {
  switch (tabId) {
    case 'main': return generateMockMetrics()
    case 'omnichannel': return generateOmnichannelMetrics()
    case 'customer-engagement': return generateCustomerEngagementMetrics()
    case 'inventory-replenishment': return generateInventoryReplenishmentMetrics()
  }
}

function generateSparkline(prev: number, cur: number): number[] {
  return Array.from({ length: 20 }, (_, i) => {
    const progress = i / 19
    const variation = Math.sin(i * 0.5) * 0.1
    return prev + (cur - prev) * progress + variation * cur
  })
}

export function useTabMetrics(tabId: TabId, refreshInterval = 30_000) {
  const prevValuesRef = useRef<Map<string, number>>(new Map())
  const seedMetrics = useRef(getSeedMetrics(tabId)).current

  const { data, isError, isLoading } = useQuery<MetricResultDTO[]>({
    queryKey: ['metrics', tabId],
    queryFn: () => fetchTabMetrics(tabId),
    refetchInterval: refreshInterval,
    retry: 1,
    staleTime: refreshInterval / 2,
  })

  // Merge API results into seed data
  const metrics: MetricData[] = seedMetrics.map((seed) => {
    if (!data || isError) return seed

    const result = data.find((r) => r.metricId === seed.id)
    if (!result || result.value == null) return seed

    const prevMap = prevValuesRef.current
    const previousValue = prevMap.get(seed.id) ?? seed.previousValue
    prevMap.set(seed.id, result.value)

    const changePercent =
      previousValue !== 0
        ? Math.abs(((result.value - previousValue) / previousValue) * 100)
        : 0
    const trend: 'up' | 'down' | 'neutral' =
      result.value > previousValue ? 'up' : result.value < previousValue ? 'down' : 'neutral'

    return {
      ...seed,
      value: result.value,
      previousValue,
      trend,
      changePercent,
      sparklineData: generateSparkline(previousValue, result.value),
    }
  })

  return { metrics, isLoading, isError }
}

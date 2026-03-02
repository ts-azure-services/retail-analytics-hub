import { MetricData, MetricBreakdown } from './types'

export function generateMockMetrics(): MetricData[] {
  const baseMetrics = [
    {
      id: 'revenue',
      label: 'Total Revenue',
      value: 284750,
      previousValue: 267200,
      unit: '$',
      format: 'currency' as const,
      icon: 'currency',
    },
    {
      id: 'orders',
      label: 'Orders Today',
      value: 1847,
      previousValue: 1923,
      unit: '',
      format: 'number' as const,
      icon: 'shopping',
      forecast: {
        value: 1950,
        variance: 103,
        variancePercent: 5.58,
      },
    },
    {
      id: 'conversion',
      label: 'Conversion Rate',
      value: 3.42,
      previousValue: 3.21,
      unit: '%',
      format: 'percentage' as const,
      icon: 'trend',
    },
    {
      id: 'customers',
      label: 'Active Customers',
      value: 54012,
      previousValue: 52890,
      unit: '',
      format: 'number' as const,
      icon: 'users',
    },
    {
      id: 'avgOrder',
      label: 'Avg Order Value',
      value: 154.23,
      previousValue: 138.95,
      unit: '$',
      format: 'currency' as const,
      icon: 'cart',
    },
    {
      id: 'inventory',
      label: 'Low Stock Items',
      value: 23,
      previousValue: 18,
      unit: '',
      format: 'number' as const,
      icon: 'warning',
    },
    {
      id: 'traffic',
      label: 'Website Traffic',
      value: 128340,
      previousValue: 121500,
      unit: '',
      format: 'number' as const,
      icon: 'globe',
    },
    {
      id: 'returns',
      label: 'Return Rate',
      value: 2.8,
      previousValue: 3.1,
      unit: '%',
      format: 'percentage' as const,
      icon: 'package',
    },
  ]

  return baseMetrics.map((metric) => {
    const changePercent = ((metric.value - metric.previousValue) / metric.previousValue) * 100
    const trend = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'neutral'
    
    const sparklineData = Array.from({ length: 20 }, (_, i) => {
      const progress = i / 19
      const variation = Math.sin(i * 0.5) * 0.1
      return metric.previousValue + (metric.value - metric.previousValue) * progress + variation * metric.value
    })

    return {
      ...metric,
      trend,
      changePercent: Math.abs(changePercent),
      sparklineData,
    }
  })
}

export function simulateMetricUpdate(metrics: MetricData[]): MetricData[] {
  return metrics.map((metric) => {
    const variance = 0.02
    const change = 1 + (Math.random() - 0.5) * variance
    const newValue = Math.max(0, metric.value * change)
    const previousValue = metric.value

    const changePercent = ((newValue - previousValue) / previousValue) * 100
    const trend = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'neutral'

    const newSparklineData = [...(metric.sparklineData || []).slice(1), newValue]

    return {
      ...metric,
      value: newValue,
      previousValue,
      trend,
      changePercent: Math.abs(changePercent),
      sparklineData: newSparklineData,
    }
  })
}

export function generateMetricBreakdown(metricId: string): MetricBreakdown {
  const breakdowns: Record<string, MetricBreakdown> = {
    revenue: {
      metricId: 'revenue',
      drivers: [
        {
          id: 'online-sales',
          label: 'Online Sales',
          value: 187340,
          contribution: 65.8,
          trend: 'up',
          changePercent: 8.4,
          description: 'Direct e-commerce transactions',
          format: 'currency',
        },
        {
          id: 'in-store',
          label: 'In-Store Sales',
          value: 68200,
          contribution: 23.9,
          trend: 'down',
          changePercent: 2.1,
          description: 'Physical retail locations',
          format: 'currency',
        },
        {
          id: 'wholesale',
          label: 'Wholesale',
          value: 29210,
          contribution: 10.3,
          trend: 'up',
          changePercent: 12.3,
          description: 'B2B wholesale orders',
          format: 'currency',
        },
      ],
      insights: [
        'Online sales driving 66% of total revenue with strong growth',
        'In-store experiencing slight decline, may need promotional boost',
        'Wholesale showing exceptional growth at 12.3%',
      ],
    },
    orders: {
      metricId: 'orders',
      drivers: [
        {
          id: 'new-customers',
          label: 'New Customers',
          value: 643,
          contribution: 34.8,
          trend: 'up',
          changePercent: 5.2,
          description: 'First-time purchasers',
          format: 'number',
        },
        {
          id: 'returning',
          label: 'Returning Customers',
          value: 1089,
          contribution: 59.0,
          trend: 'down',
          changePercent: 4.8,
          description: 'Repeat purchases',
          format: 'number',
        },
        {
          id: 'mobile-orders',
          label: 'Mobile Orders',
          value: 115,
          contribution: 6.2,
          trend: 'up',
          changePercent: 18.7,
          description: 'Orders via mobile app',
          format: 'number',
        },
      ],
      insights: [
        'Returning customers make up 59% of orders, showing strong loyalty',
        'Mobile orders growing rapidly at 18.7%, invest in app experience',
        'New customer acquisition steady with 5.2% growth',
      ],
    },
    conversion: {
      metricId: 'conversion',
      drivers: [
        {
          id: 'product-page',
          label: 'Product Page',
          value: 4.2,
          contribution: 38.5,
          trend: 'up',
          changePercent: 6.8,
          description: 'Users who viewed products',
          format: 'percentage',
        },
        {
          id: 'cart-conversion',
          label: 'Cart to Checkout',
          value: 2.9,
          contribution: 28.3,
          trend: 'up',
          changePercent: 4.2,
          description: 'Cart abandonment recovery',
          format: 'percentage',
        },
        {
          id: 'landing-page',
          label: 'Landing Page',
          value: 3.6,
          contribution: 33.2,
          trend: 'neutral',
          changePercent: 0.8,
          description: 'Campaign landing pages',
          format: 'percentage',
        },
      ],
      insights: [
        'Product pages converting strongly with 6.8% improvement',
        'Cart-to-checkout flow optimized, reduced abandonment',
        'Landing pages stable, consider A/B testing new variants',
      ],
    },
    customers: {
      metricId: 'customers',
      drivers: [
        {
          id: 'email-subscribers',
          label: 'Email Subscribers',
          value: 28900,
          contribution: 53.5,
          trend: 'up',
          changePercent: 3.2,
          description: 'Active email list members',
          format: 'number',
        },
        {
          id: 'social-followers',
          label: 'Social Media',
          value: 18340,
          contribution: 34.0,
          trend: 'up',
          changePercent: 8.9,
          description: 'Instagram and Facebook followers',
          format: 'number',
        },
        {
          id: 'loyalty-members',
          label: 'Loyalty Program',
          value: 6772,
          contribution: 12.5,
          trend: 'up',
          changePercent: 2.1,
          description: 'Enrolled loyalty members',
          format: 'number',
        },
      ],
      insights: [
        'Social media growing fastest at 8.9%, strong engagement',
        'Email list remains largest customer touchpoint at 53.5%',
        'Loyalty program steady, consider gamification features',
      ],
    },
    avgOrder: {
      metricId: 'avgOrder',
      drivers: [
        {
          id: 'upsells',
          label: 'Upsell Revenue',
          value: 42.80,
          contribution: 27.8,
          trend: 'up',
          changePercent: 15.2,
          description: 'Additional items added',
          format: 'currency',
        },
        {
          id: 'base-price',
          label: 'Base Product',
          value: 89.60,
          contribution: 58.1,
          trend: 'up',
          changePercent: 3.8,
          description: 'Primary product value',
          format: 'currency',
        },
        {
          id: 'shipping',
          label: 'Shipping & Fees',
          value: 21.83,
          contribution: 14.1,
          trend: 'up',
          changePercent: 1.2,
          description: 'Delivery and handling',
          format: 'currency',
        },
      ],
      insights: [
        'Upsells performing exceptionally well with 15.2% growth',
        'Base product prices steady with healthy 3.8% increase',
        'Consider free shipping threshold to boost order values',
      ],
    },
    inventory: {
      metricId: 'inventory',
      drivers: [
        {
          id: 'seasonal',
          label: 'Seasonal Items',
          value: 11,
          contribution: 47.8,
          trend: 'up',
          changePercent: 22.2,
          description: 'End of season clearance',
          format: 'number',
        },
        {
          id: 'bestsellers',
          label: 'Best Sellers',
          value: 8,
          contribution: 34.8,
          trend: 'up',
          changePercent: 14.3,
          description: 'High-demand SKUs',
          format: 'number',
        },
        {
          id: 'new-arrivals',
          label: 'New Arrivals',
          value: 4,
          contribution: 17.4,
          trend: 'neutral',
          changePercent: 0.0,
          description: 'Recently launched products',
          format: 'number',
        },
      ],
      insights: [
        'Seasonal items need immediate restocking, high demand',
        'Best sellers running low, prioritize replenishment',
        'New arrivals stable, monitor for demand spikes',
      ],
    },
    traffic: {
      metricId: 'traffic',
      drivers: [
        {
          id: 'organic',
          label: 'Organic Search',
          value: 52890,
          contribution: 41.2,
          trend: 'up',
          changePercent: 7.8,
          description: 'Google and search engines',
          format: 'number',
        },
        {
          id: 'social',
          label: 'Social Media',
          value: 38502,
          contribution: 30.0,
          trend: 'up',
          changePercent: 12.4,
          description: 'Instagram, Facebook, TikTok',
          format: 'number',
        },
        {
          id: 'direct',
          label: 'Direct Traffic',
          value: 25660,
          contribution: 20.0,
          trend: 'up',
          changePercent: 3.2,
          description: 'Direct URL visits',
          format: 'number',
        },
        {
          id: 'paid',
          label: 'Paid Ads',
          value: 11288,
          contribution: 8.8,
          trend: 'up',
          changePercent: 5.6,
          description: 'Google Ads and sponsored',
          format: 'number',
        },
      ],
      insights: [
        'Social media traffic surging with 12.4% growth, highest of all channels',
        'Organic search remains dominant at 41.2%, strong SEO performance',
        'Paid ads efficient with steady 5.6% growth, good ROI',
      ],
    },
    returns: {
      metricId: 'returns',
      drivers: [
        {
          id: 'sizing',
          label: 'Wrong Size',
          value: 1.2,
          contribution: 42.9,
          trend: 'down',
          changePercent: 8.3,
          description: 'Size doesn\'t fit',
          format: 'percentage',
        },
        {
          id: 'defective',
          label: 'Defective Items',
          value: 0.8,
          contribution: 28.6,
          trend: 'down',
          changePercent: 12.5,
          description: 'Quality issues',
          format: 'percentage',
        },
        {
          id: 'changed-mind',
          label: 'Changed Mind',
          value: 0.5,
          contribution: 17.8,
          trend: 'down',
          changePercent: 4.2,
          description: 'Customer preference change',
          format: 'percentage',
        },
        {
          id: 'not-as-described',
          label: 'Not As Described',
          value: 0.3,
          contribution: 10.7,
          trend: 'down',
          changePercent: 15.8,
          description: 'Product mismatch',
          format: 'percentage',
        },
      ],
      insights: [
        'Overall return rate improving across all categories',
        'Sizing issues down 8.3%, improved size guides working',
        'Quality control improvements reducing defective returns by 12.5%',
      ],
    },
  }

  return breakdowns[metricId] || {
    metricId,
    drivers: [],
    insights: [],
  }
}

export function generateOmnichannelMetrics(): MetricData[] {
  const baseMetrics = [
    {
      id: 'omni-online-orders',
      label: 'Online Orders',
      value: 1247,
      previousValue: 1189,
      unit: '',
      format: 'number' as const,
      icon: 'shopping',
    },
    {
      id: 'omni-store-orders',
      label: 'In-Store Orders',
      value: 523,
      previousValue: 578,
      unit: '',
      format: 'number' as const,
      icon: 'storefront',
    },
    {
      id: 'omni-bopis',
      label: 'Buy Online Pick In-Store',
      value: 187,
      previousValue: 165,
      unit: '',
      format: 'number' as const,
      icon: 'package',
    },
    {
      id: 'omni-ship-from-store',
      label: 'Ship from Store',
      value: 94,
      previousValue: 82,
      unit: '',
      format: 'number' as const,
      icon: 'truck',
    },
    {
      id: 'omni-cross-channel',
      label: 'Cross-Channel Rate',
      value: 28.3,
      previousValue: 25.1,
      unit: '%',
      format: 'percentage' as const,
      icon: 'arrows',
    },
    {
      id: 'omni-mobile-conversion',
      label: 'Mobile Conversion',
      value: 4.12,
      previousValue: 3.89,
      unit: '%',
      format: 'percentage' as const,
      icon: 'device',
    },
    {
      id: 'omni-store-traffic',
      label: 'Store Foot Traffic',
      value: 8934,
      previousValue: 9203,
      unit: '',
      format: 'number' as const,
      icon: 'users',
    },
    {
      id: 'omni-fulfillment-time',
      label: 'Avg Fulfillment Time',
      value: 2.4,
      previousValue: 2.8,
      unit: 'days',
      format: 'number' as const,
      icon: 'clock',
    },
  ]

  return baseMetrics.map((metric) => {
    const changePercent = ((metric.value - metric.previousValue) / metric.previousValue) * 100
    const trend = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'neutral'
    
    const sparklineData = Array.from({ length: 20 }, (_, i) => {
      const progress = i / 19
      const variation = Math.sin(i * 0.5) * 0.1
      return metric.previousValue + (metric.value - metric.previousValue) * progress + variation * metric.value
    })

    return {
      ...metric,
      trend,
      changePercent: Math.abs(changePercent),
      sparklineData,
    }
  })
}

export function generateCustomerEngagementMetrics(): MetricData[] {
  const baseMetrics = [
    {
      id: 'ce-email-open',
      label: 'Email Open Rate',
      value: 24.8,
      previousValue: 22.3,
      unit: '%',
      format: 'percentage' as const,
      icon: 'mail',
    },
    {
      id: 'ce-click-through',
      label: 'Click-Through Rate',
      value: 3.6,
      previousValue: 3.2,
      unit: '%',
      format: 'percentage' as const,
      icon: 'cursor',
    },
    {
      id: 'ce-loyalty-enrollment',
      label: 'Loyalty Enrollments',
      value: 342,
      previousValue: 298,
      unit: '',
      format: 'number' as const,
      icon: 'star',
    },
    {
      id: 'ce-social-engagement',
      label: 'Social Engagement',
      value: 12450,
      previousValue: 11780,
      unit: '',
      format: 'number' as const,
      icon: 'heart',
    },
    {
      id: 'ce-reviews',
      label: 'Customer Reviews',
      value: 189,
      previousValue: 201,
      unit: '',
      format: 'number' as const,
      icon: 'chat',
    },
    {
      id: 'ce-avg-rating',
      label: 'Average Rating',
      value: 4.6,
      previousValue: 4.5,
      unit: '/5',
      format: 'number' as const,
      icon: 'star',
    },
    {
      id: 'ce-repeat-rate',
      label: 'Repeat Purchase Rate',
      value: 42.8,
      previousValue: 39.2,
      unit: '%',
      format: 'percentage' as const,
      icon: 'refresh',
    },
    {
      id: 'ce-nps',
      label: 'Net Promoter Score',
      value: 68,
      previousValue: 64,
      unit: '',
      format: 'number' as const,
      icon: 'thumbsup',
    },
  ]

  return baseMetrics.map((metric) => {
    const changePercent = ((metric.value - metric.previousValue) / metric.previousValue) * 100
    const trend = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'neutral'
    
    const sparklineData = Array.from({ length: 20 }, (_, i) => {
      const progress = i / 19
      const variation = Math.sin(i * 0.5) * 0.1
      return metric.previousValue + (metric.value - metric.previousValue) * progress + variation * metric.value
    })

    return {
      ...metric,
      trend,
      changePercent: Math.abs(changePercent),
      sparklineData,
    }
  })
}

export function generateInventoryReplenishmentMetrics(): MetricData[] {
  const baseMetrics = [
    {
      id: 'ir-stock-outs',
      label: 'Stock-Out Items',
      value: 12,
      previousValue: 18,
      unit: '',
      format: 'number' as const,
      icon: 'warning',
    },
    {
      id: 'ir-days-inventory',
      label: 'Days of Inventory',
      value: 34.2,
      previousValue: 38.9,
      unit: 'days',
      format: 'number' as const,
      icon: 'calendar',
    },
    {
      id: 'ir-turnover-rate',
      label: 'Inventory Turnover',
      value: 6.8,
      previousValue: 6.2,
      unit: 'x',
      format: 'number' as const,
      icon: 'cycle',
    },
    {
      id: 'ir-pending-orders',
      label: 'Pending POs',
      value: 47,
      previousValue: 52,
      unit: '',
      format: 'number' as const,
      icon: 'document',
    },
    {
      id: 'ir-overstock',
      label: 'Overstock Items',
      value: 89,
      previousValue: 103,
      unit: '',
      format: 'number' as const,
      icon: 'boxes',
    },
    {
      id: 'ir-fill-rate',
      label: 'Order Fill Rate',
      value: 94.3,
      previousValue: 91.8,
      unit: '%',
      format: 'percentage' as const,
      icon: 'check',
    },
    {
      id: 'ir-lead-time',
      label: 'Avg Lead Time',
      value: 8.5,
      previousValue: 9.2,
      unit: 'days',
      format: 'number' as const,
      icon: 'clock',
    },
    {
      id: 'ir-reorder-alerts',
      label: 'Reorder Alerts',
      value: 23,
      previousValue: 19,
      unit: '',
      format: 'number' as const,
      icon: 'bell',
    },
  ]

  return baseMetrics.map((metric) => {
    const changePercent = ((metric.value - metric.previousValue) / metric.previousValue) * 100
    const trend = changePercent > 0 ? 'up' : changePercent < 0 ? 'down' : 'neutral'
    
    const sparklineData = Array.from({ length: 20 }, (_, i) => {
      const progress = i / 19
      const variation = Math.sin(i * 0.5) * 0.1
      return metric.previousValue + (metric.value - metric.previousValue) * progress + variation * metric.value
    })

    return {
      ...metric,
      trend,
      changePercent: Math.abs(changePercent),
      sparklineData,
    }
  })
}

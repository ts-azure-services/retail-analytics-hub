import { useState, useEffect, useRef } from 'react'
import { useKV } from '@github/spark/hooks'
import { NavigationSidebar, TabId, Persona, getDefaultTabForPersona } from './components/NavigationSidebar'
import { DashboardView } from './components/DashboardView'
import { MetricDetailView } from './components/MetricDetailView'
import { DigestView } from './components/DigestView'
import { ReviewTableView } from './components/ReviewTableView'
import { generateMetricBreakdown } from './lib/mock-data'
import { useTabMetrics } from './hooks/use-metrics'
import { MetricData, ChatMessage, MetricBreakdown } from './lib/types'
import { fetchDigest } from './lib/api-client'
import { Toaster, toast } from 'sonner'
import { useIsMobile } from './hooks/use-mobile'
import { Sheet, SheetContent, SheetTrigger } from './components/ui/sheet'
import { Button } from './components/ui/button'
import { List } from '@phosphor-icons/react'

type View = 'dashboard' | 'detail' | 'review-table'
type ReviewFilter = 'all' | 'positive' | 'negative' | 'needs_review'

function App() {
  const isMobile = useIsMobile()
  const [activeTab, setActiveTab] = useState<TabId>('main')
  const [currentView, setCurrentView] = useState<View>('dashboard')
  const [selectedMetric, setSelectedMetric] = useState<MetricData | null>(null)
  const [breakdown, setBreakdown] = useState<MetricBreakdown | null>(null)
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>('all')
  const [reviewTitle, setReviewTitle] = useState<string>('Customer Reviews')
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [persona, setPersona] = useState<Persona>('Master')

  const handlePersonaChange = (newPersona: Persona) => {
    setPersona(newPersona)
    const defaultTab = getDefaultTabForPersona(newPersona)
    setActiveTab(defaultTab)
    setCurrentView('dashboard')
  }
  
  const { metrics: mainMetrics } = useTabMetrics('main', 30_000)
  const { metrics: omnichannelMetrics } = useTabMetrics('omnichannel', 30_000)
  const { metrics: customerEngagementMetrics } = useTabMetrics('customer-engagement', 30_000)
  const { metrics: inventoryReplenishmentMetrics } = useTabMetrics('inventory-replenishment', 30_000)
  const { metrics: customerReviewsMetrics } = useTabMetrics('customer-reviews', 30_000)
  
  const [mainMessages, setMainMessages] = useKV<ChatMessage[]>('chat-messages-main', [])
  const [omnichannelMessages, setOmnichannelMessages] = useKV<ChatMessage[]>('chat-messages-omnichannel', [])
  const [customerEngagementMessages, setCustomerEngagementMessages] = useKV<ChatMessage[]>('chat-messages-customer-engagement', [])
  const [inventoryReplenishmentMessages, setInventoryReplenishmentMessages] = useKV<ChatMessage[]>('chat-messages-inventory-replenishment', [])
  const [customerReviewsMessages, setCustomerReviewsMessages] = useKV<ChatMessage[]>('chat-messages-customer-reviews', [])
  
  const [isLoading, setIsLoading] = useState(false)

  // Track which tabs have already had their auto-query fired
  const autoQueriedTabsRef = useRef<Set<string>>(new Set())

  // Digest tab state (Agent 2)
  const AGENT2_API = '/api/digest/generate'
  const [digestNarrative, setDigestNarrative] = useKV<string | null>('digest-narrative', null)
  const [digestLoading, setDigestLoading] = useState(false)
  const [digestLastGenerated, setDigestLastGenerated] = useState<Date | null>(null)
  const digestPollingRef = useRef(false)

  // Auto-poll for pre-generated digest from server (Agent 2 triggered on startup)
  useEffect(() => {
    if (digestNarrative || digestPollingRef.current) return
    digestPollingRef.current = true
    setDigestLoading(true)

    let cancelled = false
    const poll = async () => {
      const maxAttempts = 60   // poll for up to ~5 min (every 5s)
      for (let i = 0; i < maxAttempts; i++) {
        if (cancelled) return
        try {
          const result = await fetchDigest()
          if (result.status === 'ready' && result.narrative) {
            if (!cancelled) {
              setDigestNarrative(result.narrative)
              setDigestLastGenerated(new Date(result.generated_at || Date.now()))
              setDigestLoading(false)
              toast.success('Digest ready')
            }
            return
          }
          if (result.status === 'none') {
            // Agent 2 not available — stop polling
            if (!cancelled) setDigestLoading(false)
            return
          }
        } catch {
          // server not ready yet, keep trying
        }
        await new Promise(r => setTimeout(r, 5000))
      }
      if (!cancelled) setDigestLoading(false)
    }
    poll()

    return () => { cancelled = true }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerateDigest = async () => {
    setDigestLoading(true)
    try {
      const res = await fetch(AGENT2_API, { method: 'POST' })
      if (!res.ok) {
        toast.error('Failed to trigger digest generation.')
        setDigestLoading(false)
        return
      }
      // Poll /api/digest until ready (server calls Agent 2 in the background)
      const poll = setInterval(async () => {
        try {
          const pollRes = await fetch('/api/digest')
          if (pollRes.ok) {
            const data = await pollRes.json()
            if (data.status === 'ready') {
              clearInterval(poll)
              setDigestNarrative(data.narrative || data.summary || 'No narrative returned.')
              setDigestLastGenerated(new Date(data.generated_at || Date.now()))
              setDigestLoading(false)
              toast.success('Digest generated')
            }
          }
        } catch { /* keep polling */ }
      }, 3000)
      // Timeout after 5 min
      setTimeout(() => {
        clearInterval(poll)
        setDigestLoading(false)
      }, 300_000)
    } catch (error) {
      toast.error('Could not reach the server.')
      console.error('Digest generation error:', error)
      setDigestLoading(false)
    }
  }

  const getActiveMetrics = () => {
    switch (activeTab) {
      case 'omnichannel':
        return omnichannelMetrics
      case 'customer-engagement':
        return customerEngagementMetrics
      case 'inventory-replenishment':
        return inventoryReplenishmentMetrics
      case 'customer-reviews':
        return customerReviewsMetrics
      default:
        return mainMetrics
    }
  }

  const getActiveMessages = () => {
    switch (activeTab) {
      case 'omnichannel':
        return omnichannelMessages
      case 'customer-engagement':
        return customerEngagementMessages
      case 'inventory-replenishment':
        return inventoryReplenishmentMessages
      case 'customer-reviews':
        return customerReviewsMessages
      default:
        return mainMessages
    }
  }

  const setActiveMessages = (setter: (current?: ChatMessage[]) => ChatMessage[]) => {
    switch (activeTab) {
      case 'omnichannel':
        setOmnichannelMessages(setter)
        break
      case 'customer-engagement':
        setCustomerEngagementMessages(setter)
        break
      case 'inventory-replenishment':
        setInventoryReplenishmentMessages(setter)
        break
      case 'customer-reviews':
        setCustomerReviewsMessages(setter)
        break
      default:
        setMainMessages(setter)
        break
    }
  }

  const getTabTitle = () => {
    switch (activeTab) {
      case 'omnichannel':
        return 'Omnichannel Analytics'
      case 'customer-engagement':
        return 'Customer Engagement'
      case 'inventory-replenishment':
        return 'Inventory Replenishment'
      case 'customer-reviews':
        return 'Customer Reviews'
      default:
        return 'Retail Analytics Hub'
    }
  }

  const getTabSubtitle = () => {
    switch (activeTab) {
      case 'omnichannel':
        return 'Cross-channel performance and fulfillment metrics'
      case 'customer-engagement':
        return 'Customer interaction and loyalty insights'
      case 'inventory-replenishment':
        return 'Stock levels and replenishment tracking'
      case 'customer-reviews':
        return 'Sentiment analysis and review processing metrics'
      default:
        return 'Real-time performance metrics and insights'
    }
  }


  // Agent 1 — Dashboard Explainer (proxied through dashboard server)
  const AGENT1_API = '/api/chat'

  const handleSendMessage = async (content: string) => {
    const userMessage: ChatMessage = {
      id: `${Date.now()}-user`,
      role: 'user',
      content,
      timestamp: new Date(),
    }

    setActiveMessages((current) => [...(current || []), userMessage])
    setIsLoading(true)

    try {
      let response: string | null = null

      // --- Try Agent 1 (Dashboard Explainer) via server proxy ---
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 30000)
        const res = await fetch(AGENT1_API, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: content,
            active_tab: activeTab,
            current_view: currentView,
            selected_metric_id: selectedMetric?.id || null,
            session_id: `${activeTab}-${Date.now()}`,
          }),
          signal: controller.signal,
        })
        clearTimeout(timeout)
        if (res.ok) {
          const data = await res.json()
          response = data.response || null
        }
      } catch {
        // Agent unavailable — fall through to Spark LLM
      }

      // --- Fallback to Spark LLM if agent unavailable ---
      if (!response) {
        const activeMetrics = getActiveMetrics()
        const metricsContext = activeMetrics.map(m =>
          `- ${m.label}: ${m.format === 'currency' ? '$' : ''}${m.value.toLocaleString()}${m.format === 'percentage' ? '%' : ''}`
        ).join('\n')

        let promptText = ''

        if (currentView === 'detail' && selectedMetric && breakdown) {
          const formatValue = (value: number, format: 'number' | 'currency' | 'percentage') => {
            switch (format) {
              case 'currency':
                return `$${value.toLocaleString()}`
              case 'percentage':
                return `${value.toFixed(2)}%`
              default:
                return value.toLocaleString()
            }
          }

          const driversInfo = breakdown.drivers.map(d =>
            `  - ${d.label}: ${formatValue(d.value, d.format)} (${d.contribution.toFixed(1)}% of total, ${d.trend} ${d.changePercent.toFixed(1)}%)`
          ).join('\n')

          const insightsInfo = breakdown.insights.map((insight, i) => `${i + 1}. ${insight}`).join('\n')

          const forecastInfo = selectedMetric.forecast
            ? `\nForecast:\n- Forecasted Value: ${formatValue(selectedMetric.forecast.value, selectedMetric.format)}\n- Variance: ${selectedMetric.forecast.variance >= 0 ? '+' : ''}${formatValue(Math.abs(selectedMetric.forecast.variance), selectedMetric.format)} (${selectedMetric.forecast.variancePercent >= 0 ? '+' : ''}${selectedMetric.forecast.variancePercent.toFixed(1)}%)`
            : ''

          promptText = (window.spark.llmPrompt as any)`You are a retail analytics assistant. The user asked: "${content}".

The user is viewing the detailed breakdown page for "${selectedMetric.label}" in the ${getTabTitle()} section.

Current Metric Details:
- Metric: ${selectedMetric.label}
- Current Value: ${formatValue(selectedMetric.value, selectedMetric.format)}
- Previous Value: ${formatValue(selectedMetric.previousValue, selectedMetric.format)}
- Change: ${selectedMetric.changePercent.toFixed(2)}% (${selectedMetric.trend})${forecastInfo}

Key Drivers of ${selectedMetric.label}:
${driversInfo}

Key Insights:
${insightsInfo}

Overall ${getTabTitle()} Metrics:
${metricsContext}

When answering, prioritize information about the current metric (${selectedMetric.label}) being viewed, but you can still reference other metrics if relevant. Keep responses under 150 words.`
        } else {
          promptText = (window.spark.llmPrompt as any)`You are a retail analytics assistant. The user asked: "${content}".

CURRENT VIEW CONTEXT:
The user is viewing the ${getTabTitle()} dashboard.

${getTabTitle()} Metrics:
${metricsContext}

Provide a helpful, concise response about the retail data. Keep responses under 150 words.`
        }

        response = await window.spark.llm(promptText, 'gpt-4o-mini')
      }

      const assistantMessage: ChatMessage = {
        id: `${Date.now()}-assistant`,
        role: 'assistant',
        content: response,
        timestamp: new Date(),
      }

      setActiveMessages((current) => [...(current || []), assistantMessage])
      toast.success('Response received')
    } catch (error) {
      toast.error('Failed to get response. Please try again.')
      console.error('Chat error:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleMetricUpdate = () => {
  }

  // Auto-fire "tell me what's going on" when a metric tab is first visited
  const AUTO_QUERY_TABS: TabId[] = ['main', 'omnichannel', 'customer-engagement', 'inventory-replenishment', 'customer-reviews']
  useEffect(() => {
    if (!AUTO_QUERY_TABS.includes(activeTab)) return
    if (autoQueriedTabsRef.current.has(activeTab)) return
    // Don't fire while another query is in-flight
    if (isLoading) return
    const currentMessages = getActiveMessages()
    if (currentMessages && currentMessages.length > 0) {
      // Already has messages (persisted from a prior session) — skip
      autoQueriedTabsRef.current.add(activeTab)
      return
    }
    // Capture the tab for the closure; only mark as queried when the query actually fires
    const tabToQuery = activeTab
    const timer = setTimeout(() => {
      autoQueriedTabsRef.current.add(tabToQuery)
      handleSendMessage('Tell me what\'s going on')
    }, 500)
    return () => clearTimeout(timer)
  }, [activeTab, isLoading])  // eslint-disable-line react-hooks/exhaustive-deps

  const handleMetricClick = (metric: MetricData) => {
    // Customer reviews tiles → show review records table
    if (activeTab === 'customer-reviews') {
      if (metric.id === 'cr-total-reviews') {
        setReviewFilter('all')
        setReviewTitle('All Customer Reviews')
      } else if (metric.id === 'cr-positive-pct') {
        setReviewFilter('positive')
        setReviewTitle('Positive Reviews')
      } else if (metric.id === 'cr-negative-pct') {
        setReviewFilter('negative')
        setReviewTitle('Negative Reviews')
      } else if (metric.id === 'cr-needs-review') {
        setReviewFilter('needs_review')
        setReviewTitle('Reviews Needing Human Review')
      } else {
        // Other review tiles (avg score, processed) → default detail view
        setSelectedMetric(metric)
        const metricBreakdown = generateMetricBreakdown(metric.id)
        setBreakdown(metricBreakdown)
        setCurrentView('detail')
        return
      }
      setCurrentView('review-table')
      return
    }

    setSelectedMetric(metric)
    const metricBreakdown = generateMetricBreakdown(metric.id)
    setBreakdown(metricBreakdown)
    setCurrentView('detail')
  }

  const handleBackToDashboard = () => {
    setCurrentView('dashboard')
    setSelectedMetric(null)
  }

  const handleRefreshChat = () => {
    setActiveMessages(() => [])
  }

  const handleTabChange = (tab: TabId) => {
    setActiveTab(tab)
    if (currentView !== 'dashboard') {
      setCurrentView('dashboard')
      setSelectedMetric(null)
    }
    setMobileMenuOpen(false)
  }

  const mobileNav = isMobile && (
    <div className="fixed bottom-4 left-4 z-50">
      <Sheet open={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
        <SheetTrigger asChild>
          <Button size="lg" className="rounded-full shadow-xl">
            <List className="w-6 h-6" weight="bold" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-[280px] p-0">
          <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} persona={persona} onPersonaChange={handlePersonaChange} />
        </SheetContent>
      </Sheet>
    </div>
  )

  // Digest tab — dedicated view with Agent 2 narrative
  if (activeTab === 'digest') {
    return (
      <div className="flex h-screen">
        <Toaster />
        {mobileNav}
        {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} persona={persona} onPersonaChange={handlePersonaChange} />}
        <DigestView
          narrative={digestNarrative ?? null}
          isLoading={digestLoading}
          onGenerate={handleGenerateDigest}
          lastGenerated={digestLastGenerated}
        />
      </div>
    )
  }

  // Review table view — Customer Reviews tab drill-down
  if (currentView === 'review-table') {
    return (
      <div className="flex h-screen">
        <Toaster />
        {mobileNav}
        {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} persona={persona} onPersonaChange={handlePersonaChange} />}
        <ReviewTableView
          filter={reviewFilter}
          title={reviewTitle}
          onBack={handleBackToDashboard}
        />
      </div>
    )
  }

  if (currentView === 'detail' && selectedMetric && breakdown) {
    return (
      <div className="flex h-screen">
        <Toaster />
        {mobileNav}
        {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} persona={persona} onPersonaChange={handlePersonaChange} />}
        <MetricDetailView
          metric={selectedMetric}
          breakdown={breakdown}
          onBack={handleBackToDashboard}
          chatMessages={getActiveMessages() || []}
          onSendMessage={handleSendMessage}
          isChatLoading={isLoading}
          chatOpen={chatOpen}
          setChatOpen={setChatOpen}
          onRefreshChat={handleRefreshChat}
        />
      </div>
    )
  }

  return (
    <div className="flex h-screen">
      <Toaster />
      {mobileNav}
      {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} persona={persona} onPersonaChange={handlePersonaChange} />}
      <DashboardView
        title={getTabTitle()}
        subtitle={getTabSubtitle()}
        metrics={getActiveMetrics()}
        onMetricClick={handleMetricClick}
        onMetricUpdate={handleMetricUpdate}
        chatMessages={getActiveMessages() || []}
        onSendMessage={handleSendMessage}
        isChatLoading={isLoading}
        onRefreshChat={handleRefreshChat}
      />
    </div>
  )
}

export default App

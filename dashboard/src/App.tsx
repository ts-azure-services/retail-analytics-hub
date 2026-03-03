import { useState } from 'react'
import { useKV } from '@github/spark/hooks'
import { NavigationSidebar, TabId } from './components/NavigationSidebar'
import { DashboardView } from './components/DashboardView'
import { MetricDetailView } from './components/MetricDetailView'
import { DigestView } from './components/DigestView'
import { generateMetricBreakdown } from './lib/mock-data'
import { useTabMetrics } from './hooks/use-metrics'
import { MetricData, ChatMessage, MetricBreakdown } from './lib/types'
import { Toaster, toast } from 'sonner'
import { useIsMobile } from './hooks/use-mobile'
import { Sheet, SheetContent, SheetTrigger } from './components/ui/sheet'
import { Button } from './components/ui/button'
import { List } from '@phosphor-icons/react'

type View = 'dashboard' | 'detail'

function App() {
  const isMobile = useIsMobile()
  const [activeTab, setActiveTab] = useState<TabId>('main')
  const [currentView, setCurrentView] = useState<View>('dashboard')
  const [selectedMetric, setSelectedMetric] = useState<MetricData | null>(null)
  const [breakdown, setBreakdown] = useState<MetricBreakdown | null>(null)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  
  const { metrics: mainMetrics } = useTabMetrics('main', 30_000)
  const { metrics: omnichannelMetrics } = useTabMetrics('omnichannel', 30_000)
  const { metrics: customerEngagementMetrics } = useTabMetrics('customer-engagement', 30_000)
  const { metrics: inventoryReplenishmentMetrics } = useTabMetrics('inventory-replenishment', 30_000)
  
  const [mainMessages, setMainMessages] = useKV<ChatMessage[]>('chat-messages-main', [])
  const [omnichannelMessages, setOmnichannelMessages] = useKV<ChatMessage[]>('chat-messages-omnichannel', [])
  const [customerEngagementMessages, setCustomerEngagementMessages] = useKV<ChatMessage[]>('chat-messages-customer-engagement', [])
  const [inventoryReplenishmentMessages, setInventoryReplenishmentMessages] = useKV<ChatMessage[]>('chat-messages-inventory-replenishment', [])
  
  const [isLoading, setIsLoading] = useState(false)

  // Digest tab state (Agent 2)
  const AGENT2_URL = 'http://localhost:8002'
  const [digestNarrative, setDigestNarrative] = useKV<string | null>('digest-narrative', null)
  const [digestLoading, setDigestLoading] = useState(false)
  const [digestLastGenerated, setDigestLastGenerated] = useState<Date | null>(null)

  const handleGenerateDigest = async () => {
    setDigestLoading(true)
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 300000)
      const res = await fetch(`${AGENT2_URL}/narrative`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: 'Generate a comprehensive business narrative covering revenue, operations, customer engagement, and inventory health.',
          session_id: `digest-${Date.now()}`,
          focus_areas: ['revenue', 'operations', 'customer', 'inventory'],
        }),
        signal: controller.signal,
      })
      clearTimeout(timeout)
      if (res.ok) {
        const data = await res.json()
        setDigestNarrative(data.narrative || data.summary || 'No narrative returned.')
        setDigestLastGenerated(new Date())
        toast.success('Digest generated')
      } else {
        toast.error('Agent 2 returned an error. Please try again.')
      }
    } catch (error) {
      toast.error('Could not reach Agent 2. Make sure it is running on port 8002.')
      console.error('Digest generation error:', error)
    } finally {
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
      default:
        return 'Real-time performance metrics and insights'
    }
  }


  // Agent 1 — Dashboard Explainer
  const AGENT1_URL = 'http://localhost:8001'

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

      // --- Try Agent 1 (Dashboard Explainer) ---
      try {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 30000)
        const res = await fetch(`${AGENT1_URL}/chat`, {
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

  const handleMetricClick = (metric: MetricData) => {
    setSelectedMetric(metric)
    const metricBreakdown = generateMetricBreakdown(metric.id)
    setBreakdown(metricBreakdown)
    setCurrentView('detail')
  }

  const handleBackToDashboard = () => {
    setCurrentView('dashboard')
    setSelectedMetric(null)
    setActiveMessages(() => [])
  }

  const handleRefreshChat = () => {
    setActiveMessages(() => [])
  }

  const handleTabChange = (tab: TabId) => {
    setActiveTab(tab)
    if (currentView === 'detail') {
      handleBackToDashboard()
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
          <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} />
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
        {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} />}
        <DigestView
          narrative={digestNarrative ?? null}
          isLoading={digestLoading}
          onGenerate={handleGenerateDigest}
          lastGenerated={digestLastGenerated}
        />
      </div>
    )
  }

  if (currentView === 'detail' && selectedMetric && breakdown) {
    return (
      <div className="flex h-screen">
        <Toaster />
        {mobileNav}
        {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} />}
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
      {!isMobile && <NavigationSidebar activeTab={activeTab} onTabChange={handleTabChange} />}
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

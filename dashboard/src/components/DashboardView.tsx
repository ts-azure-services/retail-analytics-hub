import { useState } from 'react'
import { MetricTile } from './MetricTile'
import { ChatInterface } from './ChatInterface'
import { Separator } from '@/components/ui/separator'
import { MetricData, ChatMessage } from '@/lib/types'
import { useIsMobile } from '@/hooks/use-mobile'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { ChatCircle } from '@phosphor-icons/react'

interface DashboardViewProps {
  title: string
  subtitle: string
  metrics: MetricData[]
  onMetricClick: (metric: MetricData) => void
  onMetricUpdate: () => void
  chatMessages: ChatMessage[]
  onSendMessage: (content: string) => void
  isChatLoading: boolean
  onRefreshChat: () => void
}

export function DashboardView({
  title,
  subtitle,
  metrics,
  onMetricClick,
  onMetricUpdate,
  chatMessages,
  onSendMessage,
  isChatLoading,
  onRefreshChat,
}: DashboardViewProps) {
  const isMobile = useIsMobile()
  const [chatOpen, setChatOpen] = useState(false)

  const chatInterface = (
    <ChatInterface
      messages={chatMessages || []}
      onSendMessage={onSendMessage}
      isLoading={isChatLoading}
      onRefresh={onRefreshChat}
    />
  )

  return (
    <div className="flex-1 bg-gradient-to-br from-background via-background to-muted/30 overflow-auto">
      <div className="container mx-auto px-4 py-8">
        <header className="mb-8">
          <div>
            <h1 className="text-4xl font-bold font-space tracking-tight">
              {title}
            </h1>
            <p className="text-muted-foreground text-lg mt-1">
              {subtitle}
            </p>
          </div>
        </header>

        <Separator className="mb-8" />

        <div className={isMobile ? 'space-y-6' : 'grid grid-cols-1 lg:grid-cols-3 gap-6'}>
          <div className={isMobile ? 'space-y-6' : 'lg:col-span-2 space-y-6'}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {metrics.map((metric) => (
                <MetricTile
                  key={metric.id}
                  metric={metric}
                  onUpdate={onMetricUpdate}
                  onClick={() => onMetricClick(metric)}
                />
              ))}
            </div>
          </div>

          {isMobile ? (
            <Sheet open={chatOpen} onOpenChange={setChatOpen}>
              <SheetTrigger asChild>
                <Button
                  size="lg"
                  className="fixed bottom-6 right-6 rounded-full shadow-2xl w-14 h-14 p-0 z-50"
                >
                  <ChatCircle className="w-6 h-6" weight="bold" />
                </Button>
              </SheetTrigger>
              <SheetContent side="bottom" className="h-[80vh] p-0">
                <div className="h-full p-4">
                  {chatInterface}
                </div>
              </SheetContent>
            </Sheet>
          ) : (
            <div className="lg:col-span-1">
              <div className="sticky top-6 h-[calc(100vh-8rem)]">
                {chatInterface}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

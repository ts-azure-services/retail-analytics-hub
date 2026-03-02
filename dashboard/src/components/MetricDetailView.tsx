import { MetricData, MetricBreakdown, ChatMessage } from '@/lib/types'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { ArrowLeft, TrendUp, TrendDown, Lightbulb, ChartLine, ChatCircle, Target } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'
import { motion } from 'framer-motion'
import { ChatInterface } from './ChatInterface'
import { useIsMobile } from '@/hooks/use-mobile'

interface MetricDetailViewProps {
  metric: MetricData
  breakdown: MetricBreakdown
  onBack: () => void
  chatMessages: ChatMessage[]
  onSendMessage: (content: string) => void
  isChatLoading: boolean
  chatOpen: boolean
  setChatOpen: (open: boolean) => void
  onRefreshChat?: () => void
}

export function MetricDetailView({ 
  metric, 
  breakdown, 
  onBack, 
  chatMessages, 
  onSendMessage, 
  isChatLoading,
  chatOpen,
  setChatOpen,
  onRefreshChat
}: MetricDetailViewProps) {
  const isMobile = useIsMobile()
  
  const formatValue = (value: number, format: 'number' | 'currency' | 'percentage') => {
    switch (format) {
      case 'currency':
        return `$${value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
      case 'percentage':
        return `${value.toFixed(2)}%`
      default:
        return Math.round(value).toLocaleString('en-US')
    }
  }

  const isWarning = metric.id === 'inventory' && metric.trend === 'up'
  const isPositive = metric.trend === 'up' && !isWarning
  const isNegative = metric.trend === 'down' || isWarning

  const chatInterface = (
    <ChatInterface
      messages={chatMessages || []}
      onSendMessage={onSendMessage}
      isLoading={isChatLoading}
      onRefresh={onRefreshChat}
    />
  )

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.3 }}
      className="min-h-screen bg-gradient-to-br from-background via-background to-muted/30"
    >
      <div className="container mx-auto px-4 py-8">
        <div className={isMobile ? 'space-y-6' : 'grid grid-cols-1 lg:grid-cols-3 gap-6'}>
          <div className={isMobile ? 'space-y-6' : 'lg:col-span-2 space-y-6'}>
            <div className="mb-6">
              <Button
                variant="ghost"
                onClick={onBack}
                className="gap-2 mb-4 hover:bg-accent/10"
              >
                <ArrowLeft className="w-4 h-4" weight="bold" />
                Back to Dashboard
              </Button>

              <div className="flex items-center gap-4">
                <div className={cn(
                  "p-4 rounded-xl shadow-lg",
                  isWarning ? "bg-warning" : "bg-primary"
                )}>
                  <ChartLine className="w-10 h-10 text-primary-foreground" weight="bold" />
                </div>
                <div>
                  <h1 className="text-4xl font-bold font-space tracking-tight">
                    {metric.label}
                  </h1>
                  <p className="text-muted-foreground text-lg mt-1">
                    Detailed breakdown and key drivers
                  </p>
                </div>
              </div>
            </div>

            <Separator className="mb-8" />

            <div className="space-y-8">
              <Card className="p-8">
                <div className="flex items-start justify-between mb-6">
                  <div>
                    <p className="text-sm font-medium font-space uppercase tracking-wide text-muted-foreground mb-2">
                      Current Value
                    </p>
                    <div className="flex items-baseline gap-3">
                      <span className="text-6xl font-bold font-mono tabular-nums">
                        {formatValue(metric.value, metric.format)}
                      </span>
                      <div className="flex items-center gap-2">
                        {metric.trend === 'up' && (
                          <TrendUp className={cn(
                            "w-6 h-6",
                            isPositive ? "text-success" : "text-destructive"
                          )} weight="bold" />
                        )}
                        {metric.trend === 'down' && (
                          <TrendDown className={cn(
                            "w-6 h-6",
                            isNegative ? "text-destructive" : "text-success"
                          )} weight="bold" />
                        )}
                        <span className={cn(
                          "text-2xl font-medium font-mono tabular-nums",
                          isPositive && "text-success",
                          isNegative && "text-destructive",
                          metric.trend === 'neutral' && "text-muted-foreground"
                        )}>
                          {metric.changePercent.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                  </div>
                  <Badge variant="secondary" className="text-sm px-4 py-2">
                    LIVE DATA
                  </Badge>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-6 border-t">
                  <div>
                    <p className="text-sm text-muted-foreground mb-1">Previous Value</p>
                    <p className="text-2xl font-bold font-mono tabular-nums">
                      {formatValue(metric.previousValue, metric.format)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground mb-1">Change</p>
                    <p className="text-2xl font-bold font-mono tabular-nums">
                      {formatValue(metric.value - metric.previousValue, metric.format)}
                    </p>
                  </div>
                </div>

                {metric.forecast && (
                  <div className="pt-6 mt-6 border-t">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="p-2 bg-primary/10 rounded-lg">
                        <Target className="w-5 h-5 text-primary" weight="bold" />
                      </div>
                      <h3 className="text-lg font-semibold font-space">Forecast</h3>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      <div>
                        <p className="text-sm text-muted-foreground mb-1">Forecasted Value</p>
                        <p className="text-2xl font-bold font-mono tabular-nums">
                          {formatValue(metric.forecast.value, metric.format)}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground mb-1">Variance</p>
                        <div className="flex items-baseline gap-2">
                          <p className={cn(
                            "text-2xl font-bold font-mono tabular-nums",
                            metric.forecast.variance >= 0 ? "text-primary" : "text-destructive"
                          )}>
                            {metric.forecast.variance >= 0 ? '+' : ''}{formatValue(Math.abs(metric.forecast.variance), metric.format)}
                          </p>
                        </div>
                      </div>
                      <div>
                        <p className="text-sm text-muted-foreground mb-1">Variance %</p>
                        <Badge 
                          variant={metric.forecast.variancePercent >= 0 ? "default" : "destructive"}
                          className={cn(
                            "text-lg font-mono tabular-nums px-3 py-1",
                            metric.forecast.variancePercent >= 0 ? "bg-primary/10 text-primary" : "bg-destructive/10 text-destructive"
                          )}
                        >
                          {metric.forecast.variancePercent >= 0 ? '+' : ''}{metric.forecast.variancePercent.toFixed(1)}%
                        </Badge>
                      </div>
                    </div>
                  </div>
                )}
              </Card>

              <div>
                <h2 className="text-2xl font-bold font-space mb-4">Key Drivers</h2>
                <div className="grid grid-cols-1 gap-4">
                  {breakdown.drivers.map((driver) => {
                    const isDriverPositive = driver.trend === 'up'
                    const isDriverNegative = driver.trend === 'down'

                    return (
                      <Card key={driver.id} className="p-6 hover:shadow-lg transition-shadow duration-300">
                        <div className="flex items-start justify-between gap-4 mb-4">
                          <div className="flex-1">
                            <div className="flex items-center gap-3 mb-1">
                              <h3 className="text-xl font-semibold font-space">{driver.label}</h3>
                              {driver.trend !== 'neutral' && (
                                <div className="flex items-center gap-1.5">
                                  {driver.trend === 'up' && (
                                    <TrendUp className={cn(
                                      "w-5 h-5",
                                      isDriverPositive ? "text-success" : "text-destructive"
                                    )} weight="bold" />
                                  )}
                                  {driver.trend === 'down' && (
                                    <TrendDown className={cn(
                                      "w-5 h-5",
                                      isDriverNegative ? "text-destructive" : "text-success"
                                    )} weight="bold" />
                                  )}
                                  <span className={cn(
                                    "text-base font-mono font-medium tabular-nums",
                                    isDriverPositive && "text-success",
                                    isDriverNegative && "text-destructive"
                                  )}>
                                    {driver.changePercent.toFixed(1)}%
                                  </span>
                                </div>
                              )}
                            </div>
                            <p className="text-sm text-muted-foreground">{driver.description}</p>
                          </div>
                          <div className="text-right">
                            <div className="text-3xl font-bold font-mono tabular-nums">
                              {formatValue(driver.value, driver.format)}
                            </div>
                            <Badge variant="secondary" className="mt-2">
                              {driver.contribution.toFixed(1)}% of total
                            </Badge>
                          </div>
                        </div>
                        
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-sm text-muted-foreground">
                            <span className="font-medium">Contribution to {metric.label}</span>
                            <span className="font-mono tabular-nums">{driver.contribution.toFixed(1)}%</span>
                          </div>
                          <Progress value={driver.contribution} className="h-3" />
                        </div>
                      </Card>
                    )
                  })}
                </div>
              </div>

              {breakdown.insights.length > 0 && (
                <Card className="p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="p-2.5 bg-accent/10 rounded-lg">
                      <Lightbulb className="w-6 h-6 text-accent" weight="bold" />
                    </div>
                    <h2 className="text-2xl font-bold font-space">Key Insights</h2>
                  </div>
                  <ul className="space-y-3">
                    {breakdown.insights.map((insight, index) => (
                      <li key={index} className="flex gap-4 p-4 rounded-lg bg-accent/5 border border-accent/20">
                        <span className="text-accent font-mono font-bold text-lg mt-0.5 flex-shrink-0">
                          {index + 1}
                        </span>
                        <span className="text-base flex-1">{insight}</span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
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
    </motion.div>
  )
}

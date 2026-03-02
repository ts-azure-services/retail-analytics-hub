import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { MetricBreakdown } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { TrendUp, TrendDown, Lightbulb } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'

interface MetricBreakdownDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  breakdown: MetricBreakdown | null
  metricLabel: string
}

export function MetricBreakdownDialog({ open, onOpenChange, breakdown, metricLabel }: MetricBreakdownDialogProps) {
  if (!breakdown) return null

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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-2xl font-space">{metricLabel} Breakdown</DialogTitle>
          <DialogDescription>
            Key drivers and insights for this metric
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 mt-4">
          <div className="space-y-4">
            <h3 className="text-lg font-semibold font-space">Key Drivers</h3>
            {breakdown.drivers.map((driver) => {
              const isPositive = driver.trend === 'up'
              const isNegative = driver.trend === 'down'

              return (
                <div key={driver.id} className="space-y-3 p-4 rounded-lg border bg-card">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-semibold font-space">{driver.label}</h4>
                        {driver.trend !== 'neutral' && (
                          <div className="flex items-center gap-1">
                            {driver.trend === 'up' && (
                              <TrendUp className={cn(
                                "w-4 h-4",
                                isPositive ? "text-success" : "text-destructive"
                              )} weight="bold" />
                            )}
                            {driver.trend === 'down' && (
                              <TrendDown className={cn(
                                "w-4 h-4",
                                isNegative ? "text-destructive" : "text-success"
                              )} weight="bold" />
                            )}
                            <span className={cn(
                              "text-sm font-mono font-medium tabular-nums",
                              isPositive && "text-success",
                              isNegative && "text-destructive"
                            )}>
                              {driver.changePercent.toFixed(1)}%
                            </span>
                          </div>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground mb-2">{driver.description}</p>
                    </div>
                    <div className="text-right">
                      <div className="text-xl font-bold font-mono tabular-nums">
                        {formatValue(driver.value, driver.format)}
                      </div>
                      <Badge variant="secondary" className="mt-1">
                        {driver.contribution.toFixed(1)}%
                      </Badge>
                    </div>
                  </div>
                  
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>Contribution</span>
                      <span>{driver.contribution.toFixed(1)}%</span>
                    </div>
                    <Progress value={driver.contribution} className="h-2" />
                  </div>
                </div>
              )
            })}
          </div>

          {breakdown.insights.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Lightbulb className="w-5 h-5 text-accent" weight="bold" />
                <h3 className="text-lg font-semibold font-space">Insights</h3>
              </div>
              <ul className="space-y-2">
                {breakdown.insights.map((insight, index) => (
                  <li key={index} className="flex gap-3 p-3 rounded-lg bg-accent/5 border border-accent/20">
                    <span className="text-accent font-mono font-bold text-sm mt-0.5">•</span>
                    <span className="text-sm flex-1">{insight}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendUp, TrendDown, CurrencyDollar, ShoppingCart, ChartLine, Users, Package, Warning, Target } from '@phosphor-icons/react'
import { MetricData } from '@/lib/types'
import { cn } from '@/lib/utils'
import { motion } from 'framer-motion'

interface MetricTileProps {
  metric: MetricData
  onUpdate?: () => void
  onClick?: () => void
}

const iconMap = {
  currency: CurrencyDollar,
  shopping: ShoppingCart,
  trend: ChartLine,
  users: Users,
  cart: ShoppingCart,
  warning: Warning,
  package: Package,
}

export function MetricTile({ metric, onUpdate, onClick }: MetricTileProps) {
  const sparklineRef = useRef<SVGSVGElement>(null)
  const [isUpdating, setIsUpdating] = useState(false)
  const [displayValue, setDisplayValue] = useState(metric.value)
  const prevValueRef = useRef(metric.value)

  useEffect(() => {
    if (prevValueRef.current !== metric.value) {
      setIsUpdating(true)
      
      const startValue = prevValueRef.current
      const endValue = metric.value
      const duration = 400
      const startTime = Date.now()

      const animate = () => {
        const elapsed = Date.now() - startTime
        const progress = Math.min(elapsed / duration, 1)
        const eased = 1 - Math.pow(1 - progress, 3)
        
        setDisplayValue(startValue + (endValue - startValue) * eased)

        if (progress < 1) {
          requestAnimationFrame(animate)
        } else {
          setIsUpdating(false)
          prevValueRef.current = endValue
          onUpdate?.()
        }
      }

      requestAnimationFrame(animate)
    }
  }, [metric.value, onUpdate])

  useEffect(() => {
    if (!sparklineRef.current || !metric.sparklineData) return

    const svg = d3.select(sparklineRef.current)
    const width = 100
    const height = 24
    const data = metric.sparklineData

    svg.selectAll('*').remove()

    const xScale = d3.scaleLinear()
      .domain([0, data.length - 1])
      .range([0, width])

    const yScale = d3.scaleLinear()
      .domain([d3.min(data) || 0, d3.max(data) || 1])
      .range([height, 0])

    const line = d3.line<number>()
      .x((_: number, i: number) => xScale(i))
      .y((d: number) => yScale(d))
      .curve(d3.curveMonotoneX)

    svg.append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', metric.trend === 'up' ? 'oklch(0.6 0.15 145)' : metric.trend === 'down' ? 'oklch(0.55 0.22 25)' : 'oklch(0.5 0.01 250)')
      .attr('stroke-width', 2)
      .attr('d', line)
  }, [metric.sparklineData, metric.trend])

  const formatValue = (value: number) => {
    switch (metric.format) {
      case 'currency':
        return `$${value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
      case 'percentage':
        return `${value.toFixed(2)}%`
      default:
        return Math.round(value).toLocaleString('en-US')
    }
  }

  const Icon = iconMap[metric.icon as keyof typeof iconMap] || ChartLine
  const isWarning = metric.id === 'inventory' && metric.trend === 'up'
  const isPositive = metric.trend === 'up' && !isWarning
  const isNegative = metric.trend === 'down' || isWarning

  return (
    <Card 
      className={cn(
        "p-6 relative overflow-hidden transition-all duration-300 hover:shadow-lg cursor-pointer",
        isUpdating && "ring-2 ring-accent ring-opacity-50"
      )}
      onClick={onClick}
    >
      <motion.div
        initial={false}
        animate={isUpdating ? { scale: [1, 1.02, 1] } : {}}
        transition={{ duration: 0.4 }}
      >
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={cn(
              "p-2.5 rounded-lg",
              isWarning ? "bg-warning/10" : "bg-accent/10"
            )}>
              <Icon className={cn(
                "w-5 h-5",
                isWarning ? "text-warning" : "text-accent"
              )} weight="bold" />
            </div>
            <div>
              <p className="text-sm font-medium font-space uppercase tracking-wide text-muted-foreground">
                {metric.label}
              </p>
            </div>
          </div>
          <Badge variant="secondary" className="text-xs">
            LIVE
          </Badge>
        </div>

        <div className="space-y-3">
          <div className="flex items-baseline gap-2">
            <span className={cn(
              "text-4xl font-bold font-mono tabular-nums leading-none",
              isUpdating && "animate-number-pop"
            )}>
              {formatValue(displayValue)}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {metric.trend === 'up' && (
                <TrendUp className={cn(
                  "w-4 h-4",
                  isPositive ? "text-success" : "text-destructive"
                )} weight="bold" />
              )}
              {metric.trend === 'down' && (
                <TrendDown className={cn(
                  "w-4 h-4",
                  isNegative ? "text-destructive" : "text-success"
                )} weight="bold" />
              )}
              <span className={cn(
                "text-sm font-medium font-mono tabular-nums",
                isPositive && "text-success",
                isNegative && "text-destructive",
                metric.trend === 'neutral' && "text-muted-foreground"
              )}>
                {metric.changePercent.toFixed(2)}%
              </span>
            </div>

            {metric.sparklineData && (
              <svg ref={sparklineRef} width="100" height="24" className="opacity-70" />
            )}
          </div>

          {metric.forecast && (
            <div className="pt-2 border-t border-border/50">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Target className="w-3.5 h-3.5" weight="bold" />
                  <span className="font-medium uppercase tracking-wide">Forecast</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-mono tabular-nums font-semibold text-foreground">
                    {formatValue(metric.forecast.value)}
                  </span>
                  <Badge 
                    variant={metric.forecast.variance >= 0 ? "default" : "destructive"}
                    className={cn(
                      "text-[10px] font-mono tabular-nums",
                      metric.forecast.variance >= 0 ? "bg-primary/10 text-primary" : "bg-destructive/10 text-destructive"
                    )}
                  >
                    {metric.forecast.variance >= 0 ? '+' : ''}{formatValue(Math.abs(metric.forecast.variance))} ({metric.forecast.variancePercent >= 0 ? '+' : ''}{metric.forecast.variancePercent.toFixed(1)}%)
                  </Badge>
                </div>
              </div>
            </div>
          )}
        </div>
      </motion.div>
    </Card>
  )
}

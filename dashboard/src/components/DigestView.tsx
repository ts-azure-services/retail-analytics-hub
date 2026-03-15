import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ArrowClockwise, Lightning } from '@phosphor-icons/react'
import { MarkdownText } from './MarkdownText'

interface DigestViewProps {
  narrative: string | null
  isLoading: boolean
  onGenerate: () => void
  lastGenerated: Date | null
}

export function DigestView({ narrative, isLoading, onGenerate, lastGenerated }: DigestViewProps) {
  return (
    <div className="flex-1 bg-gradient-to-br from-background via-background to-muted/30 overflow-hidden">
      <div className="container mx-auto px-4 py-8 max-w-4xl h-full flex flex-col">
        <header className="mb-8">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-4xl font-bold font-space tracking-tight">
                Business Digest
              </h1>
              <p className="text-muted-foreground text-lg mt-1">
                AI-generated executive narrative across all business areas
              </p>
            </div>
            <Button
              onClick={onGenerate}
              disabled={isLoading}
              size="lg"
              className="gap-2 shrink-0"
            >
              {isLoading ? (
                <ArrowClockwise className="w-5 h-5 animate-spin" weight="bold" />
              ) : (
                <Lightning className="w-5 h-5" weight="bold" />
              )}
              {isLoading ? 'Generating...' : narrative ? 'Regenerate' : 'Generate Digest'}
            </Button>
          </div>
          {lastGenerated && (
            <p className="text-xs text-muted-foreground mt-3">
              Last generated: {lastGenerated.toLocaleString()}
            </p>
          )}
        </header>

        <Separator className="mb-8" />

        {isLoading && !narrative && (
          <Card className="p-8 space-y-4">
            <Skeleton className="h-6 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <div className="pt-4" />
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
            <div className="pt-4" />
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
          </Card>
        )}

        {!isLoading && !narrative && (
          <Card className="p-12 text-center">
            <Lightning className="w-12 h-12 text-muted-foreground mx-auto mb-4" weight="thin" />
            <h3 className="text-lg font-semibold mb-2">No digest generated yet</h3>
            <p className="text-muted-foreground max-w-md mx-auto">
              Click "Generate Digest" above to create an AI-powered executive narrative
              that analyzes metrics across all dashboard tabs.
            </p>
          </Card>
        )}

        {narrative && (
          <Card className={`relative overflow-hidden ${isLoading ? 'opacity-60' : ''}`} style={{ height: 'calc(100vh - 14rem)' }}>
            {isLoading && (
              <div className="absolute top-4 right-4 z-10">
                <ArrowClockwise className="w-5 h-5 animate-spin text-muted-foreground" weight="bold" />
              </div>
            )}
            <ScrollArea className="h-full">
              <div className="p-8">
                <MarkdownText content={narrative} />
              </div>
            </ScrollArea>
          </Card>
        )}
      </div>
    </div>
  )
}

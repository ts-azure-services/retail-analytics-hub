import { useQuery } from '@tanstack/react-query'
import { fetchReviewRecords, ReviewRecord } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ArrowLeft } from '@phosphor-icons/react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface ReviewTableViewProps {
  filter: 'all' | 'positive' | 'negative' | 'needs_review'
  title: string
  onBack: () => void
}

function sentimentBadge(category: string | null) {
  if (!category) return <Badge variant="secondary">Unknown</Badge>
  switch (category) {
    case 'very_positive':
      return <Badge className="bg-emerald-600 text-white">Very Positive</Badge>
    case 'positive':
      return <Badge className="bg-green-500 text-white">Positive</Badge>
    case 'neutral':
      return <Badge variant="secondary">Neutral</Badge>
    case 'negative':
      return <Badge className="bg-orange-500 text-white">Negative</Badge>
    case 'very_negative':
      return <Badge className="bg-red-600 text-white">Very Negative</Badge>
    default:
      return <Badge variant="outline">{category}</Badge>
  }
}

function statusBadge(status: string) {
  if (status === 'processed for response') {
    return <Badge className="bg-blue-500 text-white">Processed</Badge>
  }
  if (status === 'Needing human review') {
    return <Badge className="bg-amber-500 text-white">Needs Review</Badge>
  }
  if (status === 'To be processed') {
    return <Badge variant="outline">Pending</Badge>
  }
  if (status === 'incomplete processing') {
    return <Badge className="bg-red-500 text-white">Incomplete</Badge>
  }
  return <Badge variant="secondary">{status}</Badge>
}

export function ReviewTableView({ filter, title, onBack }: ReviewTableViewProps) {
  const { data: reviews, isLoading, isError } = useQuery<ReviewRecord[]>({
    queryKey: ['reviews', filter],
    queryFn: () => fetchReviewRecords(filter),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.3 }}
      className="flex-1 min-h-screen bg-gradient-to-br from-background via-background to-muted/30 overflow-auto"
    >
      <div className="container mx-auto px-4 py-8">
        <div className="mb-6">
          <Button
            variant="ghost"
            onClick={onBack}
            className="gap-2 mb-4 hover:bg-accent/10"
          >
            <ArrowLeft className="w-4 h-4" weight="bold" />
            Back to Dashboard
          </Button>

          <h1 className="text-4xl font-bold font-space tracking-tight">{title}</h1>
          <p className="text-muted-foreground text-lg mt-1">
            {filter === 'all'
              ? 'All customer reviews'
              : filter === 'positive'
                ? 'Reviews with positive or very positive sentiment'
                : filter === 'negative'
                  ? 'Reviews with negative or very negative sentiment'
                  : 'Reviews flagged for human review'}
          </p>
        </div>

        <Separator className="mb-6" />

        <Card className="p-0 overflow-hidden">
          {isLoading && (
            <div className="flex items-center justify-center p-12 text-muted-foreground">
              Loading reviews...
            </div>
          )}
          {isError && (
            <div className="flex items-center justify-center p-12 text-destructive">
              Failed to load reviews. Make sure the server is running.
            </div>
          )}
          {!isLoading && !isError && reviews && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[60px]">ID</TableHead>
                    <TableHead className="min-w-[300px]">Review Text</TableHead>
                    <TableHead className="w-[130px]">Sentiment</TableHead>
                    <TableHead className="w-[90px] text-right">Score</TableHead>
                    <TableHead className="w-[120px]">Status</TableHead>
                    <TableHead className="min-w-[200px]">Chatbot Statement</TableHead>
                    <TableHead className="w-[160px]">Created</TableHead>
                    <TableHead className="w-[160px]">Processed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reviews.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        No reviews found
                      </TableCell>
                    </TableRow>
                  ) : (
                    reviews.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="font-mono text-sm">{r.id}</TableCell>
                        <TableCell className="text-sm max-w-[400px]">
                          <div className="line-clamp-3">{r.review_text}</div>
                        </TableCell>
                        <TableCell>{sentimentBadge(r.sentiment_category)}</TableCell>
                        <TableCell className={cn(
                          "text-right font-mono text-sm tabular-nums",
                          r.sentiment_score != null && r.sentiment_score > 0 && "text-green-600",
                          r.sentiment_score != null && r.sentiment_score < 0 && "text-red-500",
                        )}>
                          {r.sentiment_score != null ? r.sentiment_score.toFixed(3) : '—'}
                        </TableCell>
                        <TableCell>{statusBadge(r.status)}</TableCell>
                        <TableCell className="text-sm max-w-[300px]">
                          <div className="line-clamp-2">{r.chatbot_statement || '—'}</div>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {r.processed_at ? new Date(r.processed_at).toLocaleString() : '—'}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </Card>

        {!isLoading && reviews && (
          <p className="text-sm text-muted-foreground mt-3">
            Showing {reviews.length} review{reviews.length !== 1 ? 's' : ''}
          </p>
        )}
      </div>
    </motion.div>
  )
}

import { useState, useRef, useEffect } from 'react'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { PaperPlaneRight, Circle, ArrowClockwise } from '@phosphor-icons/react'
import { ChatMessage } from '@/lib/types'
import { cn } from '@/lib/utils'
import { motion, AnimatePresence } from 'framer-motion'
import { Skeleton } from '@/components/ui/skeleton'

interface ChatInterfaceProps {
  messages: ChatMessage[]
  onSendMessage: (content: string) => void
  isLoading: boolean
  onRefresh?: () => void
}

export function ChatInterface({ messages, onSendMessage, isLoading, onRefresh }: ChatInterfaceProps) {
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim() && !isLoading) {
      onSendMessage(input.trim())
      setInput('')
      inputRef.current?.focus()
    }
  }

  const formatTime = (timestamp: Date | string) => {
    const date = timestamp instanceof Date ? timestamp : new Date(timestamp)
    if (isNaN(date.getTime())) {
      return 'Invalid time'
    }
    return new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    }).format(date)
  }

  return (
    <Card className="flex flex-col h-full">
      <div className="p-4 border-b border-border flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold font-space">Analytics Assistant</h2>
          <div className="flex items-center gap-1.5">
            <Circle className="w-2 h-2 text-success fill-success animate-pulse-glow" weight="fill" />
            <span className="text-xs text-muted-foreground">Online</span>
          </div>
        </div>
        {onRefresh && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onRefresh}
            disabled={isLoading}
            className="h-8 w-8 p-0"
          >
            <ArrowClockwise className="w-4 h-4" weight="bold" />
          </Button>
        )}
      </div>

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full">
          <div className="p-4 space-y-3">
            <AnimatePresence initial={false}>
              {messages.map((message) => (
                <motion.div
                  key={message.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.25 }}
                  className={cn(
                    "flex gap-3",
                    message.role === 'user' ? "justify-end" : "justify-start"
                  )}
                >
                  <div
                    className={cn(
                      "max-w-[80%] rounded-lg p-3 shadow-sm",
                      message.role === 'user'
                        ? "bg-primary text-primary-foreground"
                        : "bg-card border border-border"
                    )}
                  >
                    <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                      {message.content}
                    </p>
                    <span className={cn(
                      "text-xs mt-1.5 block",
                      message.role === 'user' ? "text-primary-foreground/70" : "text-muted-foreground"
                    )}>
                      {formatTime(message.timestamp)}
                    </span>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            {isLoading && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex gap-3"
              >
                <div className="max-w-[80%] rounded-lg p-3 bg-card border border-border">
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-48" />
                    <Skeleton className="h-4 w-32" />
                  </div>
                </div>
              </motion.div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>
      </div>

      <form onSubmit={handleSubmit} className="p-4 border-t border-border shrink-0">
        <div className="flex gap-2">
          <Input
            ref={inputRef}
            type="text"
            placeholder="Ask about your data..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
            className="flex-1 font-inter"
            id="chat-input"
          />
          <Button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="px-4"
          >
            <PaperPlaneRight className="w-5 h-5" weight="bold" />
          </Button>
        </div>
      </form>
    </Card>
  )
}

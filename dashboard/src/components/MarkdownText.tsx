import { cn } from '@/lib/utils'

interface MarkdownTextProps {
  content: string
  /** Compact mode uses tighter spacing — suited for chat bubbles */
  compact?: boolean
  className?: string
}

/**
 * Lightweight markdown renderer for agent responses.
 * Supports: ## / ### / #### headings, **bold**, - / * bullets, numbered lists.
 */
export function MarkdownText({ content, compact = false, className }: MarkdownTextProps) {
  // Pre-process: ensure markdown markers start on their own line.
  // LLMs sometimes emit everything on a single line.
  const normalized = content
    .replace(/\s*(#{2,4}\s)/g, '\n$1')           // newline before ## / ### / ####
    .replace(/(?<!\n)([-*] \*\*)/g, '\n$1')       // newline before "- **" / "* **"
    .replace(/(?<!\n)(\d+\.\s)/g, '\n$1')         // newline before "1. "
    .trim()

  return (
    <div className={cn(compact ? '' : 'prose prose-sm dark:prose-invert max-w-none', className)}>
      {normalized.split('\n').map((line, i) => {
        const trimmed = line.trim()

        if (!trimmed) return <div key={i} className={compact ? 'h-1.5' : 'h-3'} />

        if (trimmed.startsWith('## '))
          return (
            <h2 key={i} className={cn('font-bold font-space', compact ? 'text-sm mt-3 mb-1.5' : 'text-xl mt-6 mb-3')}>
              {trimmed.slice(3)}
            </h2>
          )

        if (trimmed.startsWith('### '))
          return (
            <h3 key={i} className={cn('font-semibold font-space', compact ? 'text-sm mt-2 mb-1' : 'text-lg mt-4 mb-2')}>
              {trimmed.slice(4)}
            </h3>
          )

        if (trimmed.startsWith('#### '))
          return (
            <h4 key={i} className={cn('font-semibold font-space', compact ? 'text-sm mt-1.5 mb-0.5' : 'text-base mt-3 mb-1.5')}>
              {renderInlineFormatting(trimmed.slice(5))}
            </h4>
          )

        if (trimmed.startsWith('**') && trimmed.endsWith('**'))
          return (
            <p key={i} className={cn('font-semibold', compact ? 'mt-2 mb-0.5 text-sm' : 'mt-4 mb-1')}>
              {trimmed.slice(2, -2)}
            </p>
          )

        if (trimmed.startsWith('- ') || trimmed.startsWith('* '))
          return (
            <div key={i} className={cn('flex gap-2 ml-2', compact ? 'mb-0.5' : 'mb-1.5')}>
              <span className="text-primary mt-0.5 shrink-0">-</span>
              <p className="text-sm leading-relaxed">{renderInlineFormatting(trimmed.slice(2))}</p>
            </div>
          )

        if (/^\d+\.\s/.test(trimmed)) {
          const match = trimmed.match(/^(\d+)\.\s(.*)/)
          return (
            <div key={i} className={cn('flex gap-2 ml-2', compact ? 'mb-0.5' : 'mb-1.5')}>
              <span className="text-primary font-medium mt-0.5 shrink-0">{match?.[1]}.</span>
              <p className="text-sm leading-relaxed">{renderInlineFormatting(match?.[2] || '')}</p>
            </div>
          )
        }

        return (
          <p key={i} className={cn('text-sm leading-relaxed', compact ? 'mb-1' : 'mb-2')}>
            {renderInlineFormatting(trimmed)}
          </p>
        )
      })}
    </div>
  )
}

/** Render **bold** spans within a line of text. */
function renderInlineFormatting(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    return <span key={i}>{part}</span>
  })
}

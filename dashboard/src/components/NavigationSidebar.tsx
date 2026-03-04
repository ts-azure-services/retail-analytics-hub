import { ChartLine, Storefront, UsersThree, Package, Newspaper, ChatDots, UserCircle } from '@phosphor-icons/react'
import { cn } from '@/lib/utils'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export type TabId = 'digest' | 'main' | 'omnichannel' | 'customer-engagement' | 'inventory-replenishment' | 'customer-reviews'

export type Persona = 'Master' | 'C-Suite' | 'Inventory Specialist' | 'Customer Specialist' | 'Omni Specialist'

const personaTabs: Record<Persona, TabId[]> = {
  'Master': ['digest', 'main', 'omnichannel', 'customer-engagement', 'inventory-replenishment', 'customer-reviews'],
  'C-Suite': ['digest', 'main'],
  'Inventory Specialist': ['inventory-replenishment'],
  'Customer Specialist': ['customer-engagement', 'customer-reviews'],
  'Omni Specialist': ['omnichannel'],
}

export function getDefaultTabForPersona(persona: Persona): TabId {
  return personaTabs[persona][0]
}

interface Tab {
  id: TabId
  label: string
  icon: React.ReactNode
}

interface NavigationSidebarProps {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  persona: Persona
  onPersonaChange: (persona: Persona) => void
}

const tabs: Tab[] = [
  {
    id: 'digest',
    label: 'Digest',
    icon: <Newspaper className="w-5 h-5" weight="bold" />,
  },
  {
    id: 'main',
    label: 'Main',
    icon: <ChartLine className="w-5 h-5" weight="bold" />,
  },
  {
    id: 'omnichannel',
    label: 'Omnichannel',
    icon: <Storefront className="w-5 h-5" weight="bold" />,
  },
  {
    id: 'customer-engagement',
    label: 'Customer Engagement',
    icon: <UsersThree className="w-5 h-5" weight="bold" />,
  },
  {
    id: 'inventory-replenishment',
    label: 'Inventory Replenishment',
    icon: <Package className="w-5 h-5" weight="bold" />,
  },
  {
    id: 'customer-reviews',
    label: 'Customer Reviews',
    icon: <ChatDots className="w-5 h-5" weight="bold" />,
  },
]

const personas: Persona[] = ['Master', 'C-Suite', 'Inventory Specialist', 'Customer Specialist', 'Omni Specialist']

export function NavigationSidebar({ activeTab, onTabChange, persona, onPersonaChange }: NavigationSidebarProps) {
  const visibleTabs = tabs.filter((tab) => personaTabs[persona].includes(tab.id))

  return (
    <div className="w-64 bg-card border-r border-border flex flex-col">
      <div className="p-6 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary rounded-lg">
            <ChartLine className="w-6 h-6 text-primary-foreground" weight="bold" />
          </div>
          <div>
            <h2 className="font-bold text-lg">Analytics Hub</h2>
            <p className="text-xs text-muted-foreground">Retail Insights</p>
          </div>
        </div>
      </div>

      <div className="px-4 pt-4 pb-2">
        <label className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground mb-1.5">
          <UserCircle className="w-3.5 h-3.5" weight="bold" />
          Persona
        </label>
        <Select value={persona} onValueChange={(v) => onPersonaChange(v as Persona)}>
          <SelectTrigger size="sm" className="w-full text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {personas.map((p) => (
              <SelectItem key={p} value={p}>{p}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <nav className="flex-1 p-4 space-y-2">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              'w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-all duration-200',
              activeTab === tab.id
                ? 'bg-primary text-primary-foreground shadow-md'
                : 'hover:bg-muted text-foreground'
            )}
          >
            <div className="flex-shrink-0">{tab.icon}</div>
            <span className="font-medium text-sm">{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  )
}

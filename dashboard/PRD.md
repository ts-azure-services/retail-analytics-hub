# Planning Guide

A real-time retail analytics hub with multi-tab navigation that visualizes key performance metrics through dynamic tiles and provides an AI-powered chat interface for querying data and generating insights. The application supports multiple specialized dashboards: Main (overall metrics), Omnichannel (cross-channel performance), Customer Engagement (loyalty and interactions), and Inventory Replenishment (stock management).

**Experience Qualities**: 
1. **Responsive** - Metrics update in real-time without user intervention, creating a live pulse of business operations across all dashboard tabs
2. **Intelligent** - Context-aware natural language chat interface that understands which dashboard view the user is on and provides relevant insights
3. **Organized** - Multi-tab navigation with sidebar provides clear separation between different analytical focuses while maintaining visual consistency

**Complexity Level**: Complex Application (advanced functionality, likely with multiple views)
  - This is a data-intensive dashboard with real-time updates, multiple specialized metric dashboards, context-aware AI chat, drill-down capabilities, and integrated navigation requiring sophisticated state management.

## Essential Features

### Multi-Tab Navigation
- **Functionality**: Left sidebar with four selectable tabs (Main, Omnichannel, Customer Engagement, Inventory Replenishment), each displaying a specialized dashboard
- **Purpose**: Organize different analytical perspectives into focused, navigable sections
- **Trigger**: User clicks on a tab in the left sidebar
- **Progression**: App loads on Main tab → User clicks tab button → Dashboard content swaps to show new metrics → Chat context updates to new tab → Visual indicator shows active tab
- **Success criteria**: Tab switching is instant, active tab is clearly indicated, each tab has unique metrics relevant to its focus, chat maintains separate history per tab

### Real-Time Metric Tiles
- **Functionality**: Display 8 key metrics per dashboard tab in card-based tiles that auto-refresh (32 total metrics across all tabs)
- **Purpose**: Provide comprehensive at-a-glance business health monitoring without manual refreshing for each analytical focus area
- **Trigger**: Page load and periodic automatic updates (every 5 seconds)
- **Progression**: Tab loads → Tiles populate with latest data → Data refreshes automatically → Visual indicators show changes (increase/decrease arrows, color shifts) → User can click any tile to see detailed breakdown
- **Success criteria**: Tiles update smoothly without flicker, changes are visually obvious, no stale data displayed, all metrics per tab visible and functional

### Analytics Chat Interface
- **Functionality**: Context-aware natural language chat where users ask questions about retail data and receive AI-generated insights specific to the active dashboard tab
- **Purpose**: Enable non-technical users to query complex data through conversation with automatic context understanding
- **Trigger**: User clicks chat button/panel, types question, sends message
- **Progression**: User opens chat → Types question ("Why is conversion down?") → Message sent with current tab context → AI analyzes query + relevant metrics for active dashboard → Response streams back with tab-specific insights → Chat history persists per tab
- **Success criteria**: Responses arrive within 3 seconds, answers reference metrics from active tab, conversation history is maintained separately per tab, switching tabs shows relevant chat history

### Metric Detail Views
- **Functionality**: Each metric tile is clickable and navigates to a detailed breakdown view showing key drivers, contribution percentages, trends, and insights
- **Purpose**: Allow users to drill down into what's driving each high-level metric
- **Trigger**: User clicks on any metric tile
- **Progression**: User clicks tile → Transition to detail view → Shows metric breakdown with driver cards, insights, and back button → User clicks back to return to main dashboard
- **Success criteria**: Smooth navigation between views, detailed data is informative, back navigation preserves dashboard state

### Trend Visualization
- **Functionality**: Each metric tile can expand to show historical trend data in sparkline or mini-chart form
- **Purpose**: Provide context for current numbers (is this good or bad compared to yesterday/last week?)
- **Trigger**: User hovers over or clicks metric tile
- **Progression**: User interacts with tile → Tooltip or expanded view shows → Mini chart renders with last 7-30 data points → User can see trend direction
- **Success criteria**: Charts render instantly from cached historical data, trends are visually clear

## Edge Case Handling

- **Connection Loss**: Display "Last updated X minutes ago" indicator; queue failed updates to retry when connection restored
- **Invalid Chat Queries**: AI responds gracefully to unclear questions with clarifying prompts rather than errors
- **Missing Data**: Show "N/A" or placeholder with explanation when specific metrics aren't available
- **Extreme Values**: Large numbers format with abbreviations (1.2M instead of 1,200,000); very long chat responses truncate with "Read more" expansion
- **Concurrent Users**: Changes to dashboard layout by one session don't affect other active sessions until they refresh
- **Slow API Response**: Show skeleton loaders on tiles during initial load; show subtle pulse animation during updates

## Design Direction

The design should evoke confidence, clarity, and sophistication—like a high-end financial terminal meets modern SaaS elegance. Users should feel informed and in control, with data presented authoritatively but not overwhelmingly. The interface should feel premium and professional while remaining approachable.

## Color Selection

A sophisticated data-focused palette with strong contrast and professional polish, using deep blues and vibrant accents to convey trust and energy.

- **Primary Color**: Deep ocean blue `oklch(0.35 0.12 250)` - Conveys trust, stability, and data authority; used for primary actions and key UI elements
- **Secondary Colors**: 
  - Cool slate `oklch(0.25 0.02 250)` - For secondary surfaces and cards, provides depth without distraction
  - Light cloud `oklch(0.96 0.005 250)` - For backgrounds and subtle separators
- **Accent Color**: Electric cyan `oklch(0.65 0.18 210)` - Attention-grabbing highlight for CTAs, positive changes, and interactive elements
- **Foreground/Background Pairings**: 
  - Background (Light cloud oklch(0.96 0.005 250)): Foreground text oklch(0.2 0.02 250) - Ratio 11.8:1 ✓
  - Primary (Deep ocean blue oklch(0.35 0.12 250)): White text oklch(1 0 0) - Ratio 6.1:1 ✓
  - Accent (Electric cyan oklch(0.65 0.18 210)): Dark text oklch(0.2 0.02 250) - Ratio 7.2:1 ✓
  - Card (Cool slate oklch(0.25 0.02 250)): White text oklch(1 0 0) - Ratio 10.5:1 ✓
  - Success green oklch(0.6 0.15 145): White text - Ratio 4.8:1 ✓
  - Warning amber oklch(0.7 0.15 75): Dark text oklch(0.2 0.02 250) - Ratio 8.5:1 ✓

## Font Selection

The typeface should communicate precision, modernity, and data clarity—readable at small sizes for dense information while maintaining character for headings.

- **Typographic Hierarchy**: 
  - H1 (Dashboard Title): Space Grotesk Bold / 32px / -0.02em letter spacing / leading-tight
  - H2 (Section Headers): Space Grotesk Semibold / 20px / -0.01em letter spacing / leading-snug
  - Metric Values: JetBrains Mono Bold / 36px / tabular-nums / leading-none
  - Metric Labels: Space Grotesk Medium / 14px / 0em letter spacing / uppercase / leading-normal
  - Body Text (Chat): Inter Regular / 15px / 0em letter spacing / leading-relaxed
  - Chat Timestamps: Inter Regular / 12px / 0.01em letter spacing / text-muted-foreground

## Animations

Animations should reinforce the "live data" feeling with subtle pulsing on updates and smooth transitions between states. Metric changes should animate numerically (counting up/down) to emphasize movement. Chat messages should slide in conversationally. All animations fast and functional—nothing gratuitous.

- Metric value changes: Number counter animation (400ms ease-out) + subtle scale pulse (0.98 → 1.0)
- Tile updates: Brief border glow in accent color (300ms) when new data arrives
- Chat messages: Slide up with fade-in (250ms ease-out) for new messages
- Tile expansion: Smooth height transition (350ms ease-in-out) when showing trend charts
- Loading states: Gentle pulse animation on skeleton loaders (1.5s infinite)

## Component Selection

- **Components**: 
  - Cards (shadcn) - Primary container for metric tiles with custom gradient borders
  - Dialog (shadcn) - For metric configuration/settings modal
  - ScrollArea (shadcn) - For chat message history with smooth scrolling
  - Tooltip (shadcn) - For showing additional context on hover over metrics
  - Skeleton (shadcn) - Loading states for tiles before data arrives
  - Separator (shadcn) - Visual dividers between dashboard sections
  - Input (shadcn) - Chat message input with send button
  - Badge (shadcn) - Status indicators (live, updated, stale) on tiles
  - Button (shadcn) - Primary and secondary actions throughout
  
- **Customizations**: 
  - Metric Tile component - Custom card with large numeric display, label, trend indicator (arrow + percentage), and mini sparkline using D3
  - Chat Bubble component - Custom message container with sender avatar, timestamp, and markdown support
  - Real-time Indicator - Custom pulsing dot component showing live connection status
  
- **States**: 
  - Buttons: Default solid primary → hover lift + brightness increase → active scale(0.98) → focus ring in accent
  - Metric tiles: Default card → hover subtle lift shadow → loading skeleton overlay → updated state brief accent glow
  - Chat input: Default border-input → focus border-accent + ring → sending disabled state → error border-destructive
  - Tiles with alerts: Destructive border for negative thresholds, success border for positive milestones
  
- **Icon Selection**: 
  - TrendUp/TrendDown (phosphor) - Metric change indicators
  - ChartLine (phosphor) - Analytics/data visualization
  - ChatCircle (phosphor) - Chat interface toggle
  - Circle (phosphor) - Real-time status indicator (pulsing when live)
  - ArrowClockwise (phosphor) - Manual refresh action
  - Gear (phosphor) - Settings/configuration
  - PaperPlaneRight (phosphor) - Send chat message
  - CaretRight (phosphor) - Expand tile for details
  
- **Spacing**: 
  - Dashboard grid: gap-6 between tiles
  - Card padding: p-6 for metric tiles, p-4 for chat messages
  - Section spacing: space-y-8 between major dashboard sections
  - Chat messages: space-y-3 between bubbles
  - Button padding: px-6 py-3 for primary, px-4 py-2 for secondary
  
- **Mobile**: 
  - Desktop (>1024px): 4-column metric grid with sidebar chat panel
  - Tablet (768-1023px): 2-column metric grid, chat becomes overlay sheet from bottom
  - Mobile (<768px): Single column metric tiles, chat full-screen modal, simplified tile details
  - Metric values scale down slightly on mobile (32px instead of 36px)
  - Chat input becomes sticky bottom bar on mobile
  - Hamburger menu for dashboard settings on mobile

# Workflows

The simulation models three retail domains. Each workflow runs as a set of SimPy processes that generate events over a configurable time horizon, persisting structured data to DuckDB for downstream analysis and ML training.

## Omnichannel Purchase

Simulates customer shopping journeys from arrival through checkout and fulfillment across three channels: online, in-store, and BOPIS (buy-online-pick-up-in-store).

### Process Flow

1. **Arrival** — Customers arrive via Poisson processes at channel-specific rates
2. **Browsing** — Exponentially-distributed browsing duration; basket is built during this phase
3. **Queue & Checkout** — In-store customers enter a checkout queue with balking behavior (leave if the queue exceeds a threshold); online customers proceed directly
4. **Cart Abandonment** — Probabilistic abandonment based on channel, wait time, and basket characteristics
5. **Payment** — Payment method selection, with configurable failure and retry rates
6. **Fulfillment** — Order processing with carrier assignment and SLA tracking

### Key Metrics

- Conversion rate, average order value, revenue
- Queue wait times, balking rate
- Fulfillment SLA compliance, fulfillment duration

### Data Tables

- `customer_journeys` — Individual journey records with features and outcomes
- `order_metrics` — Order-level fulfillment data
- `hourly_demand` — Aggregated demand by hour and channel

---

## Inventory Replenishment

Simulates supply chain operations for a product catalog: demand depletion, reorder triggers, supplier deliveries, and inventory auditing.

### Process Flow

1. **Demand Depletion** — Stochastic consumption driven by customer purchases from the omnichannel workflow
2. **Reorder Point Monitoring** — Continuous-review (s, Q) policy: when stock falls to the reorder point, a purchase order is generated
3. **Purchase Order Generation** — Automatic PO creation with quantity based on economic order quantity
4. **Supplier Delivery** — Variable lead times modeled per supplier, with reliability and short-shipment probability
5. **Goods Receipt** — Receiving with potential quantity discrepancies
6. **Shrinkage** — Daily inventory loss simulation (theft, damage, expiry)

### Key Metrics

- Fill rate, stockout count and duration
- Average lead time, supplier on-time rate
- Inventory turnover, shrinkage rate

### Data Tables

- `inventory_events` — Stock movements and stockout events
- `supplier_deliveries` — PO fulfillment with lead time actuals
- `inventory_snapshots` — Daily inventory positions per product

---

## Customer Engagement

Simulates CRM and loyalty operations: customer lifecycle management, campaign execution, loyalty programs, and churn prevention.

### Process Flow

1. **Customer Lifecycle** — State machine transitions: New → Active → Lapsed → Churned, driven by purchase recency and engagement signals
2. **RFM Segmentation** — Periodic recency/frequency/monetary scoring to assign value tiers (High, Medium, Low)
3. **Campaign Execution** — Scheduled and event-triggered campaigns (email, SMS, push) with channel-specific send logic
4. **Response Simulation** — Open, click, and conversion probabilities conditioned on campaign type, customer segment, and fatigue
5. **Loyalty Program** — Points accrual on purchases and periodic multiplier promotions; redemption at configurable thresholds
6. **Churn Prevention** — Risk scoring based on engagement decay; automatic retention campaign triggers
7. **Service Tickets** — Issue creation and resolution, with impact on satisfaction and churn probability

### Key Metrics

- Churn rate, retention rate
- Campaign response rate (open, click, conversion)
- Customer lifetime value, loyalty redemption rate
- Service ticket resolution time

### Data Tables

- `customer_snapshots` — Customer state at simulation end (segment, tier, lifetime value, churn status)
- `campaign_interactions` — Campaign send/response records

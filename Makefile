##@ Data Seeding
seed-local: ## [core] Seed local DuckDB databases (no Azure needed)
	@echo ""
	@echo "============================================================"
	@echo "🌱 Seeding Local DuckDB Databases"
	@echo "============================================================"
	@echo ""
	@cd seed-data && uv run seed_local.py --clean
	@echo ""

clean-local: ## [util] Delete local DuckDB database files
	@echo "🗑  Removing local DuckDB files..."
	@rm -f local_postgres.duckdb local_postgres.duckdb.wal
	@rm -f local_cosmos.duckdb local_cosmos.duckdb.wal
	@echo "✓ Local databases removed"

seed-cosmos: ## [util] Seed CosmosDB with 100 customer records (profile, contact, address, account info, tags)
	cd seed-data && uv run seed_cosmos.py

seed-postgres: ## [util] Seed PostgreSQL e-commerce data: 50 products, 100 orders with order items
	cd seed-data && uv run seed_postgres.py

seed-all: ## [util] Seed all databases: CosmosDB (customers) + PostgreSQL (products/orders)
	@echo ""
	@echo "============================================================"
	@echo "🌱 Starting Data Seeding Process"
	@echo "============================================================"
	@echo ""
	@echo "Phase 1: CosmosDB"
	@cd seed-data && uv run seed_cosmos.py || echo "⚠ CosmosDB seeding failed, continuing with PostgreSQL..."
	@echo ""
	@echo "Phase 2: PostgreSQL"
	@cd seed-data && uv run seed_postgres.py || (echo "✗ PostgreSQL seeding failed!" && exit 1)
	@echo ""
	@echo "============================================================"
	@echo "✓ All seeding operations completed!"
	@echo "============================================================"
	@echo ""

seed-historical: ## [util] Generate historical data for Fabric notebooks
	@echo ""
	@echo "============================================================"
	@echo "📊 Generating Historical Data for Analytics"
	@echo "============================================================"
	@echo ""
	@echo "This generates inventory events to support forecasting, reorder point recommendations."
	@echo ""
	@cd seed-data && uv run seed_cosmos.py --historical --days 30 --skip-base
	@echo ""
	@echo "============================================================"
	@echo "✓ Historical data generation completed!"
	@echo "============================================================"

seed-all-with-history: ## [core] ② Full seed: base data + historical data for analytics
	@echo ""
	@echo "============================================================"
	@echo "🌱 Full Data Seeding (Base + Historical)"
	@echo "============================================================"
	@echo ""
	@echo "Phase 1: PostgreSQL foundation (suppliers, products)"
	@cd seed-data && uv run seed_postgres.py --phase 1 || (echo "✗ Phase 1 failed!" && exit 1)
	@echo ""
	@echo "Phase 2: CosmosDB customers (source of truth)"
	@cd seed-data && uv run seed_cosmos.py --customers-only || (echo "✗ Phase 2 failed!" && exit 1)
	@echo ""
	@echo "Phase 3: PostgreSQL dependencies (import customers, policies, orders)"
	@cd seed-data && uv run seed_postgres.py --phase 2 || (echo "✗ Phase 3 failed!" && exit 1)
	@echo ""
	@echo "Phase 4: CosmosDB dependencies (carts, events + 30 days history)"
	@cd seed-data && uv run seed_cosmos.py --skip-customers --historical --days 30 || (echo "✗ Phase 4 failed!" && exit 1)
	@echo "============================================================"
	@echo "✓ All seeding operations completed!"
	@echo "============================================================"
	@echo ""

cleanse-data-force: ## [util] Clean all data WITHOUT confirmation (use with caution!)
	@echo ""
	@echo "============================================================"
	@echo "🧹 Data Cleansing - Reset to Empty State (FORCE)"
	@echo "============================================================"
	@echo ""
	@echo "Phase 1: Cleaning PostgreSQL..."
	@cd seed-data && uv run cleanup_postgres.py || echo "⚠ PostgreSQL cleanup failed"
	@echo ""
	@echo "Phase 2: Cleaning CosmosDB..."
	@cd seed-data && uv run cleanup_cosmos.py || echo "⚠ CosmosDB cleanup failed"
	@echo ""
	@echo "============================================================"
	@echo "✓ Data cleansing completed!"
	@echo "============================================================"
	@echo ""

validate-all: ## [util] Validate data in all databases (CosmosDB + PostgreSQL + local DuckDB)
	uv run seed-data/validate_data.py --all

validate-local: ## [core] Validate local DuckDB databases (tables, schema, row counts)
	uv run seed-data/validate_data.py --local

## Validate CosmosDB data (count documents, show samples)
validate-cosmos:
	uv run seed-data/validate_data.py --cosmos

## Validate PostgreSQL data (count rows, show samples)
validate-postgres:
	uv run seed-data/validate_data.py --postgres


##@ Parameter Sweeps & ML

# Omnichannel workflow sweeps
run-sweep-conversion: ## [core] Run conversion parameter sweep (36 scenarios)
	@echo "🔄 Running conversion parameter sweep..."
	uv run python -m simulation.run_simulation --sweep conversion --sweep-type grid

run-sweep-demand: ## [util] Run demand pattern sweep (36 scenarios)
	@echo "🔄 Running demand parameter sweep..."
	uv run python -m simulation.run_simulation --sweep demand --sweep-type grid

run-sweep-fulfillment: ## [util] Run fulfillment parameter sweep (27 scenarios)
	@echo "🔄 Running fulfillment parameter sweep..."
	uv run python -m simulation.run_simulation --sweep fulfillment --sweep-type grid

# Inventory workflow sweeps
run-sweep-inventory-supply: ## [util] Run inventory supply chain sweep (27 scenarios)
	@echo "📦 Running inventory supply parameter sweep..."
	uv run python -m simulation.run_simulation --sweep inventory_supply --sweep-type grid

run-sweep-inventory-policy: ## [util] Run inventory policy sweep (27 scenarios)
	@echo "📦 Running inventory policy parameter sweep..."
	uv run python -m simulation.run_simulation --sweep inventory_policy --sweep-type grid

run-sweep-inventory-demand: ## [util] Run inventory demand sweep (27 scenarios)
	@echo "📦 Running inventory demand parameter sweep..."
	uv run python -m simulation.run_simulation --sweep inventory_demand --sweep-type grid

# Engagement workflow sweeps
run-sweep-engagement-campaign: ## [util] Run engagement campaign sweep (27 scenarios)
	@echo "👥 Running engagement campaign parameter sweep..."
	uv run python -m simulation.run_simulation --sweep engagement_campaign --sweep-type grid

run-sweep-engagement-retention: ## [util] Run engagement retention sweep (27 scenarios)
	@echo "👥 Running engagement retention parameter sweep..."
	uv run python -m simulation.run_simulation --sweep engagement_retention --sweep-type grid

run-sweep-engagement-loyalty: ## [util] Run engagement loyalty sweep (27 scenarios)
	@echo "👥 Running engagement loyalty parameter sweep..."
	uv run python -m simulation.run_simulation --sweep engagement_loyalty --sweep-type grid

# Sweep reporting
sweep-report: ## [core] Report which sweep combos produced most volume & variety of data
	uv run python analysis/sweep_report.py

sweep-report-top5: ## [util] Sweep report showing top 5 per sweep
	uv run python analysis/sweep_report.py --top 5

sweep-recommend: ## [core] Generate recommendations from sweep results
	uv run python analysis/sweep_recommend.py --output recommendations.json

sweep-recommend-preview: ## [util] Preview what sweep recommendations would change
	uv run python analysis/config_applier.py --preview recommendations.json

sweep-apply: ## [core] Apply sweep recommendations to config
	uv run python analysis/config_applier.py --apply recommendations.json

# ML training
train-models: ## [core] Train ML models on simulation data
	@echo "🤖 Training ML models..."
	uv run python analysis/train_models.py --scenarios all

train-models-omnichannel: ## [util] Train only omnichannel ML models
	@echo "🤖 Training omnichannel ML models..."
	uv run python analysis/train_models.py --model-group omnichannel

train-models-inventory: ## [util] Train only inventory ML models
	@echo "🤖 Training inventory ML models..."
	uv run python analysis/train_models.py --model-group inventory

train-models-engagement: ## [util] Train only engagement ML models
	@echo "🤖 Training engagement ML models..."
	uv run python analysis/train_models.py --model-group engagement


##@ Simulation Setup & Execution
run-simulation-quick: ## [util] Run quick 1-hour test simulation
	@echo "⚡ Running 1-hour test simulation..."
	uv run python -m simulation.run_simulation --duration 1 --seed 42

run-omnichannel: ## [util] Run omnichannel workflow only (usage: make run-omnichannel HOURS=1)
	@HOURS=$${HOURS:-1}; \
	echo "🛒 Running omnichannel workflow for $$HOURS hour(s)..."; \
	uv run python -m simulation.run_simulation --workflow omnichannel --duration $$HOURS

run-inventory-workflow: ## [util] Run inventory replenishment workflow (usage: make run-inventory-workflow HOURS=1)
	@HOURS=$${HOURS:-1}; \
	echo "📦 Running inventory replenishment workflow for $$HOURS hour(s)..."; \
	uv run python -m simulation.run_simulation --workflow inventory --duration $$HOURS

run-engagement-workflow: ## [util] Run customer engagement & personalization workflow (usage: make run-engagement-workflow HOURS=1)
	@HOURS=$${HOURS:-1}; \
	echo "👥 Running customer engagement workflow for $$HOURS hour(s)..."; \
	uv run python -m simulation.run_simulation --workflow engagement --duration $$HOURS

run-all-workflows: ## [core] Run all workflows together (omnichannel + inventory + engagement)
	@HOURS=$${HOURS:-1}; \
	echo "🚀 Running all workflows (omnichannel + inventory + engagement) for $$HOURS hour(s)..."; \
	uv run python -m simulation.run_simulation --workflow all --duration $$HOURS

clean-simulation: ## [util] Reset databases (cleanse + re-seed)
	@echo "🧹 Cleaning and re-seeding databases..."
	@make cleanse-data-force
	@make seed-all-with-history


##@ Help
help: ## Show this help message (grouped by sections)
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1;35m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_.-]+:.*?## \[core\]/ {gsub(/\[core\] */, "", $$2); printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## \[util\]/ {gsub(/\[util\] */, "", $$2); printf "  \033[33m%-30s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)

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

SWEEPS_DIR = sweeps

# Helper: copy seed DBs into an isolated sweep DB pair, then run the sweep.
# When called directly (make run-sweep-X), output goes to terminal.
# Usage: $(call run-isolated-sweep,<sweep-name>)
define run-isolated-sweep
@mkdir -p $(SWEEPS_DIR)
@cp local_postgres.duckdb $(SWEEPS_DIR)/$(1)_postgres.duckdb
@cp local_cosmos.duckdb $(SWEEPS_DIR)/$(1)_cosmos.duckdb
LOCAL_POSTGRES_DB=$(CURDIR)/$(SWEEPS_DIR)/$(1)_postgres.duckdb \
LOCAL_COSMOS_DB=$(CURDIR)/$(SWEEPS_DIR)/$(1)_cosmos.duckdb \
uv run python -m simulation.run_simulation --sweep $(1) --sweep-type grid
endef

# Helper: same as above but redirects output to a log file (for parallel runs).
# Usage: $(call run-isolated-sweep-logged,<sweep-name>)
define run-isolated-sweep-logged
@mkdir -p $(SWEEPS_DIR)
@cp local_postgres.duckdb $(SWEEPS_DIR)/$(1)_postgres.duckdb
@cp local_cosmos.duckdb $(SWEEPS_DIR)/$(1)_cosmos.duckdb
LOCAL_POSTGRES_DB=$(CURDIR)/$(SWEEPS_DIR)/$(1)_postgres.duckdb \
LOCAL_COSMOS_DB=$(CURDIR)/$(SWEEPS_DIR)/$(1)_cosmos.duckdb \
uv run python -m simulation.run_simulation --sweep $(1) --sweep-type grid \
> $(SWEEPS_DIR)/$(1).log 2>&1
endef

ALL_SWEEPS = conversion demand fulfillment \
             inventory_supply inventory_policy inventory_demand \
             engagement_campaign engagement_retention engagement_loyalty

# Omnichannel workflow sweeps
run-sweep-conversion: ## [util] Run conversion parameter sweep (36 scenarios)
	@echo "🔄 Running conversion parameter sweep..."
	$(call run-isolated-sweep,conversion)

run-sweep-demand: ## [util] Run demand pattern sweep (36 scenarios)
	@echo "🔄 Running demand parameter sweep..."
	$(call run-isolated-sweep,demand)

run-sweep-fulfillment: ## [util] Run fulfillment parameter sweep (27 scenarios)
	@echo "🔄 Running fulfillment parameter sweep..."
	$(call run-isolated-sweep,fulfillment)

# Inventory workflow sweeps
run-sweep-inventory-supply: ## [util] Run inventory supply chain sweep (27 scenarios)
	@echo "📦 Running inventory supply parameter sweep..."
	$(call run-isolated-sweep,inventory_supply)

run-sweep-inventory-policy: ## [util] Run inventory policy sweep (27 scenarios)
	@echo "📦 Running inventory policy parameter sweep..."
	$(call run-isolated-sweep,inventory_policy)

run-sweep-inventory-demand: ## [util] Run inventory demand sweep (27 scenarios)
	@echo "📦 Running inventory demand parameter sweep..."
	$(call run-isolated-sweep,inventory_demand)

# Engagement workflow sweeps
run-sweep-engagement-campaign: ## [util] Run engagement campaign sweep (27 scenarios)
	@echo "👥 Running engagement campaign parameter sweep..."
	$(call run-isolated-sweep,engagement_campaign)

run-sweep-engagement-retention: ## [util] Run engagement retention sweep (27 scenarios)
	@echo "👥 Running engagement retention parameter sweep..."
	$(call run-isolated-sweep,engagement_retention)

run-sweep-engagement-loyalty: ## [util] Run engagement loyalty sweep (27 scenarios)
	@echo "👥 Running engagement loyalty parameter sweep..."
	$(call run-isolated-sweep,engagement_loyalty)

# Run all sweeps in parallel with per-sweep log files and live progress
run-all-sweeps: ## [core] Run ALL 9 parameter sweeps in parallel (isolated DBs)
	@echo ""
	@echo "============================================================"
	@echo "🚀 Launching all 9 sweeps in parallel..."
	@echo "============================================================"
	@echo "Logs: $(SWEEPS_DIR)/<sweep>.log"
	@echo ""
	@mkdir -p $(SWEEPS_DIR)
	@# Launch each sweep as a background process with its own log
	@for s in $(ALL_SWEEPS); do \
		cp local_postgres.duckdb $(SWEEPS_DIR)/$${s}_postgres.duckdb; \
		cp local_cosmos.duckdb $(SWEEPS_DIR)/$${s}_cosmos.duckdb; \
		LOCAL_POSTGRES_DB=$(CURDIR)/$(SWEEPS_DIR)/$${s}_postgres.duckdb \
		LOCAL_COSMOS_DB=$(CURDIR)/$(SWEEPS_DIR)/$${s}_cosmos.duckdb \
		uv run python -m simulation.run_simulation --sweep $$s --sweep-type grid \
			> $(SWEEPS_DIR)/$$s.log 2>&1 & \
		echo "  Started: $$s (pid $$!)"; \
	done; \
	echo ""; \
	echo "Waiting for all sweeps to finish..."; \
	echo "  Tip: tail -f $(SWEEPS_DIR)/<sweep>.log to watch a specific sweep"; \
	echo ""; \
	FAIL=0; \
	wait || FAIL=1; \
	echo "============================================================"; \
	echo "RESULTS"; \
	echo "============================================================"; \
	for s in $(ALL_SWEEPS); do \
		if [ -f $(SWEEPS_DIR)/$$s.log ]; then \
			if grep -q "SWEEP COMPLETE" $(SWEEPS_DIR)/$$s.log 2>/dev/null; then \
				SCENARIOS=$$(grep -c "^  Completed " $(SWEEPS_DIR)/$$s.log 2>/dev/null || echo 0); \
				printf "  ✓ %-28s %s scenarios\n" "$$s" "$$SCENARIOS"; \
			else \
				printf "  ✗ %-28s FAILED (see %s/%s.log)\n" "$$s" "$(SWEEPS_DIR)" "$$s"; \
				FAIL=1; \
			fi; \
		else \
			printf "  ? %-28s no log found\n" "$$s"; \
			FAIL=1; \
		fi; \
	done; \
	echo "============================================================"; \
	if [ $$FAIL -eq 0 ]; then \
		echo "✓ All sweeps complete. Run 'make merge-sweeps' to consolidate."; \
	else \
		echo "⚠ Some sweeps failed. Check logs in $(SWEEPS_DIR)/*.log"; \
	fi; \
	echo "============================================================"; \
	echo ""

# Check sweep progress (run from another terminal while sweeps are in-flight)
sweep-status: ## [core] Show progress of running/completed sweeps
	@echo ""
	@echo "============================================================"
	@echo "SWEEP STATUS"
	@echo "============================================================"
	@for s in $(ALL_SWEEPS); do \
		if [ -f $(SWEEPS_DIR)/$$s.log ]; then \
			if grep -q "SWEEP COMPLETE" $(SWEEPS_DIR)/$$s.log 2>/dev/null; then \
				SCENARIOS=$$(grep -c "^  Completed " $(SWEEPS_DIR)/$$s.log 2>/dev/null || echo 0); \
				printf "  ✓ %-28s done  (%s scenarios)\n" "$$s" "$$SCENARIOS"; \
			elif grep -q "FAILED" $(SWEEPS_DIR)/$$s.log 2>/dev/null; then \
				printf "  ✗ %-28s FAILED\n" "$$s"; \
			else \
				LAST=$$(grep "^\[" $(SWEEPS_DIR)/$$s.log 2>/dev/null | tail -1); \
				printf "  ⏳ %-28s %s\n" "$$s" "$$LAST"; \
			fi; \
		else \
			printf "  - %-28s not started\n" "$$s"; \
		fi; \
	done
	@echo "============================================================"
	@echo ""

# Sweep merge & cleanup
merge-sweeps: ## [core] Merge all sweep results into main databases
	uv run seed-data/merge_sweeps.py

merge-sweeps-dry: ## [util] Preview what merge-sweeps would do (no writes)
	uv run seed-data/merge_sweeps.py --dry-run

clean-sweeps: ## [core] Remove sweep-isolated database files
	@echo "🗑  Removing sweep databases..."
	@rm -rf $(SWEEPS_DIR)
	@echo "✓ Sweep databases removed"

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


##@ Dashboard
dashboard-install: ## [util] Install dashboard npm dependencies
	@echo "📦 Installing dashboard dependencies..."
	@cd dashboard && npm install
	@echo "✓ Dashboard dependencies installed"

dashboard-server: ## [core] Start dashboard API server (DuckDB → REST on port 3001)
	@echo "🔌 Starting dashboard API server..."
	@echo "   DB: local_postgres.duckdb → http://localhost:3001"
	@cd dashboard && npm run dev:server

dashboard-dev: ## [util] Start dashboard Vite frontend only (port 5173)
	@echo "🖥  Starting dashboard dev server..."
	@cd dashboard && npm run dev

dashboard-start: ## [core] Start API server + Vite frontend together
	@echo "🚀 Starting dashboard (API + frontend)..."
	@echo "   API:      http://localhost:3001"
	@echo "   Frontend: http://localhost:5173"
	@cd dashboard && npm run dev:all

dashboard-stop: ## [util] Stop dashboard server and frontend processes
	@echo "🛑 Stopping dashboard processes..."
	@lsof -ti :3001 | xargs kill 2>/dev/null || true
	@lsof -ti :5173 | xargs kill 2>/dev/null || true
	@echo "✓ Dashboard processes stopped"

dashboard-build: ## [core] Production build of the dashboard
	@echo "🔨 Building dashboard..."
	@cd dashboard && npm run build
	@echo "✓ Dashboard built to dashboard/dist/"

dashboard-preview: ## [util] Preview production build locally
	@echo "👀 Previewing dashboard production build..."
	@cd dashboard && npm run preview

dashboard-audit-fix: ## [util] Fix npm audit vulnerabilities
	@cd dashboard && npm audit fix


##@ Agents
agents-build: ## [core] Build agent Docker images
	docker compose -f agents/docker-compose.yml build

agents-up: ## [core] Start agent services (detached)
	docker compose -f agents/docker-compose.yml up -d

agents-down: ## [core] Stop agent services
	docker compose -f agents/docker-compose.yml down

agents-logs: ## [util] Tail agent service logs
	docker compose -f agents/docker-compose.yml logs -f


##@ Help
help: ## Show this help message (grouped by sections)
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1;35m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_.-]+:.*?## \[core\]/ {gsub(/\[core\] */, "", $$2); printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## \[util\]/ {gsub(/\[util\] */, "", $$2); printf "  \033[33m%-30s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)

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
	@rm -f event_hubs.duckdb event_hubs.duckdb.wal
	@echo "✓ Local databases removed"


validate-cloud: ## [core] Compare local DuckDB row counts vs. cloud Postgres & Cosmos
	uv run python -m sync.validate_cloud

validate-local: ## [core] Validate local DuckDB databases (tables, schema, row counts)
	uv run seed-data/validate_data.py --local

validate-cosmos: ## [util] Compare local Cosmos DuckDB vs. cloud Azure Cosmos
	uv run python -m sync.validate_cloud --cosmos

validate-postgres: ## [util] Compare local Postgres DuckDB vs. cloud Azure Postgres
	uv run python -m sync.validate_cloud --postgres


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
	@rm -f $(SWEEPS_DIR)/.pids
	@# Launch each sweep as a background process with its own log
	@for s in $(ALL_SWEEPS); do \
		cp local_postgres.duckdb $(SWEEPS_DIR)/$${s}_postgres.duckdb; \
		cp local_cosmos.duckdb $(SWEEPS_DIR)/$${s}_cosmos.duckdb; \
		LOCAL_POSTGRES_DB=$(CURDIR)/$(SWEEPS_DIR)/$${s}_postgres.duckdb \
		LOCAL_COSMOS_DB=$(CURDIR)/$(SWEEPS_DIR)/$${s}_cosmos.duckdb \
		uv run python -m simulation.run_simulation --sweep $$s --sweep-type grid \
			> $(SWEEPS_DIR)/$$s.log 2>&1 & \
		echo $$! >> $(SWEEPS_DIR)/.pids; \
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

stop-sweeps: ## [core] Kill all running sweep processes, close DBs, and clean up
	@echo ""
	@echo "============================================================"
	@echo "🛑 Stopping all sweep processes..."
	@echo "============================================================"
	@if [ -f $(SWEEPS_DIR)/.pids ]; then \
		echo "  Sending SIGTERM to sweep processes..."; \
		while read pid; do \
			if kill -0 $$pid 2>/dev/null; then \
				kill -TERM $$pid 2>/dev/null && echo "  SIGTERM → pid $$pid"; \
			fi; \
		done < $(SWEEPS_DIR)/.pids; \
		echo "  Waiting 5s for graceful shutdown..."; \
		sleep 5; \
		while read pid; do \
			if kill -0 $$pid 2>/dev/null; then \
				kill -9 $$pid 2>/dev/null && echo "  SIGKILL → pid $$pid (force)"; \
			fi; \
		done < $(SWEEPS_DIR)/.pids; \
		rm -f $(SWEEPS_DIR)/.pids; \
		echo "  ✓ All sweep processes stopped"; \
	else \
		echo "  No .pids file found — killing by process name..."; \
		pkill -TERM -f 'simulation.run_simulation --sweep' 2>/dev/null || true; \
		sleep 3; \
		pkill -9 -f 'simulation.run_simulation --sweep' 2>/dev/null || true; \
		echo "  ✓ Sweep processes stopped (by pattern match)"; \
	fi
	@echo "  Removing stale WAL files..."
	@rm -f $(SWEEPS_DIR)/*.duckdb.wal
	@echo "  ✓ WAL files cleaned"
	@echo "============================================================"
	@echo "  Running clean-sweeps to remove all sweep data..."
	@$(MAKE) --no-print-directory clean-sweeps
	@echo "============================================================"
	@echo "✓ All sweep processes stopped and cleaned up"
	@echo "============================================================"
	@echo ""

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

seed-reviews: ## [core] Seed customer reviews into event_hubs.duckdb
	@echo "📝 Seeding customer reviews..."
	uv run python -m simulation.customer_review_simulator


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
	docker compose -f agents/docker-compose.yml build --no-cache

agents-up: ## [core] Start agent services (detached)
	docker compose -f agents/docker-compose.yml up -d

agents-down: ## [core] Stop agent services
	docker compose -f agents/docker-compose.yml down

agents-logs: ## [util] Tail agent service logs
	docker compose -f agents/docker-compose.yml logs -f

# agent3-start: ## [util] Start Agent 3 sentiment service (port 8003)
# 	uv run uvicorn agents.agent3_sentiment.main:app --host 0.0.0.0 --port 8003
#
# agent3-dev: ## [util] Start Agent 3 with auto-reload
# 	uv run uvicorn agents.agent3_sentiment.main:app --host 0.0.0.0 --port 8003 --reload


# =============================================================================
##@ Cloud Deployment
# =============================================================================

cloud-build: cloud-dashboard-build cloud-agents-build ## [core] Build all 4 images in ACR (no local Docker needed)
	@echo "\033[0;32m✅ All images built in ACR!\033[0m"

cloud-dashboard-build: ## [util] Build dashboard image in ACR
	$(eval ACR_NAME := $(shell terraform -chdir=infra/cloud output -raw container_registry_name 2>/dev/null))
	@if [ -z "$(ACR_NAME)" ]; then \
		echo "ERROR: Could not read container_registry_name from Terraform output. Run 'make tf' first."; \
		exit 1; \
	fi
	@echo "Building dashboard in ACR..."
	az acr build --registry $(ACR_NAME) --image dashboard:latest --platform linux/amd64 dashboard/

cloud-agents-build: ## [util] Build all 3 agent images in ACR
	$(eval ACR_NAME := $(shell terraform -chdir=infra/cloud output -raw container_registry_name 2>/dev/null))
	@if [ -z "$(ACR_NAME)" ]; then \
		echo "ERROR: Could not read container_registry_name from Terraform output. Run 'make tf' first."; \
		exit 1; \
	fi
	@echo "Building agent images in ACR..."
	az acr build --registry $(ACR_NAME) --image agent1-explainer:latest --platform linux/amd64 -f agents/agent1_explainer/Dockerfile .
	az acr build --registry $(ACR_NAME) --image agent2-narrative:latest --platform linux/amd64 -f agents/agent2_narrative/Dockerfile .
	az acr build --registry $(ACR_NAME) --image agent3-sentiment:latest --platform linux/amd64 -f agents/agent3_sentiment/Dockerfile .

cloud-deploy: cloud-build ## [core] Build all images in ACR + update all Container Apps
	$(eval ACR_SERVER := $(shell terraform -chdir=infra/cloud output -raw container_registry_login_server 2>/dev/null))
	$(eval RG := $(shell terraform -chdir=infra/cloud output -raw resource_group 2>/dev/null))
	$(eval DASHBOARD_APP := $(shell terraform -chdir=infra/cloud output -raw dashboard_app_name 2>/dev/null))
	$(eval AGENT1_APP := $(shell terraform -chdir=infra/cloud output -raw agent1_app_name 2>/dev/null))
	$(eval AGENT2_APP := $(shell terraform -chdir=infra/cloud output -raw agent2_app_name 2>/dev/null))
	$(eval AGENT3_APP := $(shell terraform -chdir=infra/cloud output -raw agent3_app_name 2>/dev/null))
	@if [ -z "$(ACR_SERVER)" ] || [ -z "$(RG)" ]; then \
		echo "ERROR: Could not read Terraform outputs. Run 'make tf' first."; \
		exit 1; \
	fi
	@echo "Updating Container App images..."
	az containerapp update -n "$(DASHBOARD_APP)" -g "$(RG)" --image "$(ACR_SERVER)/dashboard:latest"
	az containerapp update -n "$(AGENT1_APP)" -g "$(RG)" --image "$(ACR_SERVER)/agent1-explainer:latest"
	az containerapp update -n "$(AGENT2_APP)" -g "$(RG)" --image "$(ACR_SERVER)/agent2-narrative:latest"
	az containerapp update -n "$(AGENT3_APP)" -g "$(RG)" --image "$(ACR_SERVER)/agent3-sentiment:latest"
	@echo "\033[0;32m✅ All Container Apps updated!\033[0m"

cloud-logs: ## [util] Tail Container App logs for all services
	$(eval RG := $(shell terraform -chdir=infra/cloud output -raw resource_group 2>/dev/null))
	$(eval DASHBOARD_APP := $(shell terraform -chdir=infra/cloud output -raw dashboard_app_name 2>/dev/null))
	$(eval AGENT1_APP := $(shell terraform -chdir=infra/cloud output -raw agent1_app_name 2>/dev/null))
	$(eval AGENT2_APP := $(shell terraform -chdir=infra/cloud output -raw agent2_app_name 2>/dev/null))
	$(eval AGENT3_APP := $(shell terraform -chdir=infra/cloud output -raw agent3_app_name 2>/dev/null))
	@if [ -z "$(RG)" ]; then \
		echo "ERROR: Could not read Terraform outputs. Run 'make tf' first."; \
		exit 1; \
	fi
	@echo "Tailing logs for all Container Apps..."
	@echo "Dashboard: $(DASHBOARD_APP)"
	@echo "Agent 1:   $(AGENT1_APP)"
	@echo "Agent 2:   $(AGENT2_APP)"
	@echo "Agent 3:   $(AGENT3_APP)"
	@echo ""
	az containerapp logs show -n "$(DASHBOARD_APP)" -g "$(RG)" --follow &
	az containerapp logs show -n "$(AGENT1_APP)" -g "$(RG)" --follow &
	az containerapp logs show -n "$(AGENT2_APP)" -g "$(RG)" --follow &
	az containerapp logs show -n "$(AGENT3_APP)" -g "$(RG)" --follow &
	@wait


# =============================================================================
##@ Data Sync
# =============================================================================

sync-export: ## [core] (Local) Export local DuckDB data to sync/staging/ (Parquet + NDJSON)
	@echo ""
	@echo "============================================================"
	@echo "Exporting local DuckDB data to sync/staging/"
	@echo "============================================================"
	@echo ""
	@echo "--- PostgreSQL (Parquet) ---"
	@uv run python -m sync.export_postgres
	@echo ""
	@echo "--- CosmosDB (NDJSON) ---"
	@uv run python -m sync.export_cosmos
	@echo ""
	@echo "--- Event Hub (NDJSON) ---"
	@uv run python -m sync.export_eventhub
	@echo ""
	@echo "============================================================"
	@echo "Export complete. Files in sync/staging/"
	@echo "============================================================"

sync-upload: ## [core] Upload sync/staging/ to Azure Blob Storage
	@echo "Uploading staged files to Azure Blob Storage..."
	@uv run python -m sync.upload

sync-import: ## [core] Trigger importer Container App Job in Azure
	$(eval IMPORTER_JOB := $(shell terraform -chdir=infra/cloud output -raw importer_job_name 2>/dev/null))
	$(eval RG := $(shell terraform -chdir=infra/cloud output -raw resource_group 2>/dev/null))
	@if [ -z "$(IMPORTER_JOB)" ] || [ -z "$(RG)" ]; then \
		echo "ERROR: Could not read importer_job_name or resource_group from Terraform output."; \
		echo "Run 'make tf' first to provision cloud infrastructure."; \
		exit 1; \
	fi
	@echo "Starting importer job: $(IMPORTER_JOB) in $(RG)..."
	az containerapp job start -n "$(IMPORTER_JOB)" -g "$(RG)"

sync-all: sync-export sync-upload sync-import ## [core] Full sync pipeline: export + upload + import

sync-clean: ## [util] (Local) Remove sync/staging/ directory
	@echo "Removing sync/staging/..."
	@rm -rf sync/staging/
	@echo "Done."

sync-push: ## [util] Build importer image in ACR (cloud-native, avoids arch conflicts)
	$(eval ACR_NAME := $(shell terraform -chdir=infra/cloud output -raw container_registry_name 2>/dev/null))
	@if [ -z "$(ACR_NAME)" ]; then \
		echo "ERROR: Could not read container_registry_name from Terraform output."; \
		exit 1; \
	fi
	@echo "Building sync-importer in ACR (az acr build)..."
	az acr build --registry $(ACR_NAME) --image sync-importer:latest --platform linux/amd64 sync/importer/

sync-deploy: sync-push ## [core] Build image in ACR, then update Container App Job
	$(eval ACR_SERVER := $(shell terraform -chdir=infra/cloud output -raw container_registry_login_server 2>/dev/null))
	$(eval IMPORTER_JOB := $(shell terraform -chdir=infra/cloud output -raw importer_job_name 2>/dev/null))
	$(eval RG := $(shell terraform -chdir=infra/cloud output -raw resource_group 2>/dev/null))
	@if [ -z "$(IMPORTER_JOB)" ] || [ -z "$(RG)" ] || [ -z "$(ACR_SERVER)" ]; then \
		echo "ERROR: Could not read Terraform outputs. Run 'make tf' first."; \
		exit 1; \
	fi
	@echo "Updating Container App Job image to $(ACR_SERVER)/sync-importer:latest..."
	az containerapp job update -n "$(IMPORTER_JOB)" -g "$(RG)" \
		--image "$(ACR_SERVER)/sync-importer:latest"
	@echo "✓ Importer job updated with latest image"


# =============================================================================
##@ Infrastructure (Cloud)
# =============================================================================

# Environment toggle: dev (no VNET, fast) or prod (full zero-trust)
# Usage: make tf ENV=dev  (default)
#        make tf ENV=prod
ENV ?= dev
FABRIC_ADMIN ?= $(shell az ad signed-in-user show --query userPrincipalName -o tsv 2>/dev/null)
TF_ENV_VARS = -var="environment=$(ENV)" -var="fabric_admin_upn=$(FABRIC_ADMIN)"

tf: init-clean plan apply ## [core] Provision CosmosDB + PostgreSQL via Terraform
	@echo "\033[0;32m✅ Terraform infrastructure provisioned ($(ENV))!\033[0m"

tf-dev: ## [core] Provision cloud infra in dev mode (no VNET, fast destroy)
	@$(MAKE) tf ENV=dev

tf-prod: ## [core] Provision cloud infra in prod mode (full VNET + private endpoints)
	@$(MAKE) tf ENV=prod

init-clean: ## [util] Initialize Terraform from clean state (retries on network failure)
	rm -rf infra/cloud/.terraform.lock.hcl
	rm -rf infra/cloud/.terraform
	rm -rf infra/cloud/terraform.tfstate
	rm -rf infra/cloud/terraform.tfstate.backup
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID"; \
	for i in 1 2 3; do \
		echo "Terraform init (cloud) attempt $$i/3..."; \
		ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID TF_REGISTRY_CLIENT_TIMEOUT=60 terraform -chdir=infra/cloud init --upgrade && exit 0; \
		echo "Init (cloud) failed, retrying in 10s..."; \
		sleep 10; \
	done; \
	echo "Terraform init (cloud) failed after 3 attempts"; \
	exit 1

plan: ## [util] Preview Terraform changes; can run: make plan apply ENV=dev
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID (env=$(ENV))"; \
	ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID terraform -chdir=infra/cloud plan $(TF_ENV_VARS) -out=tfplan

apply: ## [util] Apply Terraform plan
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID"; \
	ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID terraform -chdir=infra/cloud apply -auto-approve tfplan

delete-cloud: ## [core] Delete cloud resource groups (tag: tf=cloud) and purge soft-deleted resources
	$(eval subscription_id := $(shell az account show --query id -o tsv))
	$(eval tagged_rgs := $(shell az group list --subscription "$(subscription_id)" --query "[?tags.tf=='cloud'].name" -o tsv | tr -d '\r' | tr '\n' ' '))
	@echo "Cloud resource groups to delete: $(tagged_rgs)"
	@if [ -z "$(tagged_rgs)" ]; then \
		echo "No cloud-tagged resource groups found — skipping."; \
	else \
		for rg in $(tagged_rgs); do \
			echo "Deleting resource group: $$rg"; \
			az group delete --subscription "$(subscription_id)" --yes -n "$$rg" 2>&1 || true; \
		done; \
	fi
	@echo "Purging soft-deleted Key Vaults from deleted resource groups..."
	@if [ -n "$(tagged_rgs)" ]; then \
		for rg in $(tagged_rgs); do \
			az keyvault list-deleted --subscription "$(subscription_id)" \
				--query "[?properties.vaultId && contains(properties.vaultId, '$$rg')].name" -o tsv 2>/dev/null | \
				while read -r name; do \
					echo "  Purging: $$name"; \
					az keyvault purge --subscription "$(subscription_id)" -n "$$name" 2>/dev/null || true; \
				done; \
		done; \
	fi
	@echo "Cleaning up cloud Terraform state..."
	@rm -f infra/cloud/terraform.tfstate infra/cloud/terraform.tfstate.backup infra/cloud/tfplan
	@echo ""
	@echo "\033[0;32m✅ Cloud infrastructure deleted and purged!\033[0m"

# =============================================================================
##@ Infrastructure (Local)
# =============================================================================

tf-local: init-local-clean plan-local apply-local create-agent-sp ## [core] Provision local OpenAI resources + service principal
	@echo "\033[0;32m✅ Local OpenAI infrastructure provisioned!\033[0m"

init-local-clean: ## [util] Initialize local Terraform from clean state
	rm -rf infra/local/.terraform.lock.hcl
	rm -rf infra/local/.terraform
	rm -rf infra/local/terraform.tfstate
	rm -rf infra/local/terraform.tfstate.backup
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID"; \
	for i in 1 2 3; do \
		echo "Terraform init (local) attempt $$i/3..."; \
		ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID TF_REGISTRY_CLIENT_TIMEOUT=60 terraform -chdir=infra/local init --upgrade && exit 0; \
		echo "Init (local) failed, retrying in 10s..."; \
		sleep 10; \
	done; \
	echo "Terraform init (local) failed after 3 attempts"; \
	exit 1

plan-local: ## [util] Preview local Terraform changes
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID"; \
	ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID terraform -chdir=infra/local plan -out=tfplan-local

apply-local: ## [util] Apply local Terraform plan
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription in az context. Run: az login && az account set --subscription <id>"; \
		exit 1; \
	fi; \
	echo "Using Azure subscription: $$SUBSCRIPTION_ID"; \
	ARM_SUBSCRIPTION_ID=$$SUBSCRIPTION_ID terraform -chdir=infra/local apply -auto-approve tfplan-local

SP_NAME_PREFIX = simulation-workflows-agents

create-agent-sp: ## [util] Create service principal for Docker agent containers
	@echo ""
	@echo "============================================================"
	@echo "🔑 Creating Service Principal for Agent Containers"
	@echo "============================================================"
	@SUBSCRIPTION_ID=$$(az account show --query id -o tsv 2>/dev/null); \
	if [ -z "$$SUBSCRIPTION_ID" ]; then \
		echo "No active Azure subscription. Run: az login"; \
		exit 1; \
	fi; \
	OPENAI_ID=$$(terraform -chdir=infra/local output -raw openai_id 2>/dev/null); \
	if [ -z "$$OPENAI_ID" ]; then \
		echo "✗ Could not read openai_id from Terraform state. Run tf-local first."; \
		exit 1; \
	fi; \
	RG_NAME=$$(terraform -chdir=infra/local output -raw resource_group_name 2>/dev/null); \
	SP_DISPLAY_NAME="$(SP_NAME_PREFIX)-$${RG_NAME#rg-openai-}"; \
	EXISTING=$$(az ad app list --filter "displayName eq '$$SP_DISPLAY_NAME'" --query "[0].appId" -o tsv 2>/dev/null); \
	if [ -n "$$EXISTING" ]; then \
		echo "Service principal '$$SP_DISPLAY_NAME' already exists (appId: $$EXISTING) — skipping creation."; \
		if grep -q AZURE_CLIENT_ID local.env 2>/dev/null; then \
			echo "Credentials already in local.env."; \
		else \
			echo "⚠  SP exists but credentials are not in local.env. Delete the SP and re-run to regenerate."; \
		fi; \
	else \
		echo "Creating service principal: $$SP_DISPLAY_NAME"; \
		SP_JSON=$$(az ad sp create-for-rbac \
			--name "$$SP_DISPLAY_NAME" \
			--role "Cognitive Services OpenAI User" \
			--scopes "$$OPENAI_ID" \
			--create-password false \
			--only-show-errors \
			-o json); \
		if [ $$? -ne 0 ] || ! echo "$$SP_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" >/dev/null 2>&1; then \
			echo "✗ Failed to create service principal:"; \
			echo "$$SP_JSON"; \
			exit 1; \
		fi; \
		CLIENT_ID=$$(echo "$$SP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['appId'])"); \
		TENANT_ID=$$(echo "$$SP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['tenant'])"); \
		echo "Adding short-lived credential (30 days)..."; \
		CRED_END=$$(date -u -v+29d '+%Y-%m-%dT%H:%M:%SZ'); \
		CRED_JSON=$$(az ad app credential reset \
			--id "$$CLIENT_ID" \
			--end-date "$$CRED_END" \
			--append \
			--only-show-errors \
			-o json); \
		if [ $$? -ne 0 ] || ! echo "$$CRED_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" >/dev/null 2>&1; then \
			echo "✗ Failed to create credential:"; \
			echo "$$CRED_JSON"; \
			echo "Cleaning up app registration..."; \
			az ad app delete --id "$$CLIENT_ID" 2>/dev/null || true; \
			exit 1; \
		fi; \
		CLIENT_SECRET=$$(echo "$$CRED_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])"); \
		echo "Assigning additional role: Cognitive Services User"; \
		az role assignment create \
			--assignee "$$CLIENT_ID" \
			--role "Cognitive Services User" \
			--scope "$$OPENAI_ID" \
			-o none; \
		sed -i '' '/^# Service principal credentials/d;/^AZURE_TENANT_ID=/d;/^AZURE_CLIENT_ID=/d;/^AZURE_CLIENT_SECRET=/d' local.env 2>/dev/null || true; \
		sed -i '' -e :a -e '/^\n*$$/{$$d;N;ba' -e '}' local.env 2>/dev/null || true; \
		echo "" >> local.env; \
		echo "# Service principal credentials for Docker containers" >> local.env; \
		echo "AZURE_TENANT_ID=$$TENANT_ID" >> local.env; \
		echo "AZURE_CLIENT_ID=$$CLIENT_ID" >> local.env; \
		echo "AZURE_CLIENT_SECRET=$$CLIENT_SECRET" >> local.env; \
		echo "✓ Service principal created and credentials written to local.env"; \
	fi

delete-baseline: ## [core] Delete local resource groups (tag: tf=local) and purge soft-deleted resources
	$(eval subscription_id := $(shell az account show --query id -o tsv))
	$(eval tagged_rgs := $(shell az group list --subscription "$(subscription_id)" --query "[?tags.tf=='local'].name" -o tsv | tr -d '\r' | tr '\n' ' '))
	@echo "Local resource groups to delete: $(tagged_rgs)"
	@if [ -z "$(tagged_rgs)" ]; then \
		echo "No local-tagged resource groups found — skipping."; \
	else \
		for rg in $(tagged_rgs); do \
			echo "Deleting resource group: $$rg"; \
			az group delete --subscription "$(subscription_id)" --yes -n "$$rg" 2>&1 || true; \
		done; \
	fi
	@echo "Purging all soft-deleted Cognitive Services accounts..."
	@az cognitiveservices account list-deleted --subscription "$(subscription_id)" \
		--query "[].[id, name, location]" -o tsv 2>/dev/null | \
		while IFS=$$'\t' read -r id name location; do \
			rg_name=$$(echo "$$id" | sed -n 's|.*/resourceGroups/\([^/]*\)/.*|\1|p'); \
			echo "  Purging: $$name ($$location) from $$rg_name"; \
			az cognitiveservices account purge --subscription "$(subscription_id)" \
				-l "$$location" -n "$$name" -g "$$rg_name" 2>/dev/null || true; \
		done
	@echo "Cleaning up Entra ID app registrations (simulation-workflows-agents-*)..."
	@az ad app list --filter "startswith(displayName, 'simulation-workflows-agents-')" \
		--query "[].{id:id, name:displayName}" -o tsv 2>/dev/null | \
		while IFS=$$'\t' read -r app_id app_name; do \
			echo "  Deleting app registration: $$app_name"; \
			az ad app delete --id "$$app_id" 2>/dev/null || true; \
		done
	@echo "Cleaning up local Terraform state..."
	@rm -f infra/local/terraform.tfstate infra/local/terraform.tfstate.backup infra/local/tfplan-local
	@echo ""
	@echo "\033[0;32m✅ Local infrastructure deleted and purged!\033[0m"


##@ Help
help: ## [util] Show this help message
	@echo ""
	@echo "\033[1;36m╔══════════════════════════════════════════════════════════════════════╗\033[0m"
	@echo "\033[1;36m║                        Retail Analytics Hub                          ║\033[0m"
	@echo "\033[1;36m╚══════════════════════════════════════════════════════════════════════╝\033[0m"
	@echo ""
	@echo "  \033[36m●\033[0m \033[36mcore\033[0m = Primary workflows    \033[33m○\033[0m \033[33mutil\033[0m = Utilities"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} \
		/^##@/ {printf "\n\033[1;35m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z0-9_.-]+:.*?## \[core\]/ {gsub(/\[core\] */, "", $$2); printf "  \033[36m●\033[0m \033[36m%-38s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## \[util\]/ {gsub(/\[util\] */, "", $$2); printf "  \033[33m○\033[0m \033[33m%-38s\033[0m %s\n", $$1, $$2; next} \
		/^[a-zA-Z0-9_.-]+:.*?## / {printf "    %-40s %s\n", $$1, $$2}' \
		$(MAKEFILE_LIST)
	@echo ""

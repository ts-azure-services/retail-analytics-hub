terraform {
  required_version = ">= 1.8, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.56.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

locals {
  location = "westus3"
  tags = {
    tf = "local"
  }
}

resource "azurerm_resource_group" "openai" {
  name     = "rg-openai-${random_string.suffix.result}"
  location = local.location
  tags     = local.tags
}

resource "azurerm_cognitive_account" "openai" {
  name                  = "openai-fabric-${random_string.suffix.result}"
  location              = azurerm_resource_group.openai.location
  resource_group_name   = azurerm_resource_group.openai.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "openai-fabric-${random_string.suffix.result}"

  tags = local.tags
}

resource "azurerm_cognitive_deployment" "gpt_4o_mini" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = "2024-07-18"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 900
  }
}

resource "azurerm_cognitive_deployment" "gpt52" {
  name                 = "gpt-5.2"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-5.2"
    version = "2025-12-11"
  }

  sku {
    name     = "GlobalStandard"
    capacity = 900
  }
}

# =============================================================================
# COSMOSDB
# =============================================================================

resource "azurerm_cosmosdb_account" "example" {
  name                = "fabric${random_string.suffix.result}cosmos"
  location            = azurerm_resource_group.openai.location
  resource_group_name = azurerm_resource_group.openai.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  public_network_access_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.openai.location
    failover_priority = 0
  }

  backup {
    type = "Continuous"
    tier = "Continuous7Days"
  }

  tags = local.tags
}

resource "azurerm_cosmosdb_sql_database" "example" {
  name                = "fabric${random_string.suffix.result}db"
  resource_group_name = azurerm_resource_group.openai.name
  account_name        = azurerm_cosmosdb_account.example.name

  autoscale_settings {
    max_throughput = 10000
  }
}

# =============================================================================
# POSTGRESQL
# =============================================================================

resource "random_password" "postgresql_admin" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
  min_lower        = 1
  min_upper        = 1
  min_numeric      = 1
  min_special      = 1
}

resource "azurerm_postgresql_flexible_server" "example" {
  name                = "fabric${random_string.suffix.result}psql"
  location            = azurerm_resource_group.openai.location
  resource_group_name = azurerm_resource_group.openai.name

  administrator_login    = "psqladmin"
  administrator_password = random_password.postgresql_admin.result

  sku_name   = "GP_Standard_D2s_v3"
  storage_mb = 32768
  version    = "16"

  backup_retention_days = 7

  public_network_access_enabled = true

  lifecycle {
    ignore_changes = [zone]
  }

  tags = local.tags
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAllAzureServicesAndResourcesWithinAzureIps"
  server_id        = azurerm_postgresql_flexible_server.example.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "example" {
  name      = "fabric${random_string.suffix.result}database"
  server_id = azurerm_postgresql_flexible_server.example.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# =============================================================================
# EVENT HUB
# =============================================================================

resource "azurerm_eventhub_namespace" "example" {
  name                = "fabric${random_string.suffix.result}namespace"
  location            = azurerm_resource_group.openai.location
  resource_group_name = azurerm_resource_group.openai.name
  sku                 = "Standard"
  capacity            = 1

  local_authentication_enabled = true

  tags = local.tags
}

resource "azurerm_eventhub" "example" {
  name              = "fabric${random_string.suffix.result}eventhub"
  namespace_id      = azurerm_eventhub_namespace.example.id
  partition_count   = 4
  message_retention = 3
}

# Raw inbound reviews hub (generator publishes here, Agent 3 consumes)
resource "azurerm_eventhub" "raw_reviews" {
  name              = "fabric${random_string.suffix.result}rawreviews"
  namespace_id      = azurerm_eventhub_namespace.example.id
  partition_count   = 4
  message_retention = 3
}

resource "azurerm_eventhub_authorization_rule" "example" {
  name                = "ehpolicy${random_string.suffix.result}"
  namespace_name      = azurerm_eventhub_namespace.example.name
  eventhub_name       = azurerm_eventhub.example.name
  resource_group_name = azurerm_resource_group.openai.name
  listen              = true
  send                = true
  manage              = false
}

# SAS policy for raw-reviews hub
resource "azurerm_eventhub_authorization_rule" "raw_reviews" {
  name                = "ehpolicyraw${random_string.suffix.result}"
  namespace_name      = azurerm_eventhub_namespace.example.name
  eventhub_name       = azurerm_eventhub.raw_reviews.name
  resource_group_name = azurerm_resource_group.openai.name
  listen              = true
  send                = true
  manage              = false
}

# Grant current user Data Sender on processed-reviews hub
resource "azurerm_role_assignment" "eventhub_sender" {
  scope                = azurerm_eventhub.example.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Grant current user Data Sender on raw-reviews hub
resource "azurerm_role_assignment" "eventhub_raw_sender" {
  scope                = azurerm_eventhub.raw_reviews.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Grant current user Data Receiver on raw-reviews hub
resource "azurerm_role_assignment" "eventhub_raw_receiver" {
  scope                = azurerm_eventhub.raw_reviews.id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = data.azurerm_client_config.current.object_id
}

# =============================================================================
# OUTPUTS
# =============================================================================

output "resource_group_name" {
  value       = azurerm_resource_group.openai.name
  description = "Resource group containing Azure OpenAI resources"
}

output "openai_name" {
  value       = azurerm_cognitive_account.openai.name
  description = "Azure OpenAI account name"
}

output "openai_endpoint" {
  value       = azurerm_cognitive_account.openai.endpoint
  description = "Azure OpenAI endpoint"
}

output "gpt_4o_mini_deployment_name" {
  value       = azurerm_cognitive_deployment.gpt_4o_mini.name
  description = "Deployment name for gpt-4o-mini"
}

output "gpt52_deployment_name" {
  value       = azurerm_cognitive_deployment.gpt52.name
  description = "Deployment name for gpt-5.2"
}

output "openai_id" {
  value       = azurerm_cognitive_account.openai.id
  description = "Azure OpenAI account resource ID (used for RBAC scoping)"
}

# CosmosDB outputs
output "cosmosdb_account_name" {
  value       = azurerm_cosmosdb_account.example.name
  description = "The name of the CosmosDB account"
}

output "cosmosdb_endpoint" {
  value       = azurerm_cosmosdb_account.example.endpoint
  description = "The endpoint for the CosmosDB account"
}

output "cosmosdb_primary_key" {
  value       = azurerm_cosmosdb_account.example.primary_key
  description = "The primary key for the CosmosDB account"
  sensitive   = true
}

output "cosmosdb_database_name" {
  value       = azurerm_cosmosdb_sql_database.example.name
  description = "The name of the CosmosDB database"
}

# PostgreSQL outputs
output "postgresql_server_name" {
  value       = azurerm_postgresql_flexible_server.example.name
  description = "The name of the PostgreSQL flexible server"
}

output "postgresql_server_fqdn" {
  value       = azurerm_postgresql_flexible_server.example.fqdn
  description = "The FQDN of the PostgreSQL flexible server"
}

output "postgresql_admin_login" {
  value       = azurerm_postgresql_flexible_server.example.administrator_login
  description = "The administrator login for the PostgreSQL server"
}

output "postgresql_admin_password" {
  value       = azurerm_postgresql_flexible_server.example.administrator_password
  description = "The administrator password for the PostgreSQL server"
  sensitive   = true
}

output "postgresql_database_name" {
  value       = azurerm_postgresql_flexible_server_database.example.name
  description = "The name of the PostgreSQL database"
}

# Event Hub outputs
output "event_hub_namespace" {
  value       = azurerm_eventhub_namespace.example.name
  description = "The name of the Event Hub namespace"
}

output "event_hub" {
  value       = azurerm_eventhub.example.name
  description = "The name of the Event Hub (processed reviews)"
}

output "event_hub_raw_reviews" {
  value       = azurerm_eventhub.raw_reviews.name
  description = "The name of the raw-reviews Event Hub (inbound)"
}

output "event_hub_policy" {
  value       = azurerm_eventhub_authorization_rule.example.name
  description = "The name of the Event Hub authorization rule"
}

output "event_hub_connection_string" {
  value       = azurerm_eventhub_authorization_rule.example.primary_connection_string
  description = "The connection string for the Event Hub authorization rule"
  sensitive   = true
}

output "eventhub_id" {
  value       = azurerm_eventhub.example.id
  description = "The Event Hub resource ID (used for RBAC scoping)"
}

output "cosmosdb_account_id" {
  value       = azurerm_cosmosdb_account.example.id
  description = "The CosmosDB account resource ID (used for RBAC scoping)"
}

# Generate .env file for local development
resource "local_file" "env_file" {
  filename = "${path.module}/../../local.env"
  content  = <<-EOT
    # Generated by Terraform - Azure OpenAI local configuration
    AZURE_RESOURCE_GROUP=${azurerm_resource_group.openai.name}
    AZURE_OPENAI_NAME=${azurerm_cognitive_account.openai.name}
    AZURE_OPENAI_ENDPOINT=https://${azurerm_cognitive_account.openai.custom_subdomain_name}.openai.azure.com/
    AZURE_OPENAI_API_VERSION=2024-12-01-preview
    GPT_4O_MINI_DEPLOYMENT=${azurerm_cognitive_deployment.gpt_4o_mini.name}
    GPT_52_DEPLOYMENT=${azurerm_cognitive_deployment.gpt52.name}

    COSMOSDB_ACCOUNT_NAME=${azurerm_cosmosdb_account.example.name}
    COSMOSDB_ENDPOINT=${azurerm_cosmosdb_account.example.endpoint}
    COSMOSDB_DATABASE_NAME=${azurerm_cosmosdb_sql_database.example.name}
    COSMOSDB_PRIMARY_KEY=${azurerm_cosmosdb_account.example.primary_key}
    COSMOSDB_CONNECTION_STRING='${azurerm_cosmosdb_account.example.primary_sql_connection_string}'

    POSTGRES_SERVER_NAME=${azurerm_postgresql_flexible_server.example.name}
    POSTGRESQL_SERVER_FQDN=${azurerm_postgresql_flexible_server.example.fqdn}
    POSTGRESQL_DATABASE_NAME=${azurerm_postgresql_flexible_server_database.example.name}
    POSTGRESQL_ADMIN_LOGIN=${azurerm_postgresql_flexible_server.example.administrator_login}
    POSTGRESQL_ADMIN_PASSWORD='${azurerm_postgresql_flexible_server.example.administrator_password}'

    EVENTHUB_NAMESPACE=${azurerm_eventhub_namespace.example.name}
    EVENTHUB_NAME=${azurerm_eventhub.example.name}
    EVENTHUB_RAW_NAME=${azurerm_eventhub.raw_reviews.name}
    EVENTHUB_PROCESSED_NAME=${azurerm_eventhub.example.name}
    EVENTHUB_POLICY_NAME=${azurerm_eventhub_authorization_rule.example.name}
    EVENTHUB_CONNECTION_STRING='${azurerm_eventhub_authorization_rule.example.primary_connection_string}'

    # Simulation target: "local" = DuckDB (default), "cloud" = write directly to Azure
    SIMULATION_TARGET=local
  EOT
}

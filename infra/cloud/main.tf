terraform {
  required_version = ">= 1.8, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.56.0"
    }
    # azapi = {
    #   source  = "azure/azapi"
    #   version = "~> 2.0"
    # }
    fabric = {
      source  = "microsoft/fabric"
      version = "1.7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.4"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "azurerm" {
  features {}
  # Automatically uses active Azure CLI subscription
  # Override with TF_VAR_subscription_id env var or -var flag
}

provider "fabric" {
}

# Generate a random string for unique naming
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Access the client configuration of the AzureRM provider.
data "azurerm_client_config" "current" {}

/*
# Get current client public IP address (IPv4 only)
data "http" "my_ip" {
  url = "https://api.ipify.org"
}

# Get user information from Azure CLI to determine if it's a user or service principal
data "external" "azure_user" {
  program = ["bash", "-c", "az ad signed-in-user show --query '{userPrincipalName:userPrincipalName,objectId:id}' 2>/dev/null || echo '{\"userPrincipalName\":\"\",\"objectId\":\"${data.azurerm_client_config.current.object_id}\"}'"
  ]
}
*/

# =============================================================================
# ENVIRONMENT TOGGLE: dev (functional, no VNET) vs prod (full zero-trust)
# Usage: terraform apply -var="environment=dev"   (default)
#        terraform apply -var="environment=prod"
# =============================================================================

variable "environment" {
  type        = string
  default     = "dev"
  description = "Environment stage: dev = functional (no VNET, public access), prod = full zero-trust (VNET, private endpoints)"

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'."
  }
}

variable "fabric_admin_upn" {
  type        = string
  description = "UPN (email) of the Fabric Capacity administrator"
}

variable "fabric_sql_endpoint" {
  description = "Fabric SQL endpoint connection string (set after manual Fabric mirroring setup)"
  type        = string
  default     = ""
}

locals {
  is_prod      = var.environment == "prod"
  fabric_admin = var.fabric_admin_upn

  # Container App names (used for internal DNS references)
  ca_dashboard = "ca-dashboard-${random_string.suffix.result}"
  ca_agent1    = "ca-agent1-explainer-${random_string.suffix.result}"
  ca_agent2    = "ca-agent2-narrative-${random_string.suffix.result}"
  ca_agent3    = "ca-agent3-sentiment-${random_string.suffix.result}"

  # Common tags applied to all resources
  common_tags = {
    tf              = "cloud"
    environment     = var.environment
    SecurityControl = "Ignore"
  }
}

# Create a resource group.
resource "azurerm_resource_group" "example" {
  name     = "rg-fabric-${random_string.suffix.result}"
  location = "WestUS3"

  tags = local.common_tags
}

# =============================================================================
# MICROSOFT FABRIC CAPACITY AND WORKSPACE
# =============================================================================

# Create a Fabric Capacity
resource "azurerm_fabric_capacity" "example" {
  name                = "fcfabric${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.example.name
  location            = "WestUS3"

  administration_members = [local.fabric_admin]

  sku {
    name = "F8"
    tier = "Fabric"
  }

  tags = local.common_tags
}

# Get the Fabric Capacity details
data "fabric_capacity" "example" {
  display_name = azurerm_fabric_capacity.example.name

  lifecycle {
    postcondition {
      condition     = self.state == "Active"
      error_message = "Fabric Capacity is not in Active state. Please check the Fabric Capacity status."
    }
  }
}

# Create a Fabric Workspace
resource "fabric_workspace" "example" {
  capacity_id  = data.fabric_capacity.example.id
  display_name = "ws-fabric-${random_string.suffix.result}"
}

# =============================================================================
# PHASE 1: ZERO-TRUST FOUNDATION - VNET, SUBNETS, NSGs
# =============================================================================

# Virtual Network
resource "azurerm_virtual_network" "main" {
  count               = local.is_prod ? 1 : 0
  name                = "vnet-fabric-${random_string.suffix.result}"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Subnet for Container Apps Environment (delegated to Microsoft.App/environments)
resource "azurerm_subnet" "containerapp" {
  count                = local.is_prod ? 1 : 0
  name                 = "snet-containerapp"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = ["10.0.0.0/23"]

  # Service endpoints for Storage Account network ACLs
  service_endpoints = ["Microsoft.Storage"]

  delegation {
    name = "containerapp-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# Subnet for PostgreSQL Flexible Server (delegated to Microsoft.DBforPostgreSQL/flexibleServers)
resource "azurerm_subnet" "postgresql" {
  count                = local.is_prod ? 1 : 0
  name                 = "snet-postgresql"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "postgresql-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }

  service_endpoints = ["Microsoft.Storage"]
}

# Subnet for Private Endpoints (CosmosDB, Storage, Event Hub, ACR, AI Foundry)
resource "azurerm_subnet" "privateendpoints" {
  count                = local.is_prod ? 1 : 0
  name                 = "snet-privateendpoints"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = ["10.0.3.0/24"]
}

# Subnet for Key Vault Private Endpoint (isolated for security)
resource "azurerm_subnet" "keyvault_pe" {
  count                = local.is_prod ? 1 : 0
  name                 = "snet-keyvault-pe"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = ["10.0.4.0/28"]
}

# Subnet for future management resources
resource "azurerm_subnet" "management" {
  count                = local.is_prod ? 1 : 0
  name                 = "snet-management"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main[0].name
  address_prefixes     = ["10.0.5.0/24"]
}

# Network Security Group for Container App Subnet
resource "azurerm_network_security_group" "containerapp" {
  count               = local.is_prod ? 1 : 0
  name                = "nsg-containerapp-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  # Allow HTTPS inbound from Internet
  security_rule {
    name                       = "AllowHTTPSInbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  # Allow HTTP inbound from Internet (Container Apps use HTTP internally)
  security_rule {
    name                       = "AllowHTTPInbound"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  # Allow outbound to private endpoints subnet
  security_rule {
    name                       = "AllowPrivateEndpointsOutbound"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "10.0.3.0/24"
  }

  # Allow outbound to PostgreSQL subnet
  security_rule {
    name                       = "AllowPostgreSQLOutbound"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "10.0.2.0/24"
  }

  # Allow outbound to Key Vault subnet
  security_rule {
    name                       = "AllowKeyVaultOutbound"
    priority                   = 120
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "10.0.4.0/28"
  }

  # Allow outbound to Internet (for Azure services, updates, etc.)
  security_rule {
    name                       = "AllowInternetOutbound"
    priority                   = 130
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "Internet"
  }

  tags = local.common_tags
}

# Associate NSG with Container App Subnet
resource "azurerm_subnet_network_security_group_association" "containerapp" {
  count                     = local.is_prod ? 1 : 0
  subnet_id                 = azurerm_subnet.containerapp[0].id
  network_security_group_id = azurerm_network_security_group.containerapp[0].id
}

# Network Security Group for PostgreSQL Subnet
resource "azurerm_network_security_group" "postgresql" {
  count               = local.is_prod ? 1 : 0
  name                = "nsg-postgresql-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  # Allow PostgreSQL inbound from Container App subnet only
  security_rule {
    name                       = "AllowPostgreSQLFromContainerApp"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "*"
  }

  # Allow PostgreSQL inbound from management subnet
  security_rule {
    name                       = "AllowPostgreSQLFromManagement"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.5.0/24"
    destination_address_prefix = "*"
  }

  # Deny all other inbound traffic
  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = local.common_tags
}

# Associate NSG with PostgreSQL Subnet
resource "azurerm_subnet_network_security_group_association" "postgresql" {
  count                     = local.is_prod ? 1 : 0
  subnet_id                 = azurerm_subnet.postgresql[0].id
  network_security_group_id = azurerm_network_security_group.postgresql[0].id
}

# Network Security Group for Private Endpoints Subnet
resource "azurerm_network_security_group" "privateendpoints" {
  count               = local.is_prod ? 1 : 0
  name                = "nsg-privateendpoints-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  # Allow HTTPS inbound from Container App subnet
  security_rule {
    name                       = "AllowHTTPSFromContainerApp"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "*"
  }

  # Allow HTTPS inbound from PostgreSQL subnet
  security_rule {
    name                       = "AllowHTTPSFromPostgreSQL"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.2.0/24"
    destination_address_prefix = "*"
  }

  tags = local.common_tags
}

# Associate NSG with Private Endpoints Subnet
resource "azurerm_subnet_network_security_group_association" "privateendpoints" {
  count                     = local.is_prod ? 1 : 0
  subnet_id                 = azurerm_subnet.privateendpoints[0].id
  network_security_group_id = azurerm_network_security_group.privateendpoints[0].id
}

# Network Security Group for Key Vault Subnet
resource "azurerm_network_security_group" "keyvault" {
  count               = local.is_prod ? 1 : 0
  name                = "nsg-keyvault-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  # Allow HTTPS inbound from Container App subnet
  security_rule {
    name                       = "AllowHTTPSFromContainerApp"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/23"
    destination_address_prefix = "*"
  }

  # Allow HTTPS inbound from PostgreSQL subnet
  security_rule {
    name                       = "AllowHTTPSFromPostgreSQL"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.2.0/24"
    destination_address_prefix = "*"
  }

  # Deny all from Internet
  security_rule {
    name                       = "DenyInternetInbound"
    priority                   = 1000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  tags = local.common_tags
}

# Associate NSG with Key Vault Subnet
resource "azurerm_subnet_network_security_group_association" "keyvault" {
  count                     = local.is_prod ? 1 : 0
  subnet_id                 = azurerm_subnet.keyvault_pe[0].id
  network_security_group_id = azurerm_network_security_group.keyvault[0].id
}

# =============================================================================
# PHASE 1: DNS PRIVATE ZONES
# =============================================================================

# DNS Private Zone for CosmosDB
resource "azurerm_private_dns_zone" "cosmosdb" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.documents.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link CosmosDB DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "cosmosdb" {
  count                 = local.is_prod ? 1 : 0
  name                  = "cosmosdb-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.cosmosdb[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Storage Account (File)
resource "azurerm_private_dns_zone" "storage_file" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.file.core.windows.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Storage File DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "storage_file" {
  count                 = local.is_prod ? 1 : 0
  name                  = "storage-file-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.storage_file[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Event Hub
resource "azurerm_private_dns_zone" "eventhub" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.servicebus.windows.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Event Hub DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "eventhub" {
  count                 = local.is_prod ? 1 : 0
  name                  = "eventhub-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.eventhub[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Container Registry
resource "azurerm_private_dns_zone" "acr" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.azurecr.io"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link ACR DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  count                 = local.is_prod ? 1 : 0
  name                  = "acr-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.acr[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Key Vault
resource "azurerm_private_dns_zone" "keyvault" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Key Vault DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
  count                 = local.is_prod ? 1 : 0
  name                  = "keyvault-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.keyvault[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for AI Foundry (Cognitive Services)
resource "azurerm_private_dns_zone" "cognitive" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.cognitiveservices.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Cognitive Services DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "cognitive" {
  count                 = local.is_prod ? 1 : 0
  name                  = "cognitive-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.cognitive[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for PostgreSQL
resource "azurerm_private_dns_zone" "postgres" {
  count               = local.is_prod ? 1 : 0
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link PostgreSQL DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  count                 = local.is_prod ? 1 : 0
  name                  = "postgres-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = azurerm_virtual_network.main[0].id
  registration_enabled  = false

  tags = local.common_tags
}

# =============================================================================
# PHASE 1: KEY VAULT AND SECRETS MANAGEMENT
# =============================================================================

# Generate random password for PostgreSQL
resource "random_password" "postgresql_admin" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
  min_lower        = 1
  min_upper        = 1
  min_numeric      = 1
  min_special      = 1
}

# Key Vault for centralized secrets management
resource "azurerm_key_vault" "main" {
  name                = "kv-fabric-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  # Enable RBAC authorization (required for managed identities)
  rbac_authorization_enabled = true

  # Enable purge protection (security best practice)
  purge_protection_enabled = true

  # Soft delete with 7 days retention
  soft_delete_retention_days = 7

  # Public network access enabled initially (will be disabled after private endpoint)
  public_network_access_enabled = true

  # Network ACLs - allow all initially (will be restricted after private endpoint)
  network_acls {
    bypass         = "AzureServices"
    default_action = "Allow"
  }

  tags = local.common_tags
}

# Grant current user Key Vault Administrator role
resource "azurerm_role_assignment" "current_user_kv_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Store PostgreSQL admin password in Key Vault
resource "azurerm_key_vault_secret" "postgresql_password" {
  name         = "postgresql-admin-password"
  value        = random_password.postgresql_admin.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# Store CosmosDB primary key in Key Vault (for legacy compatibility)
resource "azurerm_key_vault_secret" "cosmosdb_primary_key" {
  name         = "cosmosdb-primary-key"
  value        = azurerm_cosmosdb_account.example.primary_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# Store CosmosDB connection string in Key Vault (for legacy compatibility)
resource "azurerm_key_vault_secret" "cosmosdb_connection_string" {
  name         = "cosmosdb-connection-string"
  value        = azurerm_cosmosdb_account.example.primary_sql_connection_string
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# Store Event Hub connection string in Key Vault (for Fabric Eventstream)
resource "azurerm_key_vault_secret" "eventhub_connection_string" {
  name         = "eventhub-connection-string"
  value        = azurerm_eventhub_authorization_rule.example.primary_connection_string
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# Store Event Hub primary key in Key Vault
resource "azurerm_key_vault_secret" "eventhub_primary_key" {
  name         = "eventhub-primary-key"
  value        = azurerm_eventhub_authorization_rule.example.primary_key
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# =============================================================================
# EVENT HUB
# =============================================================================

# Create Event Hub Namespace
resource "azurerm_eventhub_namespace" "example" {
  name                = "fabric${random_string.suffix.result}namespace"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  sku                 = "Standard"
  capacity            = 1

  # Enable SAS authentication for Fabric Eventstream
  local_authentication_enabled = true

  tags = local.common_tags
}

# Create Event Hub
resource "azurerm_eventhub" "example" {
  name              = "fabric${random_string.suffix.result}eventhub"
  namespace_id      = azurerm_eventhub_namespace.example.id
  partition_count   = 4
  message_retention = 3
}

# Create Event Hub Authorization Rule (SAS Policy with Send and Listen rights for simulation)
resource "azurerm_eventhub_authorization_rule" "example" {
  name                = "ehpolicy${random_string.suffix.result}"
  namespace_name      = azurerm_eventhub_namespace.example.name
  eventhub_name       = azurerm_eventhub.example.name
  resource_group_name = azurerm_resource_group.example.name
  listen              = true
  send                = true
  manage              = false
}

# Grant current user Azure Event Hubs Data Sender role for passwordless authentication
resource "azurerm_role_assignment" "eventhub_sender" {
  scope                = azurerm_eventhub.example.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = data.azurerm_client_config.current.object_id
}

# =============================================================================
# AZURE OPENAI (Cognitive Services)
# =============================================================================

# Create Azure OpenAI Account
resource "azurerm_cognitive_account" "openai" {
  name                  = "openai-fabric-${random_string.suffix.result}"
  location              = azurerm_resource_group.example.location
  resource_group_name   = azurerm_resource_group.example.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "openai-fabric-${random_string.suffix.result}"

  tags = local.common_tags
}

# Create GPT-4o-mini Deployment
resource "azurerm_cognitive_deployment" "gpt4o_mini" {
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

# Create GPT-5.1 Deployment
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

# Assign Cognitive Services OpenAI User role to current user
resource "azurerm_role_assignment" "openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

# =============================================================================
# STAGING STORAGE ACCOUNT (Sync Pipeline)
# =============================================================================

resource "azurerm_storage_account" "staging" {
  name                     = "staging${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.example.name
  location                 = azurerm_resource_group.example.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  # Public access for SAS-based uploads from local machine
  public_network_access_enabled = true
  tags                          = local.common_tags
}

resource "azurerm_storage_container" "postgres" {
  name                  = "postgres"
  storage_account_id    = azurerm_storage_account.staging.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "cosmos" {
  name                  = "cosmos"
  storage_account_id    = azurerm_storage_account.staging.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "eventhub" {
  name                  = "eventhub"
  storage_account_id    = azurerm_storage_account.staging.id
  container_access_type = "private"
}

# Create CosmosDB Account
resource "azurerm_cosmosdb_account" "example" {
  name                = "fabric${random_string.suffix.result}cosmos"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # dev: public access for functional testing; prod: private endpoints only
  public_network_access_enabled = local.is_prod ? false : true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.example.location
    failover_priority = 0
  }

  # Enable continuous backup (Point-in-Time Restore)
  backup {
    type = "Continuous"
    tier = "Continuous7Days" # Options: Continuous7Days or Continuous30Days
  }

  tags = local.common_tags
}

# Create CosmosDB SQL Database (shared autoscale throughput across all containers)
resource "azurerm_cosmosdb_sql_database" "example" {
  name                = "fabric${random_string.suffix.result}db"
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name

  autoscale_settings {
    max_throughput = 10000
  }
}

# Note: Application containers (Customers, Carts, etc.) are created dynamically by seed scripts
# Infrastructure should only manage the CosmosDB Account and Database

# Create CosmosDB SQL Role Definition (Built-in Data Contributor)
resource "azurerm_cosmosdb_sql_role_definition" "example" {
  name                = "Custom Data Contributor Role"
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name
  type                = "CustomRole"
  assignable_scopes   = [azurerm_cosmosdb_account.example.id]

  permissions {
    data_actions = [
      "Microsoft.DocumentDB/databaseAccounts/readMetadata",
      "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/*",
      "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/*"
    ]
  }
}

# Assign CosmosDB Data Contributor role to current user
resource "azurerm_cosmosdb_sql_role_assignment" "example" {
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name
  role_definition_id  = azurerm_cosmosdb_sql_role_definition.example.id
  principal_id        = data.azurerm_client_config.current.object_id
  scope               = azurerm_cosmosdb_account.example.id
}

# =============================================================================
# PHASE 2: POSTGRESQL (PRIVATE MODE)
# =============================================================================

# Create PostgreSQL Flexible Server
resource "azurerm_postgresql_flexible_server" "example" {
  name                = "fabric${random_string.suffix.result}psql"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  administrator_login    = "psqladmin"
  administrator_password = random_password.postgresql_admin.result

  sku_name   = "GP_Standard_D2s_v3"
  storage_mb = 32768
  version    = "16"

  backup_retention_days = 7

  # dev: public access for functional testing; prod: private via VNET
  public_network_access_enabled = local.is_prod ? false : true

  # Enable System-Assigned Managed Identity (required for Fabric mirroring)
  identity {
    type = "SystemAssigned"
  }

  # Enable Azure AD authentication (required for managed identity admin)
  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = true
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }

  lifecycle {
    ignore_changes = [zone]
  }

  tags = local.common_tags
}

# Allow Azure services to access PostgreSQL (required for Fabric mirroring)
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAllAzureServicesAndResourcesWithinAzureIps"
  server_id        = azurerm_postgresql_flexible_server.example.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# # PostgreSQL Server Configuration: Set wal_level to logical (required for CDC/mirroring)
# resource "azurerm_postgresql_flexible_server_configuration" "wal_level" {
#   name      = "wal_level"
#   server_id = azurerm_postgresql_flexible_server.example.id
#   value     = "logical"
# }

# # PostgreSQL Server Configuration: Allowlist azure_cdc extension
# # (commented out - azure_cdc not yet available; Fabric mirroring may configure this automatically)
# resource "azurerm_postgresql_flexible_server_configuration" "azure_extensions" {
#   name      = "azure.extensions"
#   server_id = azurerm_postgresql_flexible_server.example.id
#   value     = "azure_cdc"
# }

# # PostgreSQL Server Configuration: Preload azure_cdc extension (requires restart)
# # (commented out - azure_cdc not yet available; Fabric mirroring may configure this automatically)
# resource "azurerm_postgresql_flexible_server_configuration" "shared_preload_libraries" {
#   name      = "shared_preload_libraries"
#   server_id = azurerm_postgresql_flexible_server.example.id
#   value     = "azure_cdc"
# }

# # PostgreSQL Server Configuration: Increase max_worker_processes
# # Default is 8, add 3 for each mirrored database (assuming 1 mirrored database = 11)
# resource "azurerm_postgresql_flexible_server_configuration" "max_worker_processes" {
#   name      = "max_worker_processes"
#   server_id = azurerm_postgresql_flexible_server.example.id
#   value     = "11"
# }

# Create PostgreSQL Flexible Server Database
resource "azurerm_postgresql_flexible_server_database" "example" {
  name      = "fabric${random_string.suffix.result}database"
  server_id = azurerm_postgresql_flexible_server.example.id
  collation = "en_US.utf8"
  charset   = "utf8"
}


# ============================================================================
# Azure Container Apps Configuration
# ============================================================================

# =============================================================================
# PHASE 4: PRIVATE ENDPOINTS FOR ALL SERVICES
# =============================================================================

# Private Endpoint for Key Vault
resource "azurerm_private_endpoint" "keyvault" {
  count               = local.is_prod ? 1 : 0
  name                = "pe-keyvault-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.keyvault_pe[0].id

  private_service_connection {
    name                           = "psc-keyvault"
    private_connection_resource_id = azurerm_key_vault.main.id
    is_manual_connection           = false
    subresource_names              = ["vault"]
  }

  private_dns_zone_group {
    name                 = "keyvault-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.keyvault[0].id]
  }

  tags = local.common_tags
}

# Private Endpoint for CosmosDB
resource "azurerm_private_endpoint" "cosmosdb" {
  count               = local.is_prod ? 1 : 0
  name                = "pe-cosmosdb-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints[0].id

  private_service_connection {
    name                           = "psc-cosmosdb"
    private_connection_resource_id = azurerm_cosmosdb_account.example.id
    is_manual_connection           = false
    subresource_names              = ["Sql"]
  }

  private_dns_zone_group {
    name                 = "cosmosdb-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.cosmosdb[0].id]
  }

  tags = local.common_tags
}

# Private Endpoint for Event Hub
resource "azurerm_private_endpoint" "eventhub" {
  count               = local.is_prod ? 1 : 0
  name                = "pe-eventhub-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints[0].id

  private_service_connection {
    name                           = "psc-eventhub"
    private_connection_resource_id = azurerm_eventhub_namespace.example.id
    is_manual_connection           = false
    subresource_names              = ["namespace"]
  }

  private_dns_zone_group {
    name                 = "eventhub-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.eventhub[0].id]
  }

  tags = local.common_tags
}

# Private Endpoint for Azure OpenAI (Cognitive Services)
resource "azurerm_private_endpoint" "cognitive" {
  count               = local.is_prod ? 1 : 0
  name                = "pe-cognitive-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints[0].id

  private_service_connection {
    name                           = "psc-cognitive"
    private_connection_resource_id = azurerm_cognitive_account.openai.id
    is_manual_connection           = false
    subresource_names              = ["account"]
  }

  private_dns_zone_group {
    name                 = "cognitive-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.cognitive[0].id]
  }

  tags = local.common_tags
}

# Private Endpoint for Container Registry
resource "azurerm_private_endpoint" "acr" {
  count               = local.is_prod ? 1 : 0
  name                = "pe-acr-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints[0].id

  private_service_connection {
    name                           = "psc-acr"
    private_connection_resource_id = azurerm_container_registry.acr.id
    is_manual_connection           = false
    subresource_names              = ["registry"]
  }

  private_dns_zone_group {
    name                 = "acr-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr[0].id]
  }

  tags = local.common_tags

  depends_on = [azurerm_key_vault.main]
}

# =============================================================================
# PHASE 5: MANAGED IDENTITY AUTHENTICATION
# =============================================================================

# Container Registry (with managed identity authentication)
resource "azurerm_container_registry" "acr" {
  name                = "acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.example.name
  location            = azurerm_resource_group.example.location
  sku                 = local.is_prod ? "Premium" : "Basic" # Premium required for private endpoints
  admin_enabled       = false                               # Disabled - using managed identity instead

  # dev: public access; prod: private endpoints only
  public_network_access_enabled = local.is_prod ? false : true

  dynamic "network_rule_set" {
    for_each = local.is_prod ? [1] : []
    content {
      default_action = "Deny"
    }
  }

  tags = local.common_tags
}

# =============================================================================
# PHASE 3: CONTAINER APPS ENVIRONMENT WITH VNET INTEGRATION
# =============================================================================

# Container Apps Environment with VNET integration
resource "azurerm_container_app_environment" "env" {
  name                       = "cae-retailchat-${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.example.name
  location                   = azurerm_resource_group.example.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.example.id

  # dev: no VNET (fast deploy/destroy); prod: VNET integration
  infrastructure_subnet_id       = local.is_prod ? azurerm_subnet.containerapp[0].id : null
  internal_load_balancer_enabled = local.is_prod ? false : null

  tags = local.common_tags
}

# =============================================================================
# CONTAINER APP JOB — IMPORTER (Manual trigger, runs inside VNET)
# =============================================================================

resource "azurerm_container_app_job" "importer" {
  name                         = "caj-importer-${random_string.suffix.result}"
  resource_group_name          = azurerm_resource_group.example.name
  location                     = azurerm_resource_group.example.location
  container_app_environment_id = azurerm_container_app_environment.env.id

  replica_timeout_in_seconds = 1800
  replica_retry_limit        = 1

  # Manual trigger mode — started via `az containerapp job start`
  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type = "SystemAssigned"
  }

  # registry block added by `make sync-deploy` after AcrPull role exists

  template {
    container {
      name   = "importer"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # placeholder — update via `make sync-deploy`
      cpu    = 2.0
      memory = "4Gi"

      env {
        name  = "POSTGRES_FQDN"
        value = azurerm_postgresql_flexible_server.example.fqdn
      }
      env {
        name  = "POSTGRES_DB_NAME"
        value = azurerm_postgresql_flexible_server_database.example.name
      }
      env {
        name  = "POSTGRES_USER"
        value = azurerm_postgresql_flexible_server.example.administrator_login
      }
      env {
        name  = "POSTGRES_PASSWORD"
        value = random_password.postgresql_admin.result
      }
      env {
        name  = "COSMOSDB_ENDPOINT"
        value = azurerm_cosmosdb_account.example.endpoint
      }
      env {
        name  = "COSMOSDB_DB_NAME"
        value = azurerm_cosmosdb_sql_database.example.name
      }
      env {
        name  = "EVENTHUB_NAMESPACE"
        value = "${azurerm_eventhub_namespace.example.name}.servicebus.windows.net"
      }
      env {
        name  = "EVENTHUB_NAME"
        value = azurerm_eventhub.example.name
      }
      env {
        name  = "STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.staging.name
      }
    }
  }

  tags = local.common_tags
}

# =============================================================================
# RBAC FOR IMPORTER MANAGED IDENTITY
# =============================================================================

# Pull images from ACR
resource "azurerm_role_assignment" "importer_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app_job.importer.identity[0].principal_id
}

# Read staging blobs
resource "azurerm_role_assignment" "importer_blob_reader" {
  scope                = azurerm_storage_account.staging.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_container_app_job.importer.identity[0].principal_id
}

# Write to Cosmos DB
resource "azurerm_cosmosdb_sql_role_assignment" "importer" {
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name
  role_definition_id  = azurerm_cosmosdb_sql_role_definition.example.id
  principal_id        = azurerm_container_app_job.importer.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.example.id
}

# Send to Event Hub
resource "azurerm_role_assignment" "importer_eventhub_sender" {
  scope                = azurerm_eventhub.example.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = azurerm_container_app_job.importer.identity[0].principal_id
}

# AAD admin on Postgres for managed identity auth
resource "azurerm_postgresql_flexible_server_active_directory_administrator" "importer" {
  server_name         = azurerm_postgresql_flexible_server.example.name
  resource_group_name = azurerm_resource_group.example.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  object_id           = azurerm_container_app_job.importer.identity[0].principal_id
  principal_name      = "caj-importer-${random_string.suffix.result}"
  principal_type      = "ServicePrincipal"
}

# =============================================================================
# CONTAINER APPS — DASHBOARD + AGENTS
# =============================================================================

# ── Dashboard ────────────────────────────────────────────────────

resource "azurerm_container_app" "dashboard" {
  name                         = local.ca_dashboard
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.example.name
  revision_mode                = "Single"

  timeouts {
    create = "30m"
    update = "30m"
  }

  identity { type = "SystemAssigned" }

  # registry block added by `make cloud-deploy` after AcrPull role exists

  ingress {
    external_enabled = true
    target_port      = 3001
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2
    container {
      name   = "dashboard"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # placeholder — update via make cloud-deploy
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "DASHBOARD_API_PORT"
        value = "3001"
      }
      env {
        name  = "FABRIC_SQL_ENDPOINT"
        value = var.fabric_sql_endpoint
      }
      env {
        name  = "FABRIC_SQL_DATABASE"
        value = "postgres-mirror"
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = "https://${local.ca_dashboard}.${azurerm_container_app_environment.env.default_domain}"
      }
      env {
        name  = "AGENT1_URL"
        value = "http://${local.ca_agent1}"
      }
      env {
        name  = "AGENT2_URL"
        value = "http://${local.ca_agent2}"
      }
      env {
        name  = "AGENT3_URL"
        value = "http://${local.ca_agent3}"
      }

      # liveness_probe and readiness_probe added back after real image deploy
    }
  }

  tags = local.common_tags
}

# ── Agent 1 — Explainer ─────────────────────────────────────────

resource "azurerm_container_app" "agent1" {
  name                         = local.ca_agent1
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.example.name
  revision_mode                = "Single"

  timeouts {
    create = "30m"
    update = "30m"
  }

  identity { type = "SystemAssigned" }

  # registry block added by `make cloud-deploy` after AcrPull role exists

  ingress {
    external_enabled = false
    target_port      = 8001
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2
    container {
      name   = "agent1"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # placeholder
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AGENT_MODEL"
        value = "gpt-4o-mini"
      }
      env {
        name  = "FABRIC_SQL_ENDPOINT"
        value = var.fabric_sql_endpoint
      }
      env {
        name  = "FABRIC_SQL_DATABASE"
        value = "postgres-mirror"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }

      # liveness_probe and readiness_probe added back after real image deploy
    }
  }

  tags = local.common_tags
}

# ── Agent 2 — Narrative ─────────────────────────────────────────

resource "azurerm_container_app" "agent2" {
  name                         = local.ca_agent2
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.example.name
  revision_mode                = "Single"

  timeouts {
    create = "30m"
    update = "30m"
  }

  identity { type = "SystemAssigned" }

  # registry block added by `make cloud-deploy` after AcrPull role exists

  ingress {
    external_enabled = false
    target_port      = 8002
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2
    container {
      name   = "agent2"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # placeholder
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AGENT_MODEL"
        value = "gpt-5.2"
      }
      env {
        name  = "FABRIC_SQL_ENDPOINT"
        value = var.fabric_sql_endpoint
      }
      env {
        name  = "FABRIC_SQL_DATABASE"
        value = "postgres-mirror"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }

      # liveness_probe and readiness_probe added back after real image deploy
    }
  }

  tags = local.common_tags
}

# ── Agent 3 — Sentiment ─────────────────────────────────────────

resource "azurerm_container_app" "agent3" {
  name                         = local.ca_agent3
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.example.name
  revision_mode                = "Single"

  timeouts {
    create = "30m"
    update = "30m"
  }

  identity { type = "SystemAssigned" }

  # registry block added by `make cloud-deploy` after AcrPull role exists

  ingress {
    external_enabled = false
    target_port      = 8003
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2
    container {
      name   = "agent3"
      image  = "mcr.microsoft.com/k8se/quickstart:latest" # placeholder
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "AGENT_MODEL"
        value = "gpt-4o-mini"
      }
      env {
        name  = "FABRIC_SQL_ENDPOINT"
        value = var.fabric_sql_endpoint
      }
      env {
        name  = "FABRIC_SQL_DATABASE"
        value = "postgres-mirror"
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }

      # liveness_probe and readiness_probe added back after real image deploy
    }
  }

  tags = local.common_tags
}

# =============================================================================
# RBAC FOR CONTAINER APP MANAGED IDENTITIES
# =============================================================================

# ── AcrPull — all 4 apps ────────────────────────────────────────

resource "azurerm_role_assignment" "dashboard_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.dashboard.identity[0].principal_id
}

resource "azurerm_role_assignment" "agent1_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.agent1.identity[0].principal_id
}

resource "azurerm_role_assignment" "agent2_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.agent2.identity[0].principal_id
}

resource "azurerm_role_assignment" "agent3_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_container_app.agent3.identity[0].principal_id
}

# ── Cognitive Services OpenAI User — agents only ─────────────────

resource "azurerm_role_assignment" "agent1_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_container_app.agent1.identity[0].principal_id
}

resource "azurerm_role_assignment" "agent2_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_container_app.agent2.identity[0].principal_id
}

resource "azurerm_role_assignment" "agent3_openai" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_container_app.agent3.identity[0].principal_id
}

# =============================================================================
# LOG ANALYTICS WORKSPACE - Central monitoring for all resources
# =============================================================================

resource "azurerm_log_analytics_workspace" "example" {
  name                = "fabric${random_string.suffix.result}logs"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = local.common_tags
}

# =============================================================================
# DIAGNOSTIC SETTINGS - Send all logs and metrics to Log Analytics
# =============================================================================

# CosmosDB Diagnostic Settings
resource "azurerm_monitor_diagnostic_setting" "cosmosdb" {
  name                       = "cosmosdb-diagnostics"
  target_resource_id         = azurerm_cosmosdb_account.example.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.example.id

  # Enable all log categories
  enabled_log {
    category = "DataPlaneRequests"
  }
  enabled_log {
    category = "QueryRuntimeStatistics"
  }
  enabled_log {
    category = "PartitionKeyStatistics"
  }
  enabled_log {
    category = "PartitionKeyRUConsumption"
  }
  enabled_log {
    category = "ControlPlaneRequests"
  }
  enabled_log {
    category = "TableApiRequests"
  }

  # Enable all metrics
  enabled_metric {
    category = "Requests"
  }
}

# PostgreSQL Flexible Server Diagnostic Settings
resource "azurerm_monitor_diagnostic_setting" "postgresql" {
  name                       = "postgresql-diagnostics"
  target_resource_id         = azurerm_postgresql_flexible_server.example.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.example.id

  # Enable all log categories
  enabled_log {
    category = "PostgreSQLLogs"
  }
  enabled_log {
    category = "PostgreSQLFlexSessions"
  }
  enabled_log {
    category = "PostgreSQLFlexQueryStoreRuntime"
  }
  enabled_log {
    category = "PostgreSQLFlexQueryStoreWaitStats"
  }
  enabled_log {
    category = "PostgreSQLFlexTableStats"
  }
  enabled_log {
    category = "PostgreSQLFlexDatabaseXacts"
  }

  # Enable all metrics
  enabled_metric {
    category = "AllMetrics"
  }
}

# Event Hub Namespace Diagnostic Settings
resource "azurerm_monitor_diagnostic_setting" "eventhub" {
  name                       = "eventhub-diagnostics"
  target_resource_id         = azurerm_eventhub_namespace.example.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.example.id

  # Enable all log categories
  enabled_log {
    category = "ArchiveLogs"
  }
  enabled_log {
    category = "OperationalLogs"
  }
  enabled_log {
    category = "AutoScaleLogs"
  }
  enabled_log {
    category = "KafkaCoordinatorLogs"
  }
  enabled_log {
    category = "KafkaUserErrorLogs"
  }
  enabled_log {
    category = "EventHubVNetConnectionEvent"
  }
  enabled_log {
    category = "CustomerManagedKeyUserLogs"
  }
  enabled_log {
    category = "RuntimeAuditLogs"
  }
  enabled_log {
    category = "ApplicationMetricsLogs"
  }

  # Enable all metrics
  enabled_metric {
    category = "AllMetrics"
  }
}

# Container Registry Diagnostic Settings
resource "azurerm_monitor_diagnostic_setting" "acr" {
  name                       = "acr-diagnostics"
  target_resource_id         = azurerm_container_registry.acr.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.example.id

  # Enable all log categories
  enabled_log {
    category = "ContainerRegistryRepositoryEvents"
  }
  enabled_log {
    category = "ContainerRegistryLoginEvents"
  }

  # Enable all metrics
  enabled_metric {
    category = "AllMetrics"
  }
}

# =============================================================================
# OUTPUTS
# =============================================================================

# Details of the Fabric Capacity
output "fabric_capacity" {
  value       = data.fabric_capacity.example
  description = "The Fabric Capacity object"
}

# Details of the Fabric Workspace
output "fabric_workspace" {
  value       = fabric_workspace.example
  description = "The Fabric Workspace object"
}

# Resource Group Name
output "resource_group" {
  value       = azurerm_resource_group.example.name
  description = "The name of the resource group"
}

# Event Hub Namespace
output "event_hub_namespace" {
  value       = azurerm_eventhub_namespace.example.name
  description = "The name of the Event Hub namespace"
}

# Event Hub Namespace Connection String
output "event_hub_namespace_conn_string" {
  value       = azurerm_eventhub_namespace.example.default_primary_connection_string
  description = "The primary connection string for the Event Hub namespace"
  sensitive   = true
}

# Event Hub Name
output "event_hub" {
  value       = azurerm_eventhub.example.name
  description = "The name of the Event Hub"
}

# Event Hub Policy Name
output "event_hub_policy" {
  value       = azurerm_eventhub_authorization_rule.example.name
  description = "The name of the Event Hub authorization rule"
}

# Event Hub Primary Key
output "event_hub_primary_key" {
  value       = azurerm_eventhub_authorization_rule.example.primary_key
  description = "The primary key for the Event Hub authorization rule"
  sensitive   = true
}

# Event Hub Authorization Rule Connection String (with Send permissions)
output "event_hub_connection_string" {
  value       = azurerm_eventhub_authorization_rule.example.primary_connection_string
  description = "The connection string for the Event Hub authorization rule with Send/Listen permissions"
  sensitive   = true
}

# Staging Storage Account Name
output "staging_storage_account_name" {
  value       = azurerm_storage_account.staging.name
  description = "The name of the staging storage account"
}

# Staging Storage Account Connection String
output "staging_storage_conn_string" {
  value       = azurerm_storage_account.staging.primary_connection_string
  description = "The primary connection string for the staging storage account"
  sensitive   = true
}

# CosmosDB Account Name
output "cosmosdb_account_name" {
  value       = azurerm_cosmosdb_account.example.name
  description = "The name of the CosmosDB account"
}

# CosmosDB Endpoint
output "cosmosdb_endpoint" {
  value       = azurerm_cosmosdb_account.example.endpoint
  description = "The endpoint for the CosmosDB account"
}

# CosmosDB Primary Key
output "cosmosdb_primary_key" {
  value       = azurerm_cosmosdb_account.example.primary_key
  description = "The primary key for the CosmosDB account"
  sensitive   = true
}

# CosmosDB Connection String
output "cosmosdb_connection_string" {
  value       = azurerm_cosmosdb_account.example.primary_sql_connection_string
  description = "The primary SQL connection string for the CosmosDB account"
  sensitive   = true
}

# CosmosDB Database Name
output "cosmosdb_database_name" {
  value       = azurerm_cosmosdb_sql_database.example.name
  description = "The name of the CosmosDB database"
}

# PostgreSQL Server Name
output "postgresql_server_name" {
  value       = azurerm_postgresql_flexible_server.example.name
  description = "The name of the PostgreSQL flexible server"
}

# PostgreSQL Server FQDN
output "postgresql_server_fqdn" {
  value       = azurerm_postgresql_flexible_server.example.fqdn
  description = "The FQDN of the PostgreSQL flexible server"
}

# PostgreSQL Administrator Login
output "postgresql_admin_login" {
  value       = azurerm_postgresql_flexible_server.example.administrator_login
  description = "The administrator login for the PostgreSQL server"
}

# PostgreSQL Administrator Password
output "postgresql_admin_password" {
  value       = azurerm_postgresql_flexible_server.example.administrator_password
  description = "The administrator password for the PostgreSQL server"
  sensitive   = true
}

# PostgreSQL Database Name
output "postgresql_database_name" {
  value       = azurerm_postgresql_flexible_server_database.example.name
  description = "The name of the PostgreSQL database"
}

# Log Analytics Workspace Name
output "log_analytics_workspace_name" {
  value       = azurerm_log_analytics_workspace.example.name
  description = "The name of the Log Analytics workspace"
}

# Log Analytics Workspace ID
output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.example.workspace_id
  description = "The workspace ID of the Log Analytics workspace"
}

# Container Registry Name
output "container_registry_name" {
  value       = azurerm_container_registry.acr.name
  description = "The name of the Azure Container Registry"
}

# Container Registry Login Server
output "container_registry_login_server" {
  value       = azurerm_container_registry.acr.login_server
  description = "The login server URL for the Azure Container Registry"
}

# =============================================================================
# KEY VAULT OUTPUTS
# =============================================================================

# Key Vault Name
output "key_vault_name" {
  value       = azurerm_key_vault.main.name
  description = "The name of the Key Vault"
}

# Key Vault ID
output "key_vault_id" {
  value       = azurerm_key_vault.main.id
  description = "The ID of the Key Vault"
}

# =============================================================================
# AZURE OPENAI OUTPUTS
# =============================================================================

# Azure OpenAI Account Name
output "openai_account_name" {
  value       = azurerm_cognitive_account.openai.name
  description = "The name of the Azure OpenAI account"
}

# Azure OpenAI Endpoint
output "openai_endpoint" {
  value       = azurerm_cognitive_account.openai.endpoint
  description = "The endpoint for the Azure OpenAI account"
}

# GPT-4o-mini Deployment Name
output "openai_deployment_gpt4o_mini" {
  value       = azurerm_cognitive_deployment.gpt4o_mini.name
  description = "The name of the GPT-4o-mini deployment"
}

# GPT-5.1 Deployment Name
output "openai_deployment_gpt52" {
  value       = azurerm_cognitive_deployment.gpt52.name
  description = "The name of the GPT-5.1 deployment"
}

# Container App Job (Importer) Name
output "importer_job_name" {
  value       = azurerm_container_app_job.importer.name
  description = "The name of the importer Container App Job"
}

# =============================================================================
# CONTAINER APP OUTPUTS
# =============================================================================

output "dashboard_url" {
  value       = "https://${azurerm_container_app.dashboard.ingress[0].fqdn}"
  description = "The public URL of the dashboard Container App"
}

output "dashboard_app_name" {
  value       = azurerm_container_app.dashboard.name
  description = "The name of the dashboard Container App"
}

output "agent1_app_name" {
  value       = azurerm_container_app.agent1.name
  description = "The name of Agent 1 (Explainer) Container App"
}

output "agent2_app_name" {
  value       = azurerm_container_app.agent2.name
  description = "The name of Agent 2 (Narrative) Container App"
}

output "agent3_app_name" {
  value       = azurerm_container_app.agent3.name
  description = "The name of Agent 3 (Sentiment) Container App"
}

output "fabric_sql_endpoint" {
  value       = var.fabric_sql_endpoint
  description = "Fabric SQL endpoint (empty if not configured)"
}

# Generate .env file for local development
resource "local_file" "env_file" {
  filename = "${path.module}/../.env"
  content  = <<-EOT
    # Generated by Terraform - CosmosDB + PostgreSQL + Event Hub + OpenAI configuration
    AZURE_RESOURCE_GROUP=${azurerm_resource_group.example.name}

    COSMOSDB_ACCOUNT_NAME=${azurerm_cosmosdb_account.example.name}
    COSMOSDB_ENDPOINT=${azurerm_cosmosdb_account.example.endpoint}
    COSMOSDB_DATABASE_NAME=${azurerm_cosmosdb_sql_database.example.name}
    COSMOSDB_PRIMARY_KEY=${azurerm_cosmosdb_account.example.primary_key}
    COSMOSDB_CONNECTION_STRING='${azurerm_cosmosdb_account.example.primary_sql_connection_string}'

    POSTGRES_SERVER_NAME=${azurerm_postgresql_flexible_server.example.name}
    POSTGRES_FQDN=${azurerm_postgresql_flexible_server.example.fqdn}
    POSTGRES_DB_NAME=${azurerm_postgresql_flexible_server_database.example.name}
    POSTGRES_ADMIN_LOGIN=${azurerm_postgresql_flexible_server.example.administrator_login}
    POSTGRES_ADMIN_PASSWORD='${azurerm_postgresql_flexible_server.example.administrator_password}'

    EVENTHUB_NAMESPACE=${azurerm_eventhub_namespace.example.name}
    EVENTHUB_NAME=${azurerm_eventhub.example.name}
    EVENTHUB_POLICY_NAME=${azurerm_eventhub_authorization_rule.example.name}
    EVENTHUB_CONNECTION_STRING='${azurerm_eventhub_authorization_rule.example.primary_connection_string}'

    AZURE_OPENAI_ENDPOINT=${azurerm_cognitive_account.openai.endpoint}
    AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI=${azurerm_cognitive_deployment.gpt4o_mini.name}
    AZURE_OPENAI_DEPLOYMENT_GPT52=${azurerm_cognitive_deployment.gpt52.name}

    STAGING_STORAGE_ACCOUNT=${azurerm_storage_account.staging.name}
    STAGING_STORAGE_CONN_STRING='${azurerm_storage_account.staging.primary_connection_string}'

    FABRIC_WORKSPACE_ID=${fabric_workspace.example.id}
    FABRIC_SQL_ENDPOINT=${var.fabric_sql_endpoint}

    DASHBOARD_URL=https://${azurerm_container_app.dashboard.ingress[0].fqdn}
    DASHBOARD_APP_NAME=${azurerm_container_app.dashboard.name}
    AGENT1_APP_NAME=${azurerm_container_app.agent1.name}
    AGENT2_APP_NAME=${azurerm_container_app.agent2.name}
    AGENT3_APP_NAME=${azurerm_container_app.agent3.name}
  EOT
}

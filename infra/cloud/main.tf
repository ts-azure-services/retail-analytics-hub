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
    # fabric = {
    #   source  = "microsoft/fabric"
    #   version = "1.7.0"
    # }
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

# provider "fabric" {
# }

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

locals {
  # Common tags applied to all resources
  common_tags = {
    tf = "cloud"
    SecurityControl  = "Ignore"
  }
}

# Create a resource group.
resource "azurerm_resource_group" "example" {
  name     = "rg-fabric-${random_string.suffix.result}"
  location = "WestUS3"

  tags = local.common_tags
}

# =============================================================================
# PHASE 1: ZERO-TRUST FOUNDATION - VNET, SUBNETS, NSGs
# =============================================================================

/*
# Virtual Network
resource "azurerm_virtual_network" "main" {
  name                = "vnet-fabric-${random_string.suffix.result}"
  address_space       = ["10.0.0.0/16"]
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Subnet for Container Apps Environment (delegated to Microsoft.App/environments)
resource "azurerm_subnet" "containerapp" {
  name                 = "snet-containerapp"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main.name
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
  name                 = "snet-postgresql"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main.name
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
  name                 = "snet-privateendpoints"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.3.0/24"]
}

# Subnet for Key Vault Private Endpoint (isolated for security)
resource "azurerm_subnet" "keyvault_pe" {
  name                 = "snet-keyvault-pe"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.4.0/28"]
}

# Subnet for future management resources (Bastion, VMs, etc.)
resource "azurerm_subnet" "management" {
  name                 = "snet-management"
  resource_group_name  = azurerm_resource_group.example.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.0.5.0/24"]
}

# =============================================================================
# BASTION HOST FOR MANAGEMENT AND DATABASE ACCESS
# =============================================================================

# Public IP for Bastion Host
resource "azurerm_public_ip" "bastion" {
  name                = "pip-bastion-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  allocation_method   = "Static"
  sku                 = "Standard"

  tags = local.common_tags
}

# Network Interface for Bastion Host
resource "azurerm_network_interface" "bastion" {
  name                = "nic-bastion-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.management.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.bastion.id
  }

  tags = local.common_tags
}

# Network Security Group for Bastion Host
resource "azurerm_network_security_group" "bastion" {
  name                = "nsg-bastion-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name

  # Allow SSH from your public IP only
  security_rule {
    name                       = "AllowSSHFromClientIP"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "${trimspace(data.http.my_ip.response_body)}/32"
    destination_address_prefix = "*"
  }

  # Allow outbound to PostgreSQL subnet
  security_rule {
    name                       = "AllowPostgreSQLOutbound"
    priority                   = 100
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "*"
    destination_address_prefix = "10.0.2.0/24"
  }

  # Allow outbound to Private Endpoints subnet (CosmosDB, Storage, etc.)
  security_rule {
    name                       = "AllowPrivateEndpointsOutbound"
    priority                   = 110
    direction                  = "Outbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "10.0.3.0/24"
  }

  # Allow outbound to Internet (for package updates, etc.)
  security_rule {
    name                       = "AllowInternetOutbound"
    priority                   = 120
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

# Associate NSG with Bastion Network Interface
resource "azurerm_network_interface_security_group_association" "bastion" {
  network_interface_id      = azurerm_network_interface.bastion.id
  network_security_group_id = azurerm_network_security_group.bastion.id
}

# Bastion Host Virtual Machine
resource "azurerm_linux_virtual_machine" "bastion" {
  name                = "vm-bastion-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  size                = "Standard_B2s"
  admin_username      = "azureuser"

  # Enable System-Assigned Managed Identity for Azure resource access
  identity {
    type = "SystemAssigned"
  }

  network_interface_ids = [
    azurerm_network_interface.bastion.id,
  ]

  admin_ssh_key {
    username   = "azureuser"
    public_key = file("~/.ssh/id_rsa.pub")
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  # Install development tools and uv
  custom_data = base64encode(<<-EOF
    #!/bin/bash
    set -e

    # Update package list
    apt-get update

    # Install development and networking tools
    apt-get install -y \
      make \
      tree \
      jq \
      curl \
      wget \
      git \
      vim \
      htop \
      net-tools \
      dnsutils \
      iputils-ping \
      traceroute \
      unzip \
      zip \
      build-essential \
      ca-certificates

    # Install uv (Python package installer)
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Make uv available system-wide
    ln -s /root/.local/bin/uv /usr/local/bin/uv

    # Install Azure CLI for managing Azure resources
    curl -sL https://aka.ms/InstallAzureCLIDeb | bash

    echo "Bastion host setup complete" > /var/log/bastion-setup.log
    EOF
  )

  tags = local.common_tags

  depends_on = [
    azurerm_network_interface_security_group_association.bastion
  ]
}

# Grant Bastion Host managed identity access to CosmosDB
resource "azurerm_cosmosdb_sql_role_assignment" "bastion" {
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name
  role_definition_id  = azurerm_cosmosdb_sql_role_definition.example.id
  principal_id        = azurerm_linux_virtual_machine.bastion.identity[0].principal_id
  scope               = azurerm_cosmosdb_account.example.id
}

# Grant Bastion Host managed identity Key Vault Secrets User role
resource "azurerm_role_assignment" "bastion_kv_secrets_user" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.bastion.identity[0].principal_id
}

# Network Security Group for Container App Subnet
resource "azurerm_network_security_group" "containerapp" {
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
  subnet_id                 = azurerm_subnet.containerapp.id
  network_security_group_id = azurerm_network_security_group.containerapp.id
}

# Network Security Group for PostgreSQL Subnet
resource "azurerm_network_security_group" "postgresql" {
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

  # Allow PostgreSQL inbound from Bastion Host (management subnet)
  security_rule {
    name                       = "AllowPostgreSQLFromBastion"
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
  subnet_id                 = azurerm_subnet.postgresql.id
  network_security_group_id = azurerm_network_security_group.postgresql.id
}

# Network Security Group for Private Endpoints Subnet
resource "azurerm_network_security_group" "privateendpoints" {
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
  subnet_id                 = azurerm_subnet.privateendpoints.id
  network_security_group_id = azurerm_network_security_group.privateendpoints.id
}

# Network Security Group for Key Vault Subnet
resource "azurerm_network_security_group" "keyvault" {
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
  subnet_id                 = azurerm_subnet.keyvault_pe.id
  network_security_group_id = azurerm_network_security_group.keyvault.id
}

# =============================================================================
# PHASE 1: DNS PRIVATE ZONES
# =============================================================================

# DNS Private Zone for CosmosDB
resource "azurerm_private_dns_zone" "cosmosdb" {
  name                = "privatelink.documents.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link CosmosDB DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "cosmosdb" {
  name                  = "cosmosdb-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.cosmosdb.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Storage Account (File)
resource "azurerm_private_dns_zone" "storage_file" {
  name                = "privatelink.file.core.windows.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Storage File DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "storage_file" {
  name                  = "storage-file-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.storage_file.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Event Hub
resource "azurerm_private_dns_zone" "eventhub" {
  name                = "privatelink.servicebus.windows.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Event Hub DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "eventhub" {
  name                  = "eventhub-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.eventhub.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Container Registry
resource "azurerm_private_dns_zone" "acr" {
  name                = "privatelink.azurecr.io"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link ACR DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "acr" {
  name                  = "acr-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.acr.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for Key Vault
resource "azurerm_private_dns_zone" "keyvault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Key Vault DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
  name                  = "keyvault-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.keyvault.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for AI Foundry (Cognitive Services)
resource "azurerm_private_dns_zone" "cognitive" {
  name                = "privatelink.cognitiveservices.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link Cognitive Services DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "cognitive" {
  name                  = "cognitive-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.cognitive.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

# DNS Private Zone for PostgreSQL
resource "azurerm_private_dns_zone" "postgres" {
  name                = "privatelink.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.example.name

  tags = local.common_tags
}

# Link PostgreSQL DNS Zone to VNET
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "postgres-vnet-link"
  resource_group_name   = azurerm_resource_group.example.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}
*/

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
/*
resource "azurerm_key_vault" "main" {
  name                       = "kv-fabric-${random_string.suffix.result}"
  location                   = azurerm_resource_group.example.location
  resource_group_name        = azurerm_resource_group.example.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"

  # Enable RBAC authorization (required for managed identities)
  rbac_authorization_enabled = true

  # Enable purge protection (security best practice)
  purge_protection_enabled = true

  # Soft delete with 7 days retention
  soft_delete_retention_days = 7

  # Public network access enabled initially (will be disabled after private endpoint in Phase 4)
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

# Store AI Foundry endpoint in Key Vault
resource "azurerm_key_vault_secret" "ai_foundry_endpoint" {
  name         = "ai-foundry-endpoint"
  value        = "https://${azapi_resource.ai_foundry.body.properties.customSubDomainName}.services.ai.azure.com/api/projects/${azapi_resource.ai_foundry_project.name}"
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_role_assignment.current_user_kv_admin]
}

# =============================================================================
# AZURE AI FOUNDRY PROJECT - GPT-5 Deployment (using azapi)
# =============================================================================

# Create AI Foundry Hub resource using azapi
resource "azapi_resource" "ai_foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name                      = "aifoundry-fabric-${random_string.suffix.result}"
  parent_id                 = azurerm_resource_group.example.id
  location                  = "WestUS3"
  schema_validation_enabled = false

  body = {
    kind = "AIServices"
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }

    properties = {
      # =============================================================================
      # PHASE 5: DISABLE LOCAL AUTH - Use managed identity only
      # =============================================================================
      disableLocalAuth = true  # Changed from false

      # Specifies that this is an AI Foundry resource
      allowProjectManagement = true

      # Set custom subdomain name for DNS names
      customSubDomainName = "aifoundry-fabric-${random_string.suffix.result}"

      # Keep public network access enabled for Azure AI Studio portal
      publicNetworkAccess = "Enabled"
    }
  }

  tags = local.common_tags
}

# Create GPT-4o Deployment in the AI Foundry resource
resource "azapi_resource" "aifoundry_deployment_gpt4o" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2023-05-01"
  name      = "gpt-4o"
  parent_id = azapi_resource.ai_foundry.id
  depends_on = [
    azapi_resource.ai_foundry
  ]

  body = {
    sku = {
      name     = "GlobalStandard"
      capacity = 50
    }
    properties = {
      model = {
        format  = "OpenAI"
        name    = "gpt-4o"
        version = "2024-11-20"
      }
    }
  }
}

# Create AI Foundry Project
resource "azapi_resource" "ai_foundry_project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name                      = "project-fabric-${random_string.suffix.result}"
  parent_id                 = azapi_resource.ai_foundry.id
  location                  = "WestUS3"
  schema_validation_enabled = false

  body = {
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }

    properties = {
      displayName = "Fabric Project"
      description = "AI Foundry project for fabric capstone"
    }
  }

  tags = local.common_tags
}

# Assign Azure AI User role to current user for AI Foundry Hub
resource "azurerm_role_assignment" "ai_foundry_user" {
  scope                = azapi_resource.ai_foundry.id
  role_definition_name = "Azure AI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Assign Azure AI User role to current user for AI Foundry Project
resource "azurerm_role_assignment" "ai_foundry_project_user" {
  scope                = azapi_resource.ai_foundry_project.id
  role_definition_name = "Azure AI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Create a Fabric Capacity.
resource "azurerm_fabric_capacity" "example" {
  name                = "fcfabric${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.example.name
  location            = "WestUS3"

  administration_members = [local.fabric_admin]

  sku {
    name = "F8"
    tier = "Fabric"
  }
}

# Get the Fabric Capacity details.
data "fabric_capacity" "example" {
  display_name = azurerm_fabric_capacity.example.name

  lifecycle {
    postcondition {
      condition     = self.state == "Active"
      error_message = "Fabric Capacity is not in Active state. Please check the Fabric Capacity status."
    }
  }
}

# Create a Fabric Workspace.
# https://registry.terraform.io/providers/microsoft/fabric/latest/docs/resources/workspace
resource "fabric_workspace" "example" {
  capacity_id  = data.fabric_capacity.example.id
  display_name = "ws-fabric-${random_string.suffix.result}"
}

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
  name                = "fabric${random_string.suffix.result}eventhub"
  namespace_id        = azurerm_eventhub_namespace.example.id
  partition_count     = 4
  message_retention   = 3
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

# # Create Storage Account (commented out - not needed for current simulation workflow)
# resource "azurerm_storage_account" "example" {
#   name                     = "fabric${random_string.suffix.result}sa"
#   resource_group_name      = azurerm_resource_group.example.name
#   location                 = azurerm_resource_group.example.location
#   account_tier             = "Standard"
#   account_replication_type = "LRS"
#   account_kind             = "StorageV2"
#
#   tags = local.common_tags
# }

# # Create Blob Container (commented out - not needed for current simulation workflow)
# resource "azurerm_storage_container" "example" {
#   name                  = "fabric${random_string.suffix.result}blobcontainer"
#   storage_account_id    = azurerm_storage_account.example.id
#   container_access_type = "private"
# }
*/

# Create CosmosDB Account (public-only mode for now)
resource "azurerm_cosmosdb_account" "example" {
  name                = "fabric${random_string.suffix.result}cosmos"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  # Public-only mode for now
  public_network_access_enabled = true

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.example.location
    failover_priority = 0
  }

  # Enable continuous backup (Point-in-Time Restore)
  backup {
    type                = "Continuous"
    tier                = "Continuous7Days"  # Options: Continuous7Days or Continuous30Days
  }

  tags = local.common_tags
}

# Create CosmosDB SQL Database
resource "azurerm_cosmosdb_sql_database" "example" {
  name                = "fabric${random_string.suffix.result}db"
  resource_group_name = azurerm_resource_group.example.name
  account_name        = azurerm_cosmosdb_account.example.name
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
# PHASE 2: POSTGRESQL (PUBLIC-ONLY MODE)
# =============================================================================

# Create PostgreSQL Flexible Server (public-only mode)
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

  # Public-only mode for now
  public_network_access_enabled = true

  # Enable System-Assigned Managed Identity (required for Fabric mirroring)
  identity {
    type = "SystemAssigned"
  }

  lifecycle {
    ignore_changes = [zone]
  }

  tags = local.common_tags

  # No VNET/private DNS dependencies in public-only mode
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

# =============================================================================
# PHASE 2: FIREWALL RULES REMOVED (replaced by VNET integration)
# =============================================================================
# PostgreSQL now uses VNET integration with delegated subnet
# No firewall rules needed - access is controlled by NSGs and VNET routing

# # Create PostgreSQL Flexible Server Firewall Rule to allow client machine IP only
# resource "azurerm_postgresql_flexible_server_firewall_rule" "client_ip" {
#   name             = "AllowClientIP"
#   server_id        = azurerm_postgresql_flexible_server.example.id
#   start_ip_address = trimspace(data.http.my_ip.response_body)
#   end_ip_address   = trimspace(data.http.my_ip.response_body)
# }

# # Allow Azure services to access this PostgreSQL server
# resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
#   name             = "AllowAllAzureServicesAndResourcesWithinAzureIps"
#   server_id        = azurerm_postgresql_flexible_server.example.id
#   start_ip_address = "0.0.0.0"
#   end_ip_address   = "0.0.0.0"
# }



# ============================================================================
# Azure Container Apps Configuration
# ============================================================================

# =============================================================================
# PHASE 4: PRIVATE ENDPOINTS FOR ALL SERVICES
# =============================================================================

/*
# Private Endpoint for Key Vault
resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-keyvault-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.keyvault_pe.id

  private_service_connection {
    name                           = "psc-keyvault"
    private_connection_resource_id = azurerm_key_vault.main.id
    is_manual_connection           = false
    subresource_names              = ["vault"]
  }

  private_dns_zone_group {
    name                 = "keyvault-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.keyvault.id]
  }

  tags = local.common_tags
}

# Private Endpoint for CosmosDB
resource "azurerm_private_endpoint" "cosmosdb" {
  name                = "pe-cosmosdb-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints.id

  private_service_connection {
    name                           = "psc-cosmosdb"
    private_connection_resource_id = azurerm_cosmosdb_account.example.id
    is_manual_connection           = false
    subresource_names              = ["Sql"]
  }

  private_dns_zone_group {
    name                 = "cosmosdb-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.cosmosdb.id]
  }

  tags = local.common_tags
}

# Private Endpoint for Event Hub
resource "azurerm_private_endpoint" "eventhub" {
  name                = "pe-eventhub-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints.id

  private_service_connection {
    name                           = "psc-eventhub"
    private_connection_resource_id = azurerm_eventhub_namespace.example.id
    is_manual_connection           = false
    subresource_names              = ["namespace"]
  }

  private_dns_zone_group {
    name                 = "eventhub-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.eventhub.id]
  }

  tags = local.common_tags
}

# Private Endpoint for AI Foundry (Cognitive Services)
resource "azurerm_private_endpoint" "cognitive" {
  name                = "pe-cognitive-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints.id

  private_service_connection {
    name                           = "psc-cognitive"
    private_connection_resource_id = azapi_resource.ai_foundry.id
    is_manual_connection           = false
    subresource_names              = ["account"]
  }

  private_dns_zone_group {
    name                 = "cognitive-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.cognitive.id]
  }

  tags = local.common_tags
}

# Private Endpoint for Container Registry
resource "azurerm_private_endpoint" "acr" {
  name                = "pe-acr-${random_string.suffix.result}"
  location            = azurerm_resource_group.example.location
  resource_group_name = azurerm_resource_group.example.name
  subnet_id           = azurerm_subnet.privateendpoints.id

  private_service_connection {
    name                           = "psc-acr"
    private_connection_resource_id = azurerm_container_registry.acr.id
    is_manual_connection           = false
    subresource_names              = ["registry"]
  }

  private_dns_zone_group {
    name                 = "acr-dns-zone-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.acr.id]
  }

  tags = local.common_tags

  # Create Key Vault private endpoint before disabling public access
  depends_on = [azurerm_key_vault.main]
}

# =============================================================================
# PHASE 4: UPDATE KEY VAULT - Disable Public Access After Private Endpoint
# =============================================================================

# Note: We need to update Key Vault configuration after private endpoint is created
# This is a chicken-and-egg problem: we need to create secrets first, then create PE, then disable public access
# For now, Key Vault remains with public access enabled during initial deployment
# After successful deployment, manually disable public access or add a separate apply step

# Uncomment this resource after first successful apply to disable public access:
# resource "null_resource" "disable_keyvault_public_access" {
#   provisioner "local-exec" {
#     command = "az keyvault update --name ${azurerm_key_vault.main.name} --public-network-access Disabled"
#   }
#   depends_on = [azurerm_private_endpoint.keyvault]
# }

# =============================================================================
# PHASE 4: UPDATE SERVICES WITH PRIVATE ENDPOINTS
# =============================================================================

# =============================================================================
# PHASE 5: MANAGED IDENTITY AUTHENTICATION
# =============================================================================

# Container Registry (with managed identity authentication)
resource "azurerm_container_registry" "acr" {
  name                = "acr${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.example.name
  location            = azurerm_resource_group.example.location
  sku                 = "Premium"  # Upgraded from Basic for private endpoint support
  admin_enabled       = false      # Disabled - using managed identity instead

  # Disable public network access (Phase 4)
  public_network_access_enabled = false

  network_rule_set {
    default_action = "Deny"
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

  # VNET Integration - use delegated subnet for Container Apps
  infrastructure_subnet_id       = azurerm_subnet.containerapp.id
  internal_load_balancer_enabled = false  # Keep external ingress enabled

  tags = local.common_tags
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

*/



# Details of the Fabric Capacity
/*
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
*/

# # Storage Account Name (commented out - not needed for current simulation workflow)
# output "storage_account" {
#   value       = azurerm_storage_account.example.name
#   description = "The name of the storage account"
# }

# # Storage Account Connection String (commented out - not needed for current simulation workflow)
# output "storage_conn_string" {
#   value       = azurerm_storage_account.example.primary_connection_string
#   description = "The primary connection string for the storage account"
#   sensitive   = true
# }

# # Blob Container Name (commented out - not needed for current simulation workflow)
# output "blob_container_name" {
#   value       = azurerm_storage_container.example.name
#   description = "The name of the blob container"
# }

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
/*
output "log_analytics_workspace_name" {
  value       = azurerm_log_analytics_workspace.example.name
  description = "The name of the Log Analytics workspace"
}

# Log Analytics Workspace ID
output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.example.workspace_id
  description = "The workspace ID of the Log Analytics workspace"
}

# AI Foundry Hub ID
output "ai_foundry_hub_id" {
  value       = azapi_resource.ai_foundry.id
  description = "The ID of the AI Foundry hub"
}

# AI Foundry Hub Name
output "ai_foundry_hub_name" {
  value       = azapi_resource.ai_foundry.name
  description = "The name of the AI Foundry hub"
}

# AI Foundry Hub Endpoint
output "ai_foundry_hub_endpoint" {
  value       = azapi_resource.ai_foundry.output.properties.endpoint
  description = "The endpoint for the AI Foundry hub"
}

# GPT-4o Deployment ID
output "gpt4o_deployment_id" {
  value       = azapi_resource.aifoundry_deployment_gpt4o.id
  description = "The ID of the GPT-4o deployment"
}

# GPT-4o Deployment Name
output "gpt4o_deployment_name" {
  value       = azapi_resource.aifoundry_deployment_gpt4o.name
  description = "The name of the GPT-4o deployment"
}

# AI Foundry Project ID
output "ai_foundry_project_id" {
  value       = azapi_resource.ai_foundry_project.id
  description = "The ID of the AI Foundry project"
}

# AI Foundry Project Name
output "ai_foundry_project_name" {
  value       = azapi_resource.ai_foundry_project.name
  description = "The name of the AI Foundry project"
}

# AI Foundry Project Endpoint (for agent scripts)
output "azure_ai_project_endpoint" {
  value       = "https://${azapi_resource.ai_foundry.body.properties.customSubDomainName}.services.ai.azure.com/api/projects/${azapi_resource.ai_foundry_project.name}"
  description = "The endpoint for the AI Foundry project (used by agent scripts)"
}

# AI Foundry Project ID (for agent scripts)
output "azure_ai_project_id" {
  value       = "${azapi_resource.ai_foundry.id}/projects/${azapi_resource.ai_foundry_project.name}"
  description = "The full resource ID of the AI Foundry project (used by agent scripts)"
}

# AI Model Deployment Name (for agent scripts)
output "azure_ai_model_deployment_name" {
  value       = azapi_resource.aifoundry_deployment_gpt4o.name
  description = "The name of the GPT-4o deployment (used by agent scripts)"
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
*/

# =============================================================================
# BASTION HOST OUTPUTS
# =============================================================================

# Bastion Host Public IP
/*
output "bastion_public_ip" {
  value       = azurerm_public_ip.bastion.ip_address
  description = "The public IP address of the bastion host"
}

# Bastion Host Private IP
output "bastion_private_ip" {
  value       = azurerm_network_interface.bastion.private_ip_address
  description = "The private IP address of the bastion host"
}

# Bastion Host Connection String
output "bastion_ssh_command" {
  value       = "ssh azureuser@${azurerm_public_ip.bastion.ip_address}"
  description = "SSH command to connect to the bastion host"
}
*/

# Generate .env file for local development
resource "local_file" "env_file" {
  filename = "${path.module}/../.env"
  content  = <<-EOT
    # Generated by Terraform - CosmosDB + PostgreSQL configuration
    AZURE_RESOURCE_GROUP=${azurerm_resource_group.example.name}

    COSMOSDB_ACCOUNT_NAME=${azurerm_cosmosdb_account.example.name}
    COSMOSDB_ENDPOINT=${azurerm_cosmosdb_account.example.endpoint}
    COSMOSDB_DATABASE_NAME=${azurerm_cosmosdb_sql_database.example.name}
    COSMOSDB_PRIMARY_KEY=${azurerm_cosmosdb_account.example.primary_key}
    COSMOSDB_CONNECTION_STRING=${azurerm_cosmosdb_account.example.primary_sql_connection_string}

    POSTGRES_SERVER_NAME=${azurerm_postgresql_flexible_server.example.name}
    POSTGRES_FQDN=${azurerm_postgresql_flexible_server.example.fqdn}
    POSTGRES_DB_NAME=${azurerm_postgresql_flexible_server_database.example.name}
    POSTGRES_ADMIN_LOGIN=${azurerm_postgresql_flexible_server.example.administrator_login}
    POSTGRES_ADMIN_PASSWORD=${azurerm_postgresql_flexible_server.example.administrator_password}
  EOT
}

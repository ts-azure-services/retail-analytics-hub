#!/bin/bash
# ============================================================================
# create-fabric-lakehouse.sh
#
# Create a Microsoft Fabric Lakehouse in the specified workspace.
# The Lakehouse provides unified storage for data lake and data warehouse
# workloads, supporting both structured and unstructured data.
#
# Prerequisites:
# - Azure CLI installed and logged in (az login)
# - .env file with FABRIC_WORKSPACE_ID
#
# Usage:
#   ./create-fabric-lakehouse.sh [lakehouse_name]
#
# Environment Variables:
#   FABRIC_WORKSPACE_ID - Target Fabric workspace ID (from .env)
# ============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/infra/.env"

# Default lakehouse name
DEFAULT_LAKEHOUSE_NAME="RetailAnalyticsLakehouse"

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}============================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}  $1${NC}"
}

# ============================================================================
# Update .env File
# ============================================================================

update_env_variable() {
    local var_name="$1"
    local var_value="$2"
    local env_file="$ENV_FILE"
    
    # Remove existing entry if present
    if grep -q "^${var_name}=" "$env_file" 2>/dev/null; then
        # Use sed to update the existing entry
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|^${var_name}=.*|${var_name}=${var_value}|" "$env_file"
        else
            sed -i "s|^${var_name}=.*|${var_name}=${var_value}|" "$env_file"
        fi
        print_success "Updated ${var_name} in .env"
    else
        # Append new entry
        echo "${var_name}=${var_value}" >> "$env_file"
        print_success "Added ${var_name} to .env"
    fi
}

# ============================================================================
# Prerequisites Check
# ============================================================================

check_prerequisites() {
    print_header "Checking Prerequisites"
    
    local missing=0
    
    # Check Azure CLI
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI (az) is not installed"
        missing=1
    else
        print_success "Azure CLI found"
    fi
    
    # Check jq (optional but helpful)
    if ! command -v jq &> /dev/null; then
        print_warning "jq not installed (optional, using python fallback)"
    else
        print_success "jq found"
    fi
    
    # Check if logged into Azure
    if ! az account show &> /dev/null; then
        print_error "Not logged into Azure CLI. Run 'az login' first"
        missing=1
    else
        print_success "Logged into Azure CLI"
    fi
    
    # Load environment variables
    if [[ -f "$ENV_FILE" ]]; then
        source "$ENV_FILE"
        print_success "Loaded environment from .env"
    else
        print_error ".env file not found at $ENV_FILE"
        print_info "Run 'make tf' to generate it"
        missing=1
    fi
    
    # Check workspace ID
    if [[ -z "$FABRIC_WORKSPACE_ID" ]]; then
        print_error "FABRIC_WORKSPACE_ID not set in .env"
        missing=1
    else
        print_success "Workspace ID: $FABRIC_WORKSPACE_ID"
    fi
    
    if [[ $missing -eq 1 ]]; then
        echo ""
        print_error "Prerequisites check failed. Please fix the above issues."
        exit 1
    fi
}

# ============================================================================
# Get Fabric Access Token
# ============================================================================

get_fabric_token() {
    local token
    token=$(az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv 2>/dev/null)
    
    if [[ -z "$token" ]]; then
        print_error "Failed to get Fabric access token"
        exit 1
    fi
    
    echo "$token"
}

# ============================================================================
# Check if Lakehouse Exists
# ============================================================================

check_lakehouse_exists() {
    local token="$1"
    local lakehouse_name="$2"
    
    local response
    response=$(curl -s -X GET \
        "https://api.fabric.microsoft.com/v1/workspaces/${FABRIC_WORKSPACE_ID}/items" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json")
    
    # Try jq first, fall back to python
    local existing_id
    if command -v jq &> /dev/null; then
        existing_id=$(echo "$response" | jq -r ".value[]? | select(.displayName == \"$lakehouse_name\" and .type == \"Lakehouse\") | .id" 2>/dev/null)
    else
        existing_id=$(echo "$response" | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin).get('value', [])
    result = next((item['id'] for item in items if item.get('displayName') == '$lakehouse_name' and item.get('type') == 'Lakehouse'), '')
    print(result)
except:
    print('')
" 2>/dev/null)
    fi
    
    echo "$existing_id"
}

# ============================================================================
# Create Lakehouse
# ============================================================================

create_lakehouse() {
    local token="$1"
    local lakehouse_name="$2"
    
    print_header "Creating Fabric Lakehouse"
    
    echo -e "${BLUE}Lakehouse Name: ${YELLOW}$lakehouse_name${NC}"
    echo -e "${BLUE}Workspace ID:   ${YELLOW}$FABRIC_WORKSPACE_ID${NC}"
    echo ""
    
    # Check if lakehouse already exists
    local existing_id
    existing_id=$(check_lakehouse_exists "$token" "$lakehouse_name")
    
    if [[ -n "$existing_id" ]]; then
        print_warning "Lakehouse '$lakehouse_name' already exists"
        print_info "Lakehouse ID: $existing_id"
        # Save lakehouse ID to .env
        update_env_variable "FABRIC_LAKEHOUSE_ID" "$existing_id"
        echo ""
        echo -e "${GREEN}Lakehouse is ready to use!${NC}"
        return 0
    fi
    
    # Create the lakehouse
    echo "Creating new Lakehouse..."
    
    local payload
    payload=$(cat <<EOF
{
    "displayName": "$lakehouse_name",
    "type": "Lakehouse",
    "description": "Lakehouse for retail analytics with mirrored CosmosDB and PostgreSQL data"
}
EOF
)
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST \
        "https://api.fabric.microsoft.com/v1/workspaces/${FABRIC_WORKSPACE_ID}/items" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "$payload")
    
    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | sed '$d')
    
    if [[ "$http_code" == "201" || "$http_code" == "200" || "$http_code" == "202" ]]; then
        print_success "Lakehouse created successfully!"
        
        # Extract lakehouse ID
        local lakehouse_id
        if command -v jq &> /dev/null; then
            lakehouse_id=$(echo "$body" | jq -r '.id // empty')
        else
            lakehouse_id=$(echo "$body" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)
        fi
        
        if [[ -n "$lakehouse_id" ]]; then
            print_info "Lakehouse ID: $lakehouse_id"
            # Save lakehouse ID to .env
            update_env_variable "FABRIC_LAKEHOUSE_ID" "$lakehouse_id"
        fi
        
        echo ""
        print_success "Lakehouse '$lakehouse_name' is ready!"
        
    elif [[ "$http_code" == "409" ]]; then
        print_warning "Lakehouse already exists (conflict)"
        
    else
        print_error "Failed to create Lakehouse"
        echo "  HTTP Status: $http_code"
        echo "  Response: $body"
        return 1
    fi
}

# ============================================================================
# List Lakehouses in Workspace
# ============================================================================

list_lakehouses() {
    local token="$1"
    
    print_header "Existing Lakehouses in Workspace"
    
    local response
    response=$(curl -s -X GET \
        "https://api.fabric.microsoft.com/v1/workspaces/${FABRIC_WORKSPACE_ID}/items" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json")
    
    # Filter and display lakehouses
    if command -v jq &> /dev/null; then
        local lakehouses
        lakehouses=$(echo "$response" | jq -r '.value[]? | select(.type == "Lakehouse") | "  - \(.displayName) (ID: \(.id))"')
        if [[ -n "$lakehouses" ]]; then
            echo "$lakehouses"
        else
            echo "  No lakehouses found in workspace"
        fi
    else
        echo "$response" | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin).get('value', [])
    lakehouses = [item for item in items if item.get('type') == 'Lakehouse']
    if lakehouses:
        for lh in lakehouses:
            print(f\"  - {lh.get('displayName')} (ID: {lh.get('id')})\")
    else:
        print('  No lakehouses found in workspace')
except Exception as e:
    print(f'  Error listing lakehouses: {e}')
" 2>/dev/null
    fi
}

# ============================================================================
# Main
# ============================================================================

main() {
    # Get lakehouse name from argument or use default
    local lakehouse_name="${1:-$DEFAULT_LAKEHOUSE_NAME}"
    
    print_header "Fabric Lakehouse Creation"
    
    # Check prerequisites
    check_prerequisites
    
    # Get Fabric access token
    print_header "Authenticating with Fabric"
    local token
    token=$(get_fabric_token)
    print_success "Obtained Fabric access token"
    
    # List existing lakehouses
    list_lakehouses "$token"
    
    # Create lakehouse
    create_lakehouse "$token" "$lakehouse_name"
    
    # Print next steps
    echo ""
    print_header "Next Steps"
    echo "  1. Open Microsoft Fabric (https://app.fabric.microsoft.com)"
    echo "  2. Navigate to your workspace"
    echo "  3. Open the Lakehouse: $lakehouse_name"
    echo "  4. Set up database mirroring for CosmosDB and PostgreSQL"
    echo "  5. Upload and run analytics notebooks"
    echo ""
}

# Run main function
main "$@"

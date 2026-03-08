#!/bin/bash
# ============================================================================
# purge-onelake.sh
#
# Purge all data from OneLake by deleting and recreating Lakehouses.
# This will delete all tables, files, and shortcuts in all Lakehouses
# in the workspace.
#
# Prerequisites:
# - Azure CLI installed and logged in (az login)
# - .env file with FABRIC_WORKSPACE_ID
#
# Usage:
#   ./purge-onelake.sh [--force]
#
# Options:
#   --force    Skip confirmation prompt
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

# Parse arguments
FORCE=0
if [[ "$1" == "--force" ]]; then
    FORCE=1
fi

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
# List All Lakehouses
# ============================================================================

list_lakehouses() {
    local token="$1"
    
    local response
    response=$(curl -s -X GET \
        "https://api.fabric.microsoft.com/v1/workspaces/${FABRIC_WORKSPACE_ID}/items" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json")
    
    # Extract lakehouse info (name and ID)
    if command -v jq &> /dev/null; then
        echo "$response" | jq -r '.value[]? | select(.type == "Lakehouse") | "\(.displayName)|\(.id)"'
    else
        echo "$response" | python3 -c "
import sys, json
try:
    items = json.load(sys.stdin).get('value', [])
    lakehouses = [item for item in items if item.get('type') == 'Lakehouse']
    for lh in lakehouses:
        print(f\"{lh.get('displayName')}|{lh.get('id')}\")
except:
    pass
" 2>/dev/null
    fi
}

# ============================================================================
# Delete Lakehouse
# ============================================================================

delete_lakehouse() {
    local token="$1"
    local lakehouse_id="$2"
    local lakehouse_name="$3"
    
    echo "🗑️  Deleting Lakehouse: $lakehouse_name"
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X DELETE \
        "https://api.fabric.microsoft.com/v1/workspaces/${FABRIC_WORKSPACE_ID}/items/${lakehouse_id}" \
        -H "Authorization: Bearer $token")
    
    local http_code
    http_code=$(echo "$response" | tail -n1)
    
    if [[ "$http_code" == "200" || "$http_code" == "204" ]]; then
        print_success "Deleted Lakehouse: $lakehouse_name"
        return 0
    else
        print_error "Failed to delete Lakehouse: $lakehouse_name (HTTP $http_code)"
        return 1
    fi
}

# ============================================================================
# Purge OneLake
# ============================================================================

purge_onelake() {
    local token="$1"
    
    print_header "Purging OneLake"
    
    # Get all lakehouses
    local lakehouses
    lakehouses=$(list_lakehouses "$token")
    
    if [[ -z "$lakehouses" ]]; then
        print_info "No Lakehouses found in workspace"
        echo ""
        print_success "OneLake is already empty"
        return 0
    fi
    
    # Count lakehouses
    local count
    count=$(echo "$lakehouses" | wc -l | tr -d ' ')
    
    echo -e "${YELLOW}Found $count Lakehouse(s):${NC}"
    echo "$lakehouses" | while IFS='|' read -r name id; do
        echo "  - $name (ID: $id)"
    done
    echo ""
    
    # Confirmation prompt (unless --force)
    if [[ $FORCE -eq 0 ]]; then
        print_warning "This will DELETE ALL DATA in OneLake!"
        echo -e "${RED}All tables, files, and shortcuts will be permanently deleted.${NC}"
        echo ""
        read -p "Are you sure you want to continue? (yes/no): " confirm
        
        if [[ "$confirm" != "yes" ]]; then
            echo ""
            print_info "Operation cancelled"
            exit 0
        fi
    fi
    
    echo ""
    print_header "Deleting Lakehouses"
    
    # Delete each lakehouse
    local deleted=0
    local failed=0
    
    while IFS='|' read -r name id; do
        if delete_lakehouse "$token" "$id" "$name"; then
            ((deleted++)) || true
        else
            ((failed++)) || true
        fi
    done <<< "$lakehouses"
    
    echo ""
    print_header "Purge Complete"
    echo "  Lakehouses deleted: $deleted"
    
    if [[ $failed -gt 0 ]]; then
        print_warning "$failed Lakehouse(s) failed to delete"
    fi
    
    echo ""
    print_success "OneLake has been purged"
}

# ============================================================================
# Main
# ============================================================================

main() {
    print_header "OneLake Purge Utility"
    
    # Check prerequisites
    check_prerequisites
    
    # Get Fabric access token
    print_header "Authenticating with Fabric"
    local token
    token=$(get_fabric_token)
    print_success "Obtained Fabric access token"
    
    # Purge OneLake
    purge_onelake "$token"
    
    # Print next steps
    echo ""
    print_header "Next Steps"
    echo "  To recreate Lakehouses and reload data:"
    echo ""
    echo "    make create-lakehouse    - Recreate RetailAnalyticsLakehouse"
    echo "    make setup-mirroring     - Configure database mirroring"
    echo ""
}

# Run main function
main "$@"

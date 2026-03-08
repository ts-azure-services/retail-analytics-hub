#!/bin/bash
# Script to manage Azure Fabric Capacity (suspend/resume/update) using REST API

# Colors for output
grn=$'\e[1;32m'
red=$'\e[1;31m'
yel=$'\e[1;33m'
end=$'\e[0m'

# Check if action argument is provided
if [ $# -eq 0 ]; then
    printf "${red}Error: No action specified.${end}\n"
    printf "${yel}Usage: $0 {suspend|resume|update <SKU>}${end}\n"
    exit 1
fi

ACTION=$1
SKU_NAME=""

# Validate action and parameters
if [ "$ACTION" = "update" ]; then
    if [ $# -lt 2 ]; then
        printf "${red}Error: SKU name required for update action.${end}\n"
        printf "${yel}Usage: $0 update <SKU>${end}\n"
        printf "${yel}Valid SKUs: F2, F4, F8, F16, F32, F64, F128, F256, F512, F1024, F2048${end}\n"
        exit 1
    fi
    SKU_NAME=$2
    # Validate SKU
    VALID_SKUS="F2 F4 F8 F16 F32 F64 F128 F256 F512 F1024 F2048"
    if ! echo "$VALID_SKUS" | grep -qw "$SKU_NAME"; then
        printf "${red}Error: Invalid SKU '$SKU_NAME'.${end}\n"
        printf "${yel}Valid SKUs: F2, F4, F8, F16, F32, F64, F128, F256, F512, F1024, F2048${end}\n"
        exit 1
    fi
elif [ "$ACTION" != "suspend" ] && [ "$ACTION" != "resume" ]; then
    printf "${red}Error: Invalid action '$ACTION'.${end}\n"
    printf "${yel}Usage: $0 {suspend|resume|update <SKU>}${end}\n"
    exit 1
fi

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/infra/.env"

# Check if .env file exists
if [ ! -f "$ENV_FILE" ]; then
    printf "${red}Error: .env file not found at $ENV_FILE. Please run 'make tf' first.${end}\n"
    exit 1
fi

# Source the .env file
printf "${grn}Loading environment variables from $ENV_FILE...${end}\n"
source "$ENV_FILE"

# Check required variables
if [ -z "$AZURE_RESOURCE_GROUP" ]; then
    printf "${red}Error: AZURE_RESOURCE_GROUP not found in .env file.${end}\n"
    exit 1
fi

# Alias for convenience
RESOURCE_GROUP="$AZURE_RESOURCE_GROUP"

# Get current Azure subscription (assumes user is already logged in and subscription is set)
printf "${grn}Retrieving current Azure subscription...${end}\n"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

if [ -z "$SUBSCRIPTION_ID" ]; then
    printf "${red}Error: Not logged into Azure or no subscription set.${end}\n"
    printf "${red}Please run: az login && az account set --subscription <subscription-id>${end}\n"
    exit 1
fi

printf "${yel}Using subscription: $SUBSCRIPTION_ID${end}\n"
printf "${yel}Resource Group: $RESOURCE_GROUP${end}\n"

# Get access token for Azure Resource Manager (needed for all API calls)
printf "${grn}Getting Azure access token...${end}\n"
ACCESS_TOKEN=$(az account get-access-token --resource https://management.azure.com --query accessToken -o tsv)

if [ -z "$ACCESS_TOKEN" ]; then
    printf "${red}Error: Failed to get access token.${end}\n"
    exit 1
fi

# Get Fabric Capacity name from the resource group using REST API
printf "${grn}Finding Fabric Capacity in resource group...${end}\n"
LIST_API_URL="https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Fabric/capacities?api-version=2023-11-01"

CAPACITY_RESPONSE=$(curl -s -X GET "$LIST_API_URL" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json")

# Extract capacity name from JSON response
CAPACITY_NAME=$(echo "$CAPACITY_RESPONSE" | grep -o '"name":"[^"]*"' | head -1 | sed 's/"name":"//;s/"//')

if [ -z "$CAPACITY_NAME" ]; then
    printf "${red}Error: No Fabric Capacity found in resource group $RESOURCE_GROUP${end}\n"
    printf "${red}API Response: $CAPACITY_RESPONSE${end}\n"
    exit 1
fi

printf "${yel}Fabric Capacity Name: $CAPACITY_NAME${end}\n"

# Prepare API call based on action
if [ "$ACTION" = "update" ]; then
    # For update, use PATCH with a request body
    API_URL="https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Fabric/capacities/$CAPACITY_NAME?api-version=2023-11-01"
    REQUEST_BODY=$(cat <<EOF
{
  "sku": {
    "name": "$SKU_NAME",
    "tier": "Fabric"
  }
}
EOF
)
    HTTP_METHOD="PATCH"
    ACTION_VERB="Updating"
    ACTION_PAST="update"
    printf "${grn}Updating Fabric Capacity SKU to $SKU_NAME...${end}\n"
else
    # For suspend/resume, use POST with no body
    API_URL="https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Fabric/capacities/$CAPACITY_NAME/${ACTION}?api-version=2023-11-01"
    REQUEST_BODY=""
    HTTP_METHOD="POST"
    
    if [ "$ACTION" = "suspend" ]; then
        ACTION_VERB="Suspending"
        ACTION_PAST="suspension"
    else
        ACTION_VERB="Resuming"
        ACTION_PAST="resume"
    fi
    printf "${grn}${ACTION_VERB} Fabric Capacity...${end}\n"
fi

printf "${yel}API URL: $API_URL${end}\n"

# Make the REST API call
if [ -z "$REQUEST_BODY" ]; then
    # POST with no body (suspend/resume)
    RESPONSE=$(curl -s -w "\n%{http_code}" -X $HTTP_METHOD "$API_URL" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -H "Content-Length: 0")
else
    # PATCH with JSON body (update)
    RESPONSE=$(curl -s -w "\n%{http_code}" -X $HTTP_METHOD "$API_URL" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$REQUEST_BODY")
fi

# Extract HTTP status code (last line)
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | sed '$d')

# Check response
if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 202 ]; then
    printf "${grn}✓ Fabric Capacity ${ACTION_PAST} initiated successfully!${end}\n"
    printf "${grn}HTTP Status: $HTTP_CODE${end}\n"
    if [ ! -z "$BODY" ]; then
        printf "${yel}Response: $BODY${end}\n"
    fi
else
    printf "${red}✗ Failed to ${ACTION} Fabric Capacity${end}\n"
    printf "${red}HTTP Status: $HTTP_CODE${end}\n"
    printf "${red}Response: $BODY${end}\n"
    exit 1
fi

printf "${grn}Done!${end}\n"
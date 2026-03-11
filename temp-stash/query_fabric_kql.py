"""
Query a Fabric KQL database (Real-Time Intelligence / Eventhouse).

Prerequisites:
  1. pip install azure-kusto-data azure-identity python-dotenv
  2. az login                      (authenticate with Azure Entra ID)
  3. Copy .env.example → .env and fill in FABRIC_KQL_CLUSTER_URI
     (find it in Fabric portal: KQL Database → Query URI → copy)

Authentication uses DefaultAzureCredential which picks up your 'az login' token.

References:
  - https://learn.microsoft.com/kusto/api/get-started/app-basic-query?view=microsoft-fabric
  - https://learn.microsoft.com/fabric/real-time-intelligence/kusto-query-set
  - https://learn.microsoft.com/kusto/api/connection-strings/kusto?view=microsoft-fabric
"""

import argparse
from os import getenv
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration – override via .env or environment variables
# ---------------------------------------------------------------------------
# The Query URI from Fabric portal: KQL Database home page → "Copy URI"
# Example: https://<guid>.z0.kusto.data.microsoft.com
CLUSTER_URI = getenv("FABRIC_KQL_CLUSTER_URI", "https://trd-6fqysuc5umke67vkac.z5.kusto.fabric.microsoft.com")
DATABASE = getenv("FABRIC_KQL_DATABASE", "CustomerReviewsDB")

if not CLUSTER_URI:
    print(
        "ERROR: Set FABRIC_KQL_CLUSTER_URI in .env or environment.\n"
        "Find it in Fabric portal → your KQL Database → Query URI (copy icon)."
    )
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Fabric KQL database")
    parser.add_argument("--flatten", action="store_true", help="Print each row as key: value pairs")
    args = parser.parse_args()

    print(f"Connecting to {CLUSTER_URI} / {DATABASE} ...")

    # Authenticate via Azure Entra ID (uses az login token)
    credential = DefaultAzureCredential()
    kcsb = KustoConnectionStringBuilder.with_azure_token_credential(
        CLUSTER_URI, credential
    )

    with KustoClient(kcsb) as client:
        # KQL query — take 10 rows from the CustomerReviews table
        query = "CustomerReviews | take 10"
        print(f"\nExecuting KQL: {query}\n")

        response = client.execute_query(DATABASE, query)

        columns = [col.column_name for col in response.primary_results[0].columns]
        rows = list(response.primary_results[0])

        if args.flatten:
            for row in rows:
                print(", ".join(f'"{col}":{row[col]}' for col in columns))
        else:
            print(" | ".join(columns))
            print("-" * (len(" | ".join(columns))))
            for row in rows:
                print(" | ".join(str(row[col]) for col in columns))

    print("Done.")


if __name__ == "__main__":
    main()

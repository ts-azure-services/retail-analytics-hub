#!/usr/bin/env python3
"""Clean CosmosDB by deleting all application containers"""

import os
import sys
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

def cleanup_cosmos():
    """
    Delete all application containers from CosmosDB.
    Application containers will be recreated by seed scripts as needed.
    """
    load_dotenv()
    
    endpoint = os.getenv("COSMOSDB_ENDPOINT")
    database_name = os.getenv("COSMOSDB_DATABASE_NAME")
    
    if not all([endpoint, database_name]):
        print("✗ Error: Missing CosmosDB configuration")
        print("  Required: COSMOSDB_ENDPOINT, COSMOSDB_DATABASE_NAME")
        sys.exit(1)
    
    print("🧹 Cleaning CosmosDB containers...")
    print(f"   Database: {database_name}")
    print()
    
    # Connect using Managed Identity
    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    database = client.get_database_client(database_name)
    
    # Get all containers
    containers = list(database.list_containers())
    print(f"📦 Found {len(containers)} container(s)")
    print()
    
    deleted = 0
    
    for container_props in containers:
        container_name = container_props['id']
        
        print(f"🗑️  Deleting container: {container_name}")
        
        try:
            database.delete_container(container_name)
            print(f"   ✓ Deleted container")
            deleted += 1
            
        except Exception as e:
            print(f"   ✗ Error deleting container {container_name}: {str(e)}")
        
        print()
    
    print("="*60)
    print(f"✓ CosmosDB cleanup completed")
    print(f"  Containers deleted: {deleted}")
    print(f"  Final state: Database empty (containers will be recreated on next seed)")
    print("="*60)

if __name__ == "__main__":
    try:
        cleanup_cosmos()
    except Exception as e:
        print(f"✗ Error during cleanup: {str(e)}")
        sys.exit(1)

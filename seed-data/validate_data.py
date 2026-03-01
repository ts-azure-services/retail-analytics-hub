"""
Database validation script for Cosmos DB, PostgreSQL, and local DuckDB.

Validates seeded data and allows interactive querying.
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths for local DuckDB files (mirrors seed_local.py)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_POSTGRES_DB = str(REPO_ROOT / "local_postgres.duckdb")
LOCAL_COSMOS_DB = str(REPO_ROOT / "local_cosmos.duckdb")


# Colors for output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def print_header(text: str):
    """Print formatted header"""
    print(f"\n{Colors.BOLD}{'=' * 60}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{text}{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 60}{Colors.END}\n")


def print_section(text: str):
    """Print section header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}📊 {text}{Colors.END}")
    print(f"{Colors.BLUE}{'─' * 50}{Colors.END}")


def print_success(text: str):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {text}{Colors.END}")


def print_error(text: str):
    """Print error message"""
    print(f"{Colors.RED}✗ {text}{Colors.END}")


def print_info(text: str):
    """Print info message"""
    print(f"{Colors.YELLOW}ℹ {text}{Colors.END}")


class CosmosValidator:
    """Validates Cosmos DB data"""
    
    def __init__(self, endpoint: str, database_name: str):
        self.endpoint = endpoint
        self.database_name = database_name
        self.client = None
        self.database = None
        
    def connect(self) -> bool:
        """Connect to Cosmos DB"""
        try:
            from azure.cosmos import CosmosClient
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            self.client = CosmosClient(self.endpoint, credential=credential)
            self.database = self.client.get_database_client(self.database_name)
            print_success(f"Connected to Cosmos DB: {self.database_name}")
            return True
        except Exception as e:
            print_error(f"Failed to connect to Cosmos DB: {e}")
            return False
    
    def list_containers(self) -> List[str]:
        """List all containers in the database"""
        try:
            containers = list(self.database.list_containers())
            return [c['id'] for c in containers]
        except Exception as e:
            print_error(f"Failed to list containers: {e}")
            return []
    
    def count_documents(self, container_name: str) -> int:
        """Count documents in a container"""
        try:
            container = self.database.get_container_client(container_name)
            # Use aggregation query to count
            query = "SELECT VALUE COUNT(1) FROM c"
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            return items[0] if items else 0
        except Exception as e:
            print_error(f"Failed to count documents in {container_name}: {e}")
            return 0
    
    def get_sample_documents(self, container_name: str, limit: int = 5) -> List[Dict]:
        """Get sample documents from a container"""
        try:
            container = self.database.get_container_client(container_name)
            query = f"SELECT TOP {limit} * FROM c"
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            return items
        except Exception as e:
            print_error(f"Failed to get sample documents from {container_name}: {e}")
            return []
    
    def execute_query(self, container_name: str, query: str) -> List[Dict]:
        """Execute custom query on a container"""
        try:
            container = self.database.get_container_client(container_name)
            items = list(container.query_items(query=query, enable_cross_partition_query=True))
            return items
        except Exception as e:
            print_error(f"Failed to execute query: {e}")
            return []
    
    def validate_all(self):
        """Validate all containers"""
        print_header("Azure Cosmos DB Data Validator")
        
        if not self.connect():
            return
        
        containers = self.list_containers()
        
        if not containers:
            print_info("No containers found in database")
            return
        
        print_info(f"Found {len(containers)} container(s): {', '.join(containers)}")
        
        for container_name in containers:
            print_section(f"Container: {container_name}")
            
            # Count documents
            count = self.count_documents(container_name)
            print(f"   Total Documents: {Colors.GREEN}{count}{Colors.END}")
            
            if count > 0:
                # Get sample documents
                samples = self.get_sample_documents(container_name, limit=3)
                print(f"   Sample Records (first 3):")
                for i, doc in enumerate(samples, 1):
                    # Print first few fields of each document
                    doc_preview = {k: v for k, v in list(doc.items())[:5]}
                    print(f"      {Colors.CYAN}[{i}]{Colors.END} {doc_preview}")
            else:
                print_info("   No documents in this container")


class PostgresValidator:
    """Validates PostgreSQL data using psycopg3"""
    
    def __init__(self, host: str, database: str, user: str, password: str):
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
        self.cursor = None
        
    def connect(self) -> bool:
        """Connect to PostgreSQL"""
        try:
            import psycopg
            # psycopg3 automatically uses TLS 1.2+ with sslmode='require'
            self.conn = psycopg.connect(
                host=self.host,
                dbname=self.database,
                user=self.user,
                password=self.password,
                port=5432,
                sslmode='require',
                connect_timeout=10
            )
            self.cursor = self.conn.cursor()
            print_success(f"Connected to PostgreSQL: {self.database} (TLS enabled)")
            return True
        except Exception as e:
            print_error(f"Failed to connect to PostgreSQL: {e}")
            if hasattr(e, 'sqlstate'):
                print_error(f"SQL State: {e.sqlstate}")
            return False
    
    def list_tables(self) -> List[str]:
        """List all tables in the database"""
        try:
            query = """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                ORDER BY table_name
            """
            self.cursor.execute(query)
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print_error(f"Failed to list tables: {e}")
            return []
    
    def count_rows(self, table_name: str) -> int:
        """Count rows in a table"""
        try:
            self.cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            return self.cursor.fetchone()[0]
        except Exception as e:
            print_error(f"Failed to count rows in {table_name}: {e}")
            return 0
    
    def get_sample_rows(self, table_name: str, limit: int = 5) -> List[Dict]:
        """Get sample rows from a table"""
        try:
            self.cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except Exception as e:
            print_error(f"Failed to get sample rows from {table_name}: {e}")
            return []
    
    def execute_query(self, query: str) -> List[Dict]:
        """Execute custom SQL query"""
        try:
            self.cursor.execute(query)
            if self.cursor.description:  # If query returns results
                columns = [desc[0] for desc in self.cursor.description]
                return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
            return []
        except Exception as e:
            print_error(f"Failed to execute query: {e}")
            return []
    
    def validate_all(self):
        """Validate all tables"""
        print_header("Azure PostgreSQL Data Validator")
        
        if not self.connect():
            return
        
        tables = self.list_tables()
        
        if not tables:
            print_info("No tables found in database")
            return
        
        print_info(f"Found {len(tables)} table(s): {', '.join(tables)}")
        
        for table_name in tables:
            print_section(f"Table: {table_name}")
            
            # Count rows
            count = self.count_rows(table_name)
            print(f"   Total Rows: {Colors.GREEN}{count}{Colors.END}")
            
            if count > 0:
                # Get sample rows
                samples = self.get_sample_rows(table_name, limit=3)
                print(f"   Sample Records (first 3):")
                for i, row in enumerate(samples, 1):
                    # Print first few fields of each row
                    row_preview = {k: v for k, v in list(row.items())[:5]}
                    print(f"      {Colors.CYAN}[{i}]{Colors.END} {row_preview}")
            else:
                print_info("   No rows in this table")
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()


class DuckDBValidator:
    """Validates local DuckDB data"""

    def __init__(self, db_path: str, label: str):
        self.db_path = db_path
        self.label = label
        self.conn = None

    def connect(self) -> bool:
        """Connect to DuckDB file (read-only)"""
        if not os.path.exists(self.db_path):
            print_error(f"DuckDB file not found: {self.db_path}")
            print_info("Run seed_local.py first to create local databases")
            return False
        try:
            import duckdb
            self.conn = duckdb.connect(self.db_path, read_only=True)
            print_success(f"Connected to DuckDB: {self.label} ({self.db_path})")
            return True
        except Exception as e:
            print_error(f"Failed to connect to DuckDB {self.label}: {e}")
            return False

    def list_tables(self) -> List[str]:
        """List all tables in the database"""
        try:
            rows = self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception as e:
            print_error(f"Failed to list tables: {e}")
            return []

    def get_table_schema(self, table_name: str) -> List[Dict]:
        """Get column names and data types for a table"""
        try:
            rows = self.conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? "
                "ORDER BY ordinal_position",
                [table_name],
            ).fetchall()
            return [
                {"column": r[0], "type": r[1], "nullable": r[2]}
                for r in rows
            ]
        except Exception as e:
            print_error(f"Failed to get schema for {table_name}: {e}")
            return []

    def count_rows(self, table_name: str) -> int:
        """Count rows in a table"""
        try:
            result = self.conn.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()
            return result[0] if result else 0
        except Exception as e:
            print_error(f"Failed to count rows in {table_name}: {e}")
            return 0

    def validate_all(self):
        """Validate all tables with schema and row counts"""
        print_header(f"Local DuckDB Validator — {self.label}")

        if not self.connect():
            return False

        tables = self.list_tables()

        if not tables:
            print_info("No tables found in database")
            return True

        print_info(f"Found {len(tables)} table(s)")

        for table_name in tables:
            print_section(f"Table: {table_name}")

            # Row count
            count = self.count_rows(table_name)
            print(f"   Rows: {Colors.GREEN}{count}{Colors.END}")

            # Schema
            schema = self.get_table_schema(table_name)
            if schema:
                # Calculate column widths for alignment
                max_col = max(len(c["column"]) for c in schema)
                max_type = max(len(c["type"]) for c in schema)
                print(f"   Schema ({len(schema)} columns):")
                print(f"      {Colors.BOLD}{'Column':<{max_col}}  {'Type':<{max_type}}  Nullable{Colors.END}")
                print(f"      {'─' * max_col}  {'─' * max_type}  {'─' * 8}")
                for col in schema:
                    nullable = "YES" if col["nullable"] == "YES" else "NO"
                    print(f"      {col['column']:<{max_col}}  "
                          f"{Colors.CYAN}{col['type']:<{max_type}}{Colors.END}  "
                          f"{nullable}")

        self.close()
        return True

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Validate seeded data in Cosmos DB and PostgreSQL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate all databases
  python validate_data.py --all
  
  # Validate only Cosmos DB
  python validate_data.py --cosmos
  
  # Validate only PostgreSQL
  python validate_data.py --postgres

  # Validate local DuckDB databases
  python validate_data.py --local

  # Execute custom query on Cosmos DB
  python validate_data.py --cosmos --query "SELECT * FROM c WHERE c.isActive = true"

  # Execute custom query on PostgreSQL
  python validate_data.py --postgres --query "SELECT category, COUNT(*) FROM products GROUP BY category"
        """
    )
    
    parser.add_argument('--all', action='store_true', help='Validate all databases (default)')
    parser.add_argument('--cosmos', action='store_true', help='Validate Cosmos DB only')
    parser.add_argument('--postgres', action='store_true', help='Validate PostgreSQL only')
    parser.add_argument('--local', action='store_true', help='Validate local DuckDB databases only')
    parser.add_argument('--query', type=str, help='Execute custom query')
    parser.add_argument('--container', type=str, help='Cosmos DB container name (for custom query)')
    
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv()
    
    # Determine what to validate
    any_specified = args.cosmos or args.postgres or args.local
    validate_cosmos = args.cosmos or args.all or not any_specified
    validate_postgres = args.postgres or args.all or not any_specified
    validate_local = args.local or args.all or not any_specified
    
    # Track success status
    success = True
    
    # Validate Cosmos DB
    if validate_cosmos:
        cosmos_endpoint = os.getenv("COSMOSDB_ENDPOINT")
        cosmos_database = os.getenv("COSMOSDB_DATABASE_NAME")
        
        if not cosmos_endpoint or not cosmos_database:
            print_error("Cosmos DB configuration missing in .env file")
            print_info("Required: COSMOSDB_ENDPOINT, COSMOSDB_DATABASE_NAME")
            success = False
        else:
            validator = CosmosValidator(cosmos_endpoint, cosmos_database)
            
            if args.query:
                container_name = args.container or os.getenv("COSMOSDB_CONTAINER_NAME", "customers")
                print_header(f"Cosmos DB Query Results: {container_name}")
                if validator.connect():
                    results = validator.execute_query(container_name, args.query)
                    print(f"Found {len(results)} result(s):")
                    for i, result in enumerate(results[:10], 1):  # Limit to first 10
                        print(f"{Colors.CYAN}[{i}]{Colors.END} {result}")
                else:
                    success = False
            else:
                if not validator.connect():
                    success = False
                else:
                    validator.validate_all()
    
    # Validate PostgreSQL
    pg_validator = None
    if validate_postgres:
        pg_host = os.getenv("POSTGRESQL_SERVER_FQDN")
        pg_database = os.getenv("POSTGRESQL_DATABASE_NAME")
        pg_user = os.getenv("POSTGRESQL_ADMIN_LOGIN")
        pg_password = os.getenv("POSTGRESQL_ADMIN_PASSWORD")
        
        if not all([pg_host, pg_database, pg_user, pg_password]):
            print_error("PostgreSQL configuration missing in .env file")
            print_info("Required: POSTGRESQL_SERVER_FQDN, POSTGRESQL_DATABASE_NAME, POSTGRESQL_ADMIN_LOGIN, POSTGRESQL_ADMIN_PASSWORD")
            success = False
        else:
            pg_validator = PostgresValidator(pg_host, pg_database, pg_user, pg_password)
            
            try:
                if args.query:
                    print_header("PostgreSQL Query Results")
                    if pg_validator.connect():
                        results = pg_validator.execute_query(args.query)
                        print(f"Found {len(results)} result(s):")
                        for i, result in enumerate(results[:10], 1):  # Limit to first 10
                            print(f"{Colors.CYAN}[{i}]{Colors.END} {result}")
                    else:
                        success = False
                else:
                    if not pg_validator.connect():
                        success = False
                    else:
                        pg_validator.validate_all()
            finally:
                if pg_validator:
                    pg_validator.close()
    
    # Validate local DuckDB databases
    if validate_local:
        for db_path, label in [
            (LOCAL_POSTGRES_DB, "Local PostgreSQL (DuckDB)"),
            (LOCAL_COSMOS_DB, "Local CosmosDB (DuckDB)"),
        ]:
            dv = DuckDBValidator(db_path, label)
            if not dv.validate_all():
                success = False

    # Print final status
    if success:
        print(f"\n{Colors.GREEN}{'=' * 60}{Colors.END}")
        print(f"{Colors.GREEN}{Colors.BOLD}✓ Validation Complete - All checks passed!{Colors.END}")
        print(f"{Colors.GREEN}{'=' * 60}{Colors.END}\n")
    else:
        print(f"\n{Colors.RED}{'=' * 60}{Colors.END}")
        print(f"{Colors.RED}{Colors.BOLD}✗ Validation Failed - Check errors above{Colors.END}")
        print(f"{Colors.RED}{'=' * 60}{Colors.END}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

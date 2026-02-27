#!/usr/bin/env python3
"""Drop all tables from PostgreSQL database"""

import os
import sys
import psycopg
from dotenv import load_dotenv

def cleanup_postgres():
    """Drop all tables from PostgreSQL database"""
    load_dotenv()
    
    pg_host = os.getenv("POSTGRESQL_SERVER_FQDN")
    pg_database = os.getenv("POSTGRESQL_DATABASE_NAME")
    pg_user = os.getenv("POSTGRESQL_ADMIN_LOGIN")
    pg_password = os.getenv("POSTGRESQL_ADMIN_PASSWORD")
    
    if not all([pg_host, pg_database, pg_user, pg_password]):
        print("✗ Error: Missing PostgreSQL configuration")
        sys.exit(1)
    
    print("🧹 Cleaning PostgreSQL...")
    print(f"   Database: {pg_database}")
    print()
    
    try:
        # Connect to PostgreSQL
        conn = psycopg.connect(
            host=pg_host,
            dbname=pg_database,
            user=pg_user,
            password=pg_password,
            port=5432,
            sslmode='require',
            connect_timeout=10
        )
        
        cursor = conn.cursor()
        
        # Get all tables in public schema
        cursor.execute("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        
        tables = cursor.fetchall()
        
        if not tables:
            print("ℹ  No tables found - database is already clean")
            cursor.close()
            conn.close()
            return
        
        print(f"📋 Found {len(tables)} table(s) to drop:")
        for table in tables:
            print(f"   - {table[0]}")
        
        print()
        
        # Drop all tables (CASCADE to handle foreign keys)
        dropped = 0
        for table in tables:
            table_name = table[0]
            try:
                print(f"🗑️  Dropping table: {table_name}")
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
                conn.commit()
                dropped += 1
            except Exception as e:
                print(f"   ⚠️  Failed to drop {table_name}: {str(e)}")
                conn.rollback()
        
        cursor.close()
        conn.close()
        
        print()
        print("="*60)
        print(f"✓ PostgreSQL cleanup completed")
        print(f"  Tables dropped: {dropped}/{len(tables)}")
        print("="*60)
        
    except Exception as e:
        print(f"✗ Error connecting to PostgreSQL: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        cleanup_postgres()
    except Exception as e:
        print(f"✗ Error during cleanup: {str(e)}")
        sys.exit(1)

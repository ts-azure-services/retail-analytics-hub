""" Seed CosmosDB with sample customer data using Faker """
import os
import sys
import argparse
import time
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
from azure.cosmos import CosmosClient, PartitionKey, exceptions
from azure.identity import DefaultAzureCredential
from faker import Faker
from dotenv import load_dotenv
import psycopg


class CosmosSeeder:
    """Handles seeding data into Azure CosmosDB"""
    
    def __init__(self, endpoint: str, database_name: str):
        """Initialize CosmosDB client with Azure AD authentication"""
        credential = DefaultAzureCredential()
        self.client = CosmosClient(endpoint, credential=credential)
        self.database_name = database_name
        self.database = None
        self.containers = {}
        
    def setup_database(self):
        """Ensure database exists"""
        print(f"📦 Connecting to CosmosDB database: {self.database_name}")
        try:
            self.database = self.client.get_database_client(self.database_name)
            print(f"✓ Connected to database: {self.database_name}")
        except exceptions.CosmosResourceNotFoundError:
            print(f"✗ Database not found")
            raise
    
    def setup_container(self, container_name: str, partition_key: str = "/id"):
        """Ensure container exists and cache reference"""
        print(f"📦 Setting up container: {container_name}")
        try:
            container = self.database.get_container_client(container_name)
            # Verify container exists by reading properties
            container.read()
            self.containers[container_name] = container
            print(f"✓ Container ready: {container_name}")
        except exceptions.CosmosResourceNotFoundError:
            print(f"  ⚠ Container {container_name} not found, creating...")
            try:
                container = self.database.create_container(
                    id=container_name,
                    partition_key=PartitionKey(path=partition_key)
                )
                self.containers[container_name] = container
                print(f"✓ Created container: {container_name}")
            except exceptions.CosmosHttpResponseError as e:
                print(f"✗ Error creating container: {e.message}")
                raise
        except exceptions.CosmosResourceNotFoundError:
            print(f"✗ Database or container not found")
            raise
    
    def generate_customer_data(self, count: int = 100) -> List[Dict]:
        """Generate fake customer data using Faker"""
        fake = Faker()
        customers = []
        
        print(f"🎲 Generating {count} customer records...")
        
        for i in range(count):
            customer = {
                "id": fake.uuid4(),
                "customerId": fake.uuid4(),
                "firstName": fake.first_name(),
                "lastName": fake.last_name(),
                "email": fake.email(),
                "phone": fake.phone_number(),
                "address": {
                    "street": fake.street_address(),
                    "city": fake.city(),
                    "state": fake.state_abbr(),
                    "zipCode": fake.zipcode(),
                    "country": "USA"
                },
                "dateOfBirth": fake.date_of_birth(minimum_age=18, maximum_age=80).isoformat(),
                "accountCreated": fake.date_time_this_decade().isoformat(),
                "accountBalance": round(fake.random.uniform(100, 50000), 2),
                "creditScore": fake.random_int(min=300, max=850),
                "isActive": fake.boolean(chance_of_getting_true=85),
                "preferredContactMethod": fake.random_element(elements=["email", "phone", "sms"]),
                "tags": fake.random_elements(
                    elements=["premium", "standard", "vip", "new", "loyal"],
                    length=fake.random_int(min=1, max=3),
                    unique=True
                )
            }
            customers.append(customer)
        
        print(f"✓ Generated {len(customers)} customer records")
        return customers
    
    def generate_sample_carts(self, customer_ids: List[str], products: List[Dict], count: int = 20) -> List[Dict]:
        """Generate sample shopping cart data using real customer IDs and real product data"""
        fake = Faker()
        carts = []
        
        if not customer_ids:
            print("⚠ No customer IDs provided, skipping cart generation")
            return []
        
        if not products:
            print("⚠ No products provided, skipping cart generation")
            return []
        
        # Ensure we don't try to create more carts than customers
        actual_count = min(count, len(customer_ids))
        if actual_count < count:
            print(f"⚠ Requested {count} carts but only {len(customer_ids)} customers available")
        
        print(f"🎲 Generating {actual_count} sample cart records...")
        print(f"   Using {len(customer_ids)} real customer IDs")
        print(f"   Using {len(products)} real products from PostgreSQL")
        
        # Randomly sample unique customer IDs (no duplicates)
        import random
        selected_customer_ids = random.sample(customer_ids, actual_count)
        
        for customer_id in selected_customer_ids:
            num_items = fake.random_int(min=1, max=8)
            items = []
            for _ in range(num_items):
                product = fake.random_element(products)  # Real product from PostgreSQL
                items.append({
                    "sku": product['sku'],  # Real SKU
                    "productName": product['name'],  # Real product name (chocolate!)
                    "quantity": fake.random_int(min=1, max=5),
                    "price": product['price']  # Real price from products table
                })
            
            cart = {
                "id": fake.uuid4(),
                "cartId": fake.uuid4(),
                "userId": customer_id,  # Unique customer ID (no duplicates)
                "channel": fake.random_element(elements=["online", "mobile_app", "in_store"]),
                "items": items,
                "lastUpdateTime": fake.date_time_this_month().isoformat(),
                "status": fake.random_element(elements=["active", "abandoned", "checked_out"])
            }
            carts.append(cart)
        
        print(f"✓ Generated {len(carts)} cart records with real product data")
        return carts
    
    def generate_sample_workflow_events(self, count: int = 50) -> List[Dict]:
        """Generate sample workflow event data"""
        fake = Faker()
        events = []
        
        print(f"🎲 Generating {count} sample workflow event records...")
        
        event_types = {
            "cart": ["item_added", "item_removed", "quantity_changed", "cart_abandoned", "checkout_started"],
            "order": ["order_placed", "payment_confirmed", "picking_started", "packed", "shipped", "delivered", "picked_up"],
            "fulfillment": ["assigned_to_warehouse", "out_for_delivery", "delivery_attempted", "delivery_failed", "returned"]
        }
        
        for _ in range(count):
            workflow_type = fake.random_element(elements=list(event_types.keys()))
            order_id = fake.uuid4()
            
            event = {
                "id": fake.uuid4(),
                "orderId": order_id,
                "workflowType": workflow_type,
                "eventType": fake.random_element(elements=event_types[workflow_type]),
                "timestamp": fake.date_time_this_month().isoformat(),
                "details": {
                    "location": fake.city() if workflow_type != "cart" else None,
                    "sku": fake.bothify(text='SKU-####-????').upper() if workflow_type == "cart" else None,
                    "quantity": fake.random_int(min=1, max=5) if workflow_type == "cart" else None,
                    "carrier": fake.company() if workflow_type == "fulfillment" else None
                },
                "metadata": {
                    "source": "seed_data",
                    "version": "1.0"
                }
            }
            events.append(event)
        
        print(f"✓ Generated {len(events)} workflow event records")
        return events
    
    def generate_inventory_events_history(self, products: List[Dict], 
                                          days_of_history: int = 90) -> List[Dict]:
        """
        Generate historical inventory events for demand forecasting.
        
        Creates realistic SALE events over the specified history period
        to support Prophet forecasting (requires 14+ data points, optimal 90+).
        
        Args:
            products: List of product dicts with 'sku', 'name', 'price' keys
            days_of_history: Number of days of history to generate (default 90)
        
        Returns:
            List of inventory event documents for CosmosDB
        """
        fake = Faker()
        events = []
        
        locations = ["WAREHOUSE-001", "STORE-NYC", "STORE-LA", "STORE-CHI", "STORE-MIA"]
        
        # Extract just SKUs for popularity mapping
        product_skus = [p['sku'] for p in products]
        
        # Define demand patterns by SKU category (simulate seasonality)
        # Higher numbers = more popular product
        sku_popularity = {sku: fake.random.uniform(0.3, 1.0) for sku in product_skus}
        
        print(f"🎲 Generating {days_of_history} days of inventory events for {len(product_skus)} SKUs...")
        
        from datetime import datetime, timedelta
        import random
        import math
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_of_history)
        
        for day_offset in range(days_of_history):
            current_date = start_date + timedelta(days=day_offset)
            
            # Day-of-week effect (weekends have higher retail sales)
            day_of_week = current_date.weekday()
            if day_of_week >= 5:  # Saturday/Sunday
                day_multiplier = 1.5
            elif day_of_week == 4:  # Friday
                day_multiplier = 1.2
            else:
                day_multiplier = 1.0
            
            # Simple weekly seasonality pattern
            week_factor = 1.0 + 0.1 * math.sin(2 * math.pi * day_offset / 7)
            
            for sku in product_skus:
                popularity = sku_popularity[sku]
                
                # Generate sales for each location
                for location in locations:
                    # Warehouses have fewer direct sales than stores
                    if "WAREHOUSE" in location:
                        base_sales = random.randint(0, 3)
                    else:
                        # Stores: 2-15 sales per day per SKU, modified by popularity
                        base_sales = int(random.randint(2, 15) * popularity * day_multiplier * week_factor)
                    
                    if base_sales == 0:
                        continue
                    
                    # Generate individual sale events throughout the day
                    num_events = min(base_sales, random.randint(1, 5))  # Batch into reasonable events
                    remaining_qty = base_sales
                    
                    for _ in range(num_events):
                        if remaining_qty <= 0:
                            break
                        
                        # Random time during business hours (8am - 9pm)
                        hour = random.randint(8, 21)
                        minute = random.randint(0, 59)
                        event_time = current_date.replace(hour=hour, minute=minute, second=random.randint(0, 59))
                        
                        # Quantity for this event
                        qty_this_event = min(remaining_qty, random.randint(1, 3))
                        remaining_qty -= qty_this_event
                        
                        # Simulate running inventory (start high, decrease)
                        base_inventory = 500 if "WAREHOUSE" in location else 100
                        simulated_on_hand = max(0, base_inventory - (day_offset * 3) - random.randint(0, 20))
                        
                        event = {
                            "id": fake.uuid4(),
                            "eventType": "SALE",
                            "sku": sku,
                            "location": location,
                            "quantityChange": -qty_this_event,
                            "newOnHandQuantity": max(0, simulated_on_hand - qty_this_event),
                            "referenceId": f"ORDER-{fake.uuid4()[:8]}",
                            "eventTime": event_time.isoformat(),
                            "partitionKey": sku
                        }
                        events.append(event)
        
        # Also add some RECEIPT events (replenishment) to make data realistic
        print(f"  Adding replenishment events...")
        for sku in product_skus:
            for location in locations:
                # Add 2-4 receipts per SKU-location over the period
                num_receipts = random.randint(2, 4)
                for _ in range(num_receipts):
                    day_offset = random.randint(5, days_of_history - 5)
                    receipt_date = start_date + timedelta(days=day_offset)
                    receipt_time = receipt_date.replace(
                        hour=random.randint(6, 10), 
                        minute=random.randint(0, 59)
                    )
                    
                    receipt_qty = random.randint(50, 200) if "WAREHOUSE" in location else random.randint(20, 80)
                    
                    event = {
                        "id": fake.uuid4(),
                        "eventType": "RECEIPT",
                        "sku": sku,
                        "location": location,
                        "quantityChange": receipt_qty,
                        "newOnHandQuantity": random.randint(100, 400),
                        "referenceId": f"PO-{fake.uuid4()[:8]}",
                        "eventTime": receipt_time.isoformat(),
                        "partitionKey": sku
                    }
                    events.append(event)
        
        print(f"✓ Generated {len(events)} inventory events ({days_of_history} days of history)")
        return events
    
    def seed_data(self, container_name: str, data: List[Dict], batch_size: int = 100, max_workers: int = 30) -> int:
        """
        Insert data into specified CosmosDB container using parallel bulk operations.
        
        Args:
            container_name: Name of the container to insert into
            data: List of items to insert
            batch_size: Items per progress update (default: 100)
            max_workers: Number of parallel workers (default: 30)
            
        Returns:
            Number of successfully inserted items
        """
        print(f"💾 Seeding {len(data)} records into {container_name}...")
        
        if container_name not in self.containers:
            print(f"✗ Container {container_name} not set up")
            return 0
        
        container = self.containers[container_name]
        total = len(data)
        completed = 0
        errors = []
        
        def upsert_item(item):
            """Upsert single item with retry logic"""
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    container.upsert_item(item)
                    return True, None
                except exceptions.CosmosHttpResponseError as e:
                    if attempt == max_retries - 1:
                        return False, str(e)
                    time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                except Exception as e:
                    return False, str(e)
            return False, "Max retries exceeded"
        
        print(f"   Using {max_workers} parallel workers for bulk operations...")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all items
            future_to_item = {executor.submit(upsert_item, item): i for i, item in enumerate(data)}
            
            # Process results as they complete
            for future in as_completed(future_to_item):
                success, error = future.result()
                completed += 1
                
                if not success:
                    errors.append(error)
                
                # Progress update every batch_size items or every 1%
                if completed % batch_size == 0 or completed % max(1, total // 100) == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total - completed) / rate if rate > 0 else 0
                    print(f"  ➜ Progress: {completed}/{total} ({completed*100//total}%) "
                          f"| Rate: {rate:.0f} items/s | ETA: {eta:.0f}s")
        
        elapsed = time.time() - start_time
        success_count = completed - len(errors)
        
        print(f"\n✓ Bulk insert completed in {elapsed:.2f}s")
        print(f"  Success: {success_count}/{total} ({success_count*100//total}%)")
        print(f"  Average rate: {total/elapsed:.0f} items/second")
        
        if errors:
            print(f"  ⚠️  Errors: {len(errors)}")
            print(f"  First error: {errors[0][:200]}")
        
        return success_count


def fetch_product_skus_from_postgres() -> List[Dict]:
    """Fetch product info (SKU, name, price) from PostgreSQL to ensure consistency."""
    load_dotenv()
    
    pg_host = os.getenv("POSTGRESQL_SERVER_FQDN")
    pg_database = os.getenv("POSTGRESQL_DATABASE_NAME")
    pg_user = os.getenv("POSTGRESQL_ADMIN_LOGIN")
    pg_password = os.getenv("POSTGRESQL_ADMIN_PASSWORD")
    
    if not all([pg_host, pg_database, pg_user, pg_password]):
        print("⚠ PostgreSQL configuration not found, generating random product data")
        fake = Faker()
        return [
            {
                'sku': fake.bothify(text='SKU-####-????').upper(),
                'name': fake.catch_phrase(),
                'price': round(fake.random.uniform(9.99, 299.99), 2)
            }
            for _ in range(50)
        ]
    
    try:
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
        cursor.execute("SELECT sku, name, price FROM products")
        products = [
            {
                'sku': row[0],
                'name': row[1],
                'price': float(row[2])
            }
            for row in cursor.fetchall()
        ]
        cursor.close()
        conn.close()
        
        if products:
            print(f"✓ Fetched {len(products)} products (SKU, name, price) from PostgreSQL")
            return products
        else:
            print("⚠ No products found in PostgreSQL, generating random product data")
            fake = Faker()
            return [
                {
                    'sku': fake.bothify(text='SKU-####-????').upper(),
                    'name': fake.catch_phrase(),
                    'price': round(fake.random.uniform(9.99, 299.99), 2)
                }
                for _ in range(50)
            ]
            
    except Exception as e:
        print(f"⚠ Could not fetch from PostgreSQL: {e}")
        fake = Faker()
        return [
            {
                'sku': fake.bothify(text='SKU-####-????').upper(),
                'name': fake.catch_phrase(),
                'price': round(fake.random.uniform(9.99, 299.99), 2)
            }
            for _ in range(50)
        ]


def main():
    """Main execution function"""
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Seed CosmosDB with sample data')
    parser.add_argument('--historical', action='store_true',
                       help='Generate historical inventory events (90 days) for analytics')
    parser.add_argument('--days', type=int, default=90,
                       help='Number of days of historical data to generate (default: 90)')
    parser.add_argument('--skip-base', action='store_true',
                       help='Skip base data seeding (customers, carts, workflow events)')
    parser.add_argument('--customers-only', action='store_true',
                       help='Phase 1: Seed only customers (required before PostgreSQL seeding)')
    parser.add_argument('--skip-customers', action='store_true',
                       help='Phase 2: Skip customers, seed carts/events (requires PostgreSQL products)')
    args = parser.parse_args()
    
    # Get CosmosDB configuration
    cosmos_endpoint = os.getenv("COSMOSDB_ENDPOINT")
    cosmos_database = os.getenv("COSMOSDB_DATABASE_NAME")
    
    # Application-level container name (created dynamically, not Terraform-managed)
    customer_container = "Customers"
    
    if not all([cosmos_endpoint, cosmos_database]):
        print("✗ Error: Missing CosmosDB configuration in .env file")
        print("  Required: COSMOSDB_ENDPOINT, COSMOSDB_DATABASE_NAME")
        sys.exit(1)
    
    print("=" * 60)
    print("🌱 CosmosDB Data Seeding Script")
    if args.customers_only:
        print("   Mode: Phase 1 - Customers Only")
    elif args.skip_customers:
        print("   Mode: Phase 2 - Carts/Events (requires PostgreSQL products)")
    elif args.historical:
        print(f"   Mode: Historical data generation ({args.days} days)")
    print("=" * 60)
    
    try:
        # Initialize seeder
        seeder = CosmosSeeder(cosmos_endpoint, cosmos_database)
        seeder.setup_database()
        
        # Setup all containers needed for simulation workflows
        seeder.setup_container(customer_container, partition_key="/customerId")
        seeder.setup_container("Carts", partition_key="/cartId")
        seeder.setup_container("WorkflowEvents", partition_key="/orderId")
        seeder.setup_container("FulfillmentState", partition_key="/order_id")
        seeder.setup_container("InventoryEvents", partition_key="/sku")  # For Workflow 2
        seeder.setup_container("EngagementEvents", partition_key="/customer_id")  # For Workflow 4
        
        customer_count = 0
        cart_count = 0
        event_count = 0
        inventory_event_count = 0
        
        # PHASE 1: Customers only (required before PostgreSQL seeding)
        if args.customers_only:
            print("\n📦 Phase 1: Seeding customers only...")
            customers = seeder.generate_customer_data(count=500)
            customer_count = seeder.seed_data(customer_container, customers)
            print(f"✓ Phase 1 complete: {customer_count} customers seeded")
            print("💡 Next: Run PostgreSQL seeding to import customers and create products")
        
        # PHASE 2: Carts and events (requires PostgreSQL products to exist)
        elif args.skip_customers:
            print("\n📦 Phase 2: Seeding carts and events (requires PostgreSQL products)...")
            
            # Fetch customer IDs from existing Customers container
            print("   Fetching customer IDs from Customers container...")
            container = seeder.containers.get(customer_container)
            if not container:
                print("✗ Error: Customers container not found. Run with --customers-only first.")
                sys.exit(1)
            
            customers = list(container.read_all_items())
            customer_ids = [c['id'] for c in customers]
            print(f"   Found {len(customer_ids)} customers")
            
            # Extract real product data from PostgreSQL
            products = fetch_product_skus_from_postgres()
            
            # Generate and seed sample carts with real customer IDs and real product data
            carts = seeder.generate_sample_carts(customer_ids, products, count=80)
            cart_count = seeder.seed_data("Carts", carts)
            
            # Generate and seed sample workflow events
            events = seeder.generate_sample_workflow_events(count=50)
            event_count = seeder.seed_data("WorkflowEvents", events)
            
            print(f"✓ Phase 2 complete: {cart_count} carts, {event_count} events seeded")
        
        # LEGACY MODE: All base data at once (not recommended due to race conditions)
        elif not args.skip_base:
            print("\n⚠️  Running legacy mode (all at once). Consider using phased approach.")
            # Generate and seed customer data
            customers = seeder.generate_customer_data(count=500)
            customer_count = seeder.seed_data(customer_container, customers)
            
            # Extract real product data from PostgreSQL for cart items
            products = fetch_product_skus_from_postgres()

            # Generate and seed sample carts with real customer IDs and real product data
            carts = seeder.generate_sample_carts(customer_ids, products, count=100)
            cart_count = seeder.seed_data("Carts", carts)
            
            # Generate and seed sample workflow events
            events = seeder.generate_sample_workflow_events(count=50)
            event_count = seeder.seed_data("WorkflowEvents", events)
        
        # Generate historical inventory events if requested
        if args.historical:
            print("\n📊 Generating historical inventory events for analytics...")
            products = fetch_product_skus_from_postgres()
            
            inventory_events = seeder.generate_inventory_events_history(
                products=products,
                days_of_history=args.days
            )
            inventory_event_count = seeder.seed_data("InventoryEvents", inventory_events)
        
        print("=" * 60)
        print(f"✓ CosmosDB seeding completed:")
        if args.customers_only:
            print(f"  - {customer_count} customer records (Phase 1)")
        elif args.skip_customers:
            print(f"  - {cart_count} cart records")
            print(f"  - {event_count} workflow event records")
            if args.historical:
                print(f"  - {inventory_event_count} inventory event records ({args.days} days history)")
            print("  (Phase 2 - using PostgreSQL products)")
        else:
            if not args.skip_base:
                print(f"  - {customer_count} customer records")
                print(f"  - {cart_count} cart records")
                print(f"  - {event_count} workflow event records")
            if args.historical:
                print(f"  - {inventory_event_count} inventory event records ({args.days} days history)")
        print("=" * 60)
        
    except Exception as e:
        print(f"✗ Error during seeding: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

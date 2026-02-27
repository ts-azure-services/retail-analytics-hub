""" Seed PostgreSQL with sample product and order data using Faker """
import os
import sys
import ssl
from typing import List, Tuple, Dict
import psycopg
from psycopg import sql
from faker import Faker
from dotenv import load_dotenv
from azure.cosmos import CosmosClient


class PostgresSeeder:
    """Handles seeding data into Azure PostgreSQL Flexible Server"""
    
    def __init__(self, host: str, database: str, user: str, password: str):
        """Initialize PostgreSQL connection"""
        self.host = host
        self.database = database
        self.user = user
        self.password = password
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Establish connection to PostgreSQL"""
        print(f"🔌 Connecting to PostgreSQL: {self.host}")
        print(f"   User: {self.user}")
        print(f"   Database: {self.database}")
        try:
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
            print(f"✓ Connected to database: {self.database} (TLS enabled)")
        except psycopg.Error as e:
            print(f"✗ Connection failed: {e}")
            if hasattr(e, 'sqlstate'):
                print(f"SQL State: {e.sqlstate}")
            print(f"Error details: {str(e)}")
            raise
        except Exception as e:
            print(f"✗ Error during connection: {str(e)}")
            raise
    
    def create_tables(self):
        """Create sample tables if they don't exist"""
        print("📋 Creating tables...")
        
        # Customers table
        create_customers_table = """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id VARCHAR(100) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Loyalty Account table
        create_loyalty_table = """
        CREATE TABLE IF NOT EXISTS loyalty_account (
            customer_id VARCHAR(100) PRIMARY KEY REFERENCES customers(customer_id),
            current_points INTEGER NOT NULL DEFAULT 0,
            lifetime_points INTEGER NOT NULL DEFAULT 0,
            tier VARCHAR(50) DEFAULT 'standard',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Products table
        create_products_table = """
        CREATE TABLE IF NOT EXISTS products (
            product_id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100),
            price DECIMAL(10, 2) NOT NULL,
            stock_quantity INTEGER DEFAULT 0,
            sku VARCHAR(50) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Inventory table - tracks stock at each location
        create_inventory_table = """
        CREATE TABLE IF NOT EXISTS inventory (
            sku VARCHAR(50) NOT NULL,
            location_id VARCHAR(50) NOT NULL,
            quantity_on_hand INTEGER NOT NULL DEFAULT 0,
            quantity_reserved INTEGER NOT NULL DEFAULT 0,
            on_order_qty INTEGER NOT NULL DEFAULT 0,
            reorder_point INTEGER NOT NULL DEFAULT 10,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sku, location_id)
        );
        """
        
        # Suppliers table - tracks supplier information
        create_suppliers_table = """
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id VARCHAR(100) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            mean_lead_time_days DECIMAL(5, 2) NOT NULL,
            reliability DECIMAL(3, 2) NOT NULL DEFAULT 0.95,
            min_order_qty INTEGER NOT NULL DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # ReplenishmentPolicy table - defines reorder policies per SKU/location
        create_replenishment_policy_table = """
        CREATE TABLE IF NOT EXISTS replenishment_policy (
            sku VARCHAR(50) NOT NULL,
            location_id VARCHAR(50) NOT NULL,
            supplier_id VARCHAR(100) NOT NULL REFERENCES suppliers(supplier_id),
            reorder_point INTEGER NOT NULL,
            order_quantity INTEGER NOT NULL,
            safety_stock INTEGER NOT NULL,
            lead_time_days DECIMAL(5, 2) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (sku, location_id)
        );
        """
        
        # PurchaseOrders table - tracks purchase orders to suppliers
        create_purchase_orders_table = """
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number VARCHAR(100) PRIMARY KEY,
            supplier_id VARCHAR(100) NOT NULL REFERENCES suppliers(supplier_id),
            status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
            expected_delivery_date TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # PurchaseOrderLines table - line items for each PO
        create_purchase_order_lines_table = """
        CREATE TABLE IF NOT EXISTS purchase_order_lines (
            po_line_id SERIAL PRIMARY KEY,
            po_number VARCHAR(100) NOT NULL REFERENCES purchase_orders(po_number) ON DELETE CASCADE,
            sku VARCHAR(50) NOT NULL,
            location_id VARCHAR(50) NOT NULL,
            order_qty INTEGER NOT NULL,
            received_qty INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Orders table - enhanced with channel and fulfillment tracking
        create_orders_table = """
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            customer_id VARCHAR(100) NOT NULL,
            order_date TIMESTAMP NOT NULL,
            total_amount DECIMAL(10, 2) NOT NULL,
            status VARCHAR(50) NOT NULL,
            channel VARCHAR(50) NOT NULL DEFAULT 'online',
            payment_status VARCHAR(50) DEFAULT 'pending',
            fulfillment_status VARCHAR(50) DEFAULT 'pending',
            workflow_source VARCHAR(50) DEFAULT 'manual',
            shipping_address TEXT,
            payment_method VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Order items table
        create_order_items_table = """
        CREATE TABLE IF NOT EXISTS order_items (
            order_item_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(product_id),
            sku VARCHAR(50),
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            subtotal DECIMAL(10, 2) NOT NULL
        );
        """
        
        # Payments table - tracks payment transactions
        create_payments_table = """
        CREATE TABLE IF NOT EXISTS payments (
            payment_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
            amount DECIMAL(10, 2) NOT NULL,
            payment_method VARCHAR(50) NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            auth_code VARCHAR(100),
            payment_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Customer Preferences table (Workflow 4)
        create_customer_preferences_table = """
        CREATE TABLE IF NOT EXISTS customer_preferences (
            customer_id VARCHAR(100) PRIMARY KEY REFERENCES customers(customer_id),
            preferred_categories TEXT,
            marketing_opt_in BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Customer Stats table (Workflow 4)
        create_customer_stats_table = """
        CREATE TABLE IF NOT EXISTS customer_stats (
            customer_id VARCHAR(100) PRIMARY KEY REFERENCES customers(customer_id),
            total_spend DECIMAL(10, 2) DEFAULT 0,
            last_purchase_date TIMESTAMP,
            purchase_count INTEGER DEFAULT 0,
            avg_order_value DECIMAL(10, 2) DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Customer Scores table (Workflow 4)
        create_customer_scores_table = """
        CREATE TABLE IF NOT EXISTS customer_scores (
            customer_id VARCHAR(100) PRIMARY KEY REFERENCES customers(customer_id),
            segment VARCHAR(50),
            value_tier VARCHAR(20),
            churn_risk_score DECIMAL(3, 2) DEFAULT 0,
            activity_state VARCHAR(20),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Points Transactions table (Workflow 4)
        create_points_transactions_table = """
        CREATE TABLE IF NOT EXISTS points_transactions (
            transaction_id SERIAL PRIMARY KEY,
            customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
            points_change INTEGER NOT NULL,
            reason VARCHAR(100),
            transaction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Support Tickets table (Workflow 4)
        create_support_tickets_table = """
        CREATE TABLE IF NOT EXISTS support_tickets (
            ticket_id VARCHAR(100) PRIMARY KEY,
            customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
            issue_type VARCHAR(50),
            status VARCHAR(20) DEFAULT 'open',
            satisfaction_rating INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );
        """
        
        # Returns table (Workflow 4)
        create_returns_table = """
        CREATE TABLE IF NOT EXISTS returns (
            return_id SERIAL PRIMARY KEY,
            customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
            order_id INTEGER REFERENCES orders(order_id),
            sku VARCHAR(50),
            refund_amount DECIMAL(10, 2),
            return_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason VARCHAR(100)
        );
        """
        
        # Recommendations Cache table (Workflow 4)
        create_recommendations_cache_table = """
        CREATE TABLE IF NOT EXISTS recommendations_cache (
            customer_id VARCHAR(100) PRIMARY KEY REFERENCES customers(customer_id),
            sku_rank_1 VARCHAR(50),
            sku_rank_2 VARCHAR(50),
            sku_rank_3 VARCHAR(50),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Customer Purchase History table (Workflow 3 - Customer Engagement)
        # Stores individual purchase transactions with real product SKUs for RFM segmentation
        create_customer_purchase_history_table = """
        CREATE TABLE IF NOT EXISTS customer_purchase_history (
            purchase_id SERIAL PRIMARY KEY,
            customer_id VARCHAR(100) NOT NULL REFERENCES customers(customer_id),
            order_id VARCHAR(100) NOT NULL,
            sku VARCHAR(50) NOT NULL,
            product_name VARCHAR(255),
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price DECIMAL(10, 2) NOT NULL,
            line_total DECIMAL(10, 2) NOT NULL,
            purchase_date TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Index for customer purchase history queries
        create_customer_purchase_history_index = """
        CREATE INDEX IF NOT EXISTS idx_customer_purchase 
        ON customer_purchase_history (customer_id, purchase_date);
        """
        
        try:
            # Create tables in dependency order (parent tables before child tables with FKs)
            # 1. Independent base tables (no foreign keys)
            self.cursor.execute(create_customers_table)
            self.cursor.execute(create_products_table)
            self.cursor.execute(create_suppliers_table)
            
            # 2. Tables with FK to base tables
            self.cursor.execute(create_loyalty_table)  # FK to customers
            self.cursor.execute(create_customer_preferences_table)  # FK to customers
            self.cursor.execute(create_customer_stats_table)  # FK to customers
            self.cursor.execute(create_customer_scores_table)  # FK to customers
            self.cursor.execute(create_customer_purchase_history_table)  # FK to customers
            self.cursor.execute(create_support_tickets_table)  # FK to customers
            self.cursor.execute(create_recommendations_cache_table)  # FK to customers
            self.cursor.execute(create_inventory_table)  # FK to products
            self.cursor.execute(create_replenishment_policy_table)  # FK to products
            self.cursor.execute(create_purchase_orders_table)  # FK to suppliers
            self.cursor.execute(create_purchase_order_lines_table)  # FK to purchase_orders
            
            # 3. Orders table (referenced by order_items, payments, returns)
            self.cursor.execute(create_orders_table)
            
            # 4. Tables with FK to orders (must come after orders)
            self.cursor.execute(create_order_items_table)  # FK to orders
            self.cursor.execute(create_payments_table)  # FK to orders
            self.cursor.execute(create_points_transactions_table)  # FK to customers, orders
            self.cursor.execute(create_returns_table)  # FK to orders
            
            # 5. Create indexes for performance
            self.cursor.execute(create_customer_purchase_history_index)
            
            self.conn.commit()
            print("✓ Tables created successfully")
            
            # Add missing columns to existing tables (migration)
            print("🔄 Checking for missing columns...")
            
            # Add payment_status to orders if it doesn't exist
            alter_orders_payment_status = """
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='orders' AND column_name='payment_status'
                ) THEN
                    ALTER TABLE orders ADD COLUMN payment_status VARCHAR(50) DEFAULT 'pending';
                END IF;
            END $$;
            """
            
            # Add sku to order_items if it doesn't exist
            alter_order_items_sku = """
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='order_items' AND column_name='sku'
                ) THEN
                    ALTER TABLE order_items ADD COLUMN sku VARCHAR(50);
                END IF;
            END $$;
            """
            
            # Add on_order_qty to inventory if it doesn't exist
            alter_inventory_on_order = """
            DO $$ 
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name='inventory' AND column_name='on_order_qty'
                ) THEN
                    ALTER TABLE inventory ADD COLUMN on_order_qty INTEGER NOT NULL DEFAULT 0;
                END IF;
            END $$;
            """
            
            self.cursor.execute(alter_orders_payment_status)
            self.cursor.execute(alter_order_items_sku)
            self.cursor.execute(alter_inventory_on_order)
            self.conn.commit()
            print("✓ Schema migration completed")
            
        except psycopg.Error as e:
            print(f"✗ Error creating tables: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def generate_products(self, count: int = 50) -> List[Tuple]:
        """Generate chocolate-themed product data with consistent categories"""
        fake = Faker()
        products = []
        
        print(f"🎲 Generating {count} chocolate product records...")
        
        # Chocolate categories
        categories = [
            "Dark Chocolate",
            "Milk Chocolate", 
            "White Chocolate",
            "Artisan Truffles",
            "Chocolate Bars",
            "Filled Chocolates"
        ]
        
        # Chocolate products with matching descriptions
        chocolate_products = [
            # Dark Chocolate (70%+ cacao)
            ("Dark Chocolate Sea Salt Caramels", "Rich 70% dark chocolate filled with buttery caramel and sprinkled with sea salt crystals", "Dark Chocolate", 24.99),
            ("Extra Dark 85% Cacao Bar", "Intense dark chocolate bar with 85% cacao content from single-origin beans", "Dark Chocolate", 12.99),
            ("Dark Chocolate Espresso Bites", "Bold dark chocolate infused with premium espresso for coffee lovers", "Dark Chocolate", 18.50),
            ("Dark Cherry Cordials", "Sweet cherries enrobed in rich dark chocolate with liquid center", "Dark Chocolate", 22.99),
            ("Dark Chocolate Orange Peel", "Candied orange peel dipped in premium dark chocolate", "Dark Chocolate", 16.99),
            ("Midnight Dark Raspberry", "72% dark chocolate with freeze-dried raspberry pieces", "Dark Chocolate", 19.99),
            ("Dark Chocolate Almond Bark", "Roasted almonds covered in smooth dark chocolate", "Dark Chocolate", 15.99),
            ("Dark Mint Thins", "Crisp mint cream sandwiched between layers of dark chocolate", "Dark Chocolate", 14.50),
            
            # Milk Chocolate
            ("Classic Milk Chocolate Bar", "Smooth and creamy milk chocolate made with premium cocoa beans", "Milk Chocolate", 8.99),
            ("Milk Chocolate Peanut Clusters", "Roasted peanuts covered in rich milk chocolate", "Milk Chocolate", 12.99),
            ("Milk Chocolate Caramel Squares", "Soft caramel centers wrapped in creamy milk chocolate", "Milk Chocolate", 16.99),
            ("Honeycomb Milk Chocolate", "Crunchy honeycomb candy coated in smooth milk chocolate", "Milk Chocolate", 13.99),
            ("Milk Chocolate Hazelnut Bar", "Whole roasted hazelnuts in creamy milk chocolate", "Milk Chocolate", 11.99),
            ("Milk Chocolate Pretzel Bites", "Crunchy pretzels covered in smooth milk chocolate", "Milk Chocolate", 14.99),
            ("Toffee Milk Chocolate Squares", "Buttery English toffee pieces in milk chocolate", "Milk Chocolate", 17.99),
            ("Milk Chocolate Raisins", "Plump raisins covered in premium milk chocolate", "Milk Chocolate", 9.99),
            
            # White Chocolate
            ("White Chocolate Raspberry Bark", "White chocolate with dried raspberries and almond pieces", "White Chocolate", 15.99),
            ("White Chocolate Macadamia", "Premium white chocolate with roasted macadamia nuts", "White Chocolate", 21.99),
            ("White Chocolate Lemon Truffles", "Creamy white chocolate ganache infused with fresh lemon", "White Chocolate", 19.99),
            ("White Chocolate Coconut Dreams", "Toasted coconut flakes in smooth white chocolate", "White Chocolate", 13.99),
            ("White Chocolate Strawberry Cream", "White chocolate filled with strawberry cream center", "White Chocolate", 16.50),
            ("White Chocolate Peppermint", "Cool peppermint in white chocolate coating", "White Chocolate", 14.99),
            ("White Chocolate Pistachio", "Roasted pistachios covered in premium white chocolate", "White Chocolate", 18.99),
            ("White Chocolate Cranberry", "Dried cranberries in smooth white chocolate", "White Chocolate", 14.50),
            
            # Artisan Truffles
            ("Champagne Truffles", "Delicate champagne-infused ganache rolled in cocoa powder", "Artisan Truffles", 32.99),
            ("Salted Caramel Truffles", "Silky caramel ganache with French sea salt", "Artisan Truffles", 28.99),
            ("Lavender Honey Truffles", "Floral lavender and honey in dark chocolate ganache", "Artisan Truffles", 29.99),
            ("Earl Grey Tea Truffles", "Bergamot-infused chocolate ganache with tea notes", "Artisan Truffles", 27.99),
            ("Bourbon Barrel Truffles", "Rich ganache with aged bourbon and vanilla notes", "Artisan Truffles", 34.99),
            ("Matcha Green Tea Truffles", "Premium matcha powder in white chocolate ganache", "Artisan Truffles", 30.99),
            ("Hazelnut Praline Truffles", "Roasted hazelnut praline in milk chocolate", "Artisan Truffles", 31.99),
            ("Passion Fruit Truffles", "Tropical passion fruit ganache in dark chocolate", "Artisan Truffles", 29.99),
            
            # Chocolate Bars
            ("Classic Milk Chocolate Bar 100g", "Traditional milk chocolate bar, perfect for sharing", "Chocolate Bars", 7.99),
            ("Dark Chocolate Almond Bar", "Whole almonds in 60% dark chocolate bar", "Chocolate Bars", 9.99),
            ("Sea Salt Caramel Bar", "Milk chocolate bar with caramel and sea salt swirls", "Chocolate Bars", 10.99),
            ("Cookie Crunch Chocolate Bar", "Milk chocolate with crunchy cookie pieces", "Chocolate Bars", 8.99),
            ("Mint Dark Chocolate Bar", "Refreshing mint in smooth dark chocolate bar", "Chocolate Bars", 9.50),
            ("Raspberry Dark Chocolate Bar", "Tart raspberry pieces in rich dark chocolate", "Chocolate Bars", 10.50),
            ("Peanut Butter Chocolate Bar", "Creamy peanut butter layered in milk chocolate", "Chocolate Bars", 9.99),
            ("Toffee Crunch Bar", "English toffee bits throughout milk chocolate bar", "Chocolate Bars", 11.50),
            
            # Filled Chocolates
            ("Cherry Cordial Collection", "Assorted cherry cordials with liqueur centers", "Filled Chocolates", 25.99),
            ("Assorted Cream Centers", "Variety of cream-filled chocolates in milk and dark", "Filled Chocolates", 22.99),
            ("Caramel Filled Chocolates", "Soft caramel centers in premium chocolate shells", "Filled Chocolates", 24.50),
            ("Nut Cluster Assortment", "Mixed nuts in milk, dark, and white chocolate", "Filled Chocolates", 26.99),
            ("Fruit Cream Collection", "Fruit-flavored cream centers in chocolate shells", "Filled Chocolates", 23.99),
            ("Coffee Cream Chocolates", "Espresso cream filling in dark chocolate cups", "Filled Chocolates", 21.99),
            ("Nougat Filled Chocolates", "Soft nougat centers wrapped in milk chocolate", "Filled Chocolates", 20.99),
            ("Marzipan Chocolates", "Almond marzipan covered in dark chocolate", "Filled Chocolates", 27.99),
            ("Coconut Cream Bonbons", "Creamy coconut filling in milk chocolate shells", "Filled Chocolates", 22.50),
            ("Peanut Butter Cups", "Smooth peanut butter in dark chocolate cups", "Filled Chocolates", 19.99)
        ]
        
        # Generate products from the defined list
        for i in range(min(count, len(chocolate_products))):
            name, description, category, base_price = chocolate_products[i]
            
            # Add some price variation (+/- 20%)
            price = round(base_price * fake.random.uniform(0.85, 1.15), 2)
            
            product = (
                name,  # name
                description,  # description
                category,  # category
                price,  # price
                fake.random_int(min=0, max=500),  # stock_quantity
                fake.bothify(text='SKU-####-????').upper()  # sku
            )
            products.append(product)
        
        print(f"✓ Generated {len(products)} chocolate product records")
        return products
    
    def generate_inventory(self, product_skus: List[str]) -> List[Tuple]:
        """
        Generate inventory records for multiple locations with varied stock levels.
        
        Creates a mix of stock statuses to support transfer recommendations:
        - Overstock: days_of_supply > 90 (high quantity, low reorder point)
        - Normal: days_of_supply 30-90
        - Low Stock: quantity <= reorder_point
        """
        fake = Faker()
        inventory = []
        
        locations = ["WAREHOUSE-001", "STORE-NYC", "STORE-LA", "STORE-CHI", "STORE-MIA"]
        
        # Define stock scenarios for each location (varies by location)
        # This creates the Overstock vs Low Stock contrast needed for transfer recommendations
        location_profiles = {
            "WAREHOUSE-001": {"bias": "overstock", "qty_range": (200, 800), "rop_range": (50, 100)},
            "STORE-NYC": {"bias": "normal", "qty_range": (30, 150), "rop_range": (15, 40)},
            "STORE-LA": {"bias": "low", "qty_range": (5, 40), "rop_range": (20, 50)},  # Often low stock
            "STORE-CHI": {"bias": "overstock", "qty_range": (100, 300), "rop_range": (10, 25)},
            "STORE-MIA": {"bias": "low", "qty_range": (8, 35), "rop_range": (25, 45)},  # Often low stock
        }
        
        print(f"🎲 Generating inventory records for {len(product_skus)} SKUs across {len(locations)} locations...")
        print(f"   Creating varied stock levels for transfer recommendations...")
        
        for sku_idx, sku in enumerate(product_skus):
            for location in locations:
                profile = location_profiles[location]
                
                # Determine stock scenario based on SKU index and location bias
                # This ensures some SKUs are overstocked in some locations and low in others
                scenario_roll = (sku_idx + hash(location)) % 10
                
                if profile["bias"] == "overstock":
                    if scenario_roll < 7:  # 70% overstock
                        qty = fake.random_int(min=profile["qty_range"][0], max=profile["qty_range"][1])
                        rop = fake.random_int(min=profile["rop_range"][0], max=profile["rop_range"][1])
                    else:  # 30% normal
                        qty = fake.random_int(min=50, max=120)
                        rop = fake.random_int(min=30, max=60)
                elif profile["bias"] == "low":
                    if scenario_roll < 6:  # 60% low stock (qty near or below ROP)
                        rop = fake.random_int(min=profile["rop_range"][0], max=profile["rop_range"][1])
                        qty = fake.random_int(min=max(3, rop - 15), max=rop + 5)  # Near ROP
                    else:  # 40% normal
                        qty = fake.random_int(min=40, max=100)
                        rop = fake.random_int(min=15, max=35)
                else:  # normal
                    qty = fake.random_int(min=profile["qty_range"][0], max=profile["qty_range"][1])
                    rop = fake.random_int(min=profile["rop_range"][0], max=profile["rop_range"][1])
                
                inventory_record = (
                    sku,  # sku
                    location,  # location_id
                    qty,  # quantity_on_hand
                    0,  # quantity_reserved
                    0,  # on_order_qty
                    rop  # reorder_point
                )
                inventory.append(inventory_record)
        
        print(f"✓ Generated {len(inventory)} inventory records with varied stock levels")
        return inventory
    
    def generate_orders(self, count: int = 100, product_count: int = 50) -> Tuple[List[Tuple], List[Tuple]]:
        """Generate fake order and order item data"""
        fake = Faker()
        orders = []
        order_items = []
        
        print(f"🎲 Generating {count} order records...")
        
        statuses = ["pending", "processing", "shipped", "delivered", "cancelled"]
        channels = ["in_store", "online", "bopis"]
        payment_statuses = ["pending", "authorized", "captured", "failed"]
        fulfillment_statuses = ["pending", "picking", "packed", "shipped", "delivered", "ready_for_pickup", "picked_up"]
        payment_methods = ["credit_card", "debit_card", "paypal", "bank_transfer"]
        
        for order_num in range(1, count + 1):
            channel = fake.random_element(elements=channels)
            payment_status = fake.random_element(elements=payment_statuses)
            order = (
                fake.uuid4(),  # customer_id
                fake.date_time_this_year(),  # order_date
                0,  # total_amount (will be calculated)
                fake.random_element(elements=statuses),  # status
                channel,  # channel
                payment_status,  # payment_status
                fake.random_element(elements=fulfillment_statuses),  # fulfillment_status
                "seed_data",  # workflow_source
                fake.address() if channel != "in_store" else None,  # shipping_address
                fake.random_element(elements=payment_methods)  # payment_method
            )
            
            # Generate 1-5 items per order
            num_items = fake.random_int(min=1, max=5)
            order_total = 0
            
            for _ in range(num_items):
                product_id = fake.random_int(min=1, max=product_count)
                quantity = fake.random_int(min=1, max=5)
                unit_price = round(fake.random.uniform(9.99, 299.99), 2)
                subtotal = round(unit_price * quantity, 2)
                order_total += subtotal
                
                order_item = (
                    order_num,  # order_id
                    product_id,  # product_id
                    quantity,  # quantity
                    unit_price,  # unit_price
                    subtotal  # subtotal
                )
                order_items.append(order_item)
            
            # Update order with total amount
            order = order[:2] + (round(order_total, 2),) + order[3:]
            orders.append(order)
        
        print(f"✓ Generated {len(orders)} order records with {len(order_items)} order items")
        return orders, order_items
    
    def generate_suppliers(self, count: int = 50) -> List[Tuple]:
        """Generate fake supplier data"""
        fake = Faker()
        suppliers = []
        
        print(f"🎲 Generating {count} supplier records...")
        
        supplier_names = [
            "Global Supply Co.", "Pacific Distributors", "Metro Wholesale", 
            "Premier Vendors", "United Suppliers", "Alliance Trading",
            "Continental Imports", "Eastern Distribution", "Western Logistics",
            "National Wholesale Group", "Premier Trading Partners", "Apex Distributors",
            "Summit Supply Chain", "Vertex Wholesale", "Horizon Imports",
            "Cascade Distribution", "Pinnacle Logistics", "Elite Suppliers Inc.",
            "Meridian Trading Co.", "Quantum Wholesale", "Nexus Supply Group",
            "Titan Distributors", "Phoenix Trading", "Atlas Supply Chain",
            "Sterling Wholesale", "Crown Distributors", "Sovereign Imports",
            "Empire Trading Partners", "Legacy Supply Co.", "Prime Logistics Group",
            "Odyssey Distributors", "Zenith Wholesale", "Nova Supply Chain",
            "Everest Trading Co.", "Keystone Distributors", "Frontier Imports",
            "Ascent Supply Group", "Prestige Wholesale", "Dynasty Trading",
            "Triumph Distributors", "Excellence Supply Co.", "Vanguard Logistics",
            "Prosperity Trading", "Fortune Wholesale", "Synergy Distributors",
            "Unity Supply Chain", "Infinity Trading Co.", "Victory Wholesale",
            "Omega Distributors", "Alpha Supply Group"
        ]
        
        for i in range(count):
            supplier = (
                f"SUP-{i+1:03d}",  # supplier_id
                supplier_names[i] if i < len(supplier_names) else fake.company(),  # name
                # round(fake.random.uniform(2.0, 14.0), 2),  # mean_lead_time_days
                round(fake.random.uniform(0.2, 1.4), 2),  # mean_lead_time_days
                round(fake.random.uniform(0.85, 0.99), 2),  # reliability
                fake.random_element(elements=[50, 100, 200, 500])  # min_order_qty
            )
            suppliers.append(supplier)
        
        print(f"✓ Generated {len(suppliers)} supplier records")
        return suppliers
    
    def generate_replenishment_policies(self, product_skus: List[str], 
                                       supplier_ids: List[str]) -> List[Tuple]:
        """Generate replenishment policies for SKUs at locations"""
        fake = Faker()
        policies = []
        
        locations = ["WAREHOUSE-001", "STORE-NYC", "STORE-LA", "STORE-CHI", "STORE-MIA"]
        
        print(f"🎲 Generating replenishment policies for {len(product_skus)} SKUs...")
        
        for sku in product_skus:
            # Not all SKUs need policies at all locations
            # Warehouse gets policy for all, stores for subset
            for location in locations:
                if "WAREHOUSE" in location or fake.boolean(chance_of_getting_true=60):
                    supplier_id = fake.random_element(elements=supplier_ids)
                    
                    # Warehouse has higher thresholds
                    if "WAREHOUSE" in location:
                        reorder_point = fake.random_int(min=100, max=300)
                        order_quantity = fake.random_int(min=500, max=2000)
                        safety_stock = fake.random_int(min=50, max=150)
                    else:
                        reorder_point = fake.random_int(min=10, max=50)
                        order_quantity = fake.random_int(min=100, max=500)
                        safety_stock = fake.random_int(min=5, max=30)
                    
                    policy = (
                        sku,  # sku
                        location,  # location_id
                        supplier_id,  # supplier_id
                        reorder_point,  # reorder_point
                        order_quantity,  # order_quantity
                        safety_stock,  # safety_stock
                        round(fake.random.uniform(2.0, 10.0), 2)  # lead_time_days
                    )
                    policies.append(policy)
        
        print(f"✓ Generated {len(policies)} replenishment policies")
        return policies
    
    def fetch_customers_from_cosmos(self) -> List[Dict]:
        """Fetch customers from CosmosDB (source of truth)"""
        print("📥 Fetching customers from CosmosDB...")
        
        cosmos_endpoint = os.getenv("COSMOSDB_ENDPOINT")
        cosmos_key = os.getenv("COSMOSDB_PRIMARY_KEY")
        cosmos_database = os.getenv("COSMOSDB_DATABASE_NAME")
        cosmos_container = "Customers"  # Application-level container
        
        if not all([cosmos_endpoint, cosmos_key, cosmos_database]):
            print("⚠ CosmosDB configuration not found, skipping customer sync")
            return []
        
        try:
            client = CosmosClient(cosmos_endpoint, cosmos_key)
            database = client.get_database_client(cosmos_database)
            container = database.get_container_client(cosmos_container)
            
            # Query all customers
            query = "SELECT * FROM c"
            customers = list(container.query_items(query=query, enable_cross_partition_query=True))
            
            print(f"✓ Fetched {len(customers)} customers from CosmosDB")
            return customers
            
        except Exception as e:
            print(f"⚠ Error fetching from CosmosDB: {e}")
            return []
    
    def seed_customers_from_cosmos(self, customers: List[Dict]) -> int:
        """Insert customers from CosmosDB into PostgreSQL"""
        if not customers:
            print("⚠ No customers to seed")
            return 0
        
        print(f"💾 Seeding {len(customers)} customers into PostgreSQL...")
        
        insert_query = """
        INSERT INTO customers (customer_id, name, email, created_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (customer_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            email = EXCLUDED.email
        """
        
        try:
            records = []
            for customer in customers:
                # Map CosmosDB fields to PostgreSQL
                customer_id = customer.get('customerId', customer.get('id'))
                first_name = customer.get('firstName', '')
                last_name = customer.get('lastName', '')
                name = f"{first_name} {last_name}".strip() or "Unknown"
                email = customer.get('email', '')
                created_at = customer.get('accountCreated', None)
                
                records.append((customer_id, name, email, created_at))
            
            self.cursor.executemany(insert_query, records)
            self.conn.commit()
            print(f"✓ Successfully synced {len(records)} customers from CosmosDB to PostgreSQL")
            return len(records)
            
        except psycopg.Error as e:
            print(f"✗ Error inserting customers: {e}")
            self.conn.rollback()
            raise
    
    def generate_customer_purchase_history(self, customer_ids: List[str], product_skus: List[str]) -> List[Tuple]:
        """Generate detailed purchase transactions with real product SKUs
        
        High-level distribution across RFM segments:
        - 20% Champions (8-20 orders over 5-25 days, $600-2000 total)
        - 30% Loyal (4-8 orders over 30-55 days, $300-600 total)
        - 30% Potential (1-3 orders over 60-85 days, $120-300 total)
        - 20% Needs Attention (no purchases)
        
        Returns list of tuples: (customer_id, order_id, sku, product_name, quantity, 
                                  unit_price, line_total, purchase_date)
        """
        import random
        from datetime import datetime, timedelta
        from uuid import uuid4
        
        print(f"🎲 Generating detailed purchase transactions for {len(customer_ids)} customers...")
        
        # Load product details from database (SKU -> name, price)
        self.cursor.execute("SELECT sku, name, price FROM products")
        products = {row[0]: (row[1], float(row[2])) for row in self.cursor.fetchall()}
        
        if not products:
            print("⚠ No products found - cannot generate purchase history")
            return []
        
        available_skus = list(products.keys())
        now = datetime.now()
        transactions = []
        
        for i, customer_id in enumerate(customer_ids):
            segment_pct = i / len(customer_ids)
            
            # Determine segment parameters
            if segment_pct < 0.20:  # 20% Champions
                num_orders = random.randint(8, 20)
                days_back = random.randint(5, 25)
                target_spend = random.uniform(600, 2000)
                
            elif segment_pct < 0.50:  # 30% Loyal
                num_orders = random.randint(4, 8)
                days_back = random.randint(30, 55)
                target_spend = random.uniform(300, 600)
                
            elif segment_pct < 0.80:  # 30% Potential
                num_orders = random.randint(1, 3)
                days_back = random.randint(60, 85)
                target_spend = random.uniform(120, 300)
                
            else:  # 20% Needs Attention (no purchases)
                continue
            
            # Generate orders distributed over time period
            avg_spend_per_order = target_spend / num_orders
            
            for order_num in range(num_orders):
                order_id = f"ORD-{customer_id[:8]}-{uuid4().hex[:8]}"
                
                # Distribute purchase dates across the time period
                order_days_back = random.uniform(0, days_back)
                purchase_date = now - timedelta(days=order_days_back)
                
                # Generate 1-4 line items per order
                items_in_order = random.randint(1, 4)
                order_spend = 0
                
                for item_num in range(items_in_order):
                    # Pick random product
                    sku = random.choice(available_skus)
                    product_name, unit_price = products[sku]
                    
                    # Determine quantity (mostly 1-2, occasionally more)
                    quantity = random.choices([1, 2, 3, 4], weights=[60, 30, 8, 2])[0]
                    
                    # Adjust price slightly (+/- 5% for discounts/promotions)
                    price_variance = random.uniform(0.95, 1.0)
                    final_unit_price = round(unit_price * price_variance, 2)
                    line_total = round(final_unit_price * quantity, 2)
                    
                    order_spend += line_total
                    
                    transactions.append((
                        customer_id,
                        order_id,
                        sku,
                        product_name,
                        quantity,
                        final_unit_price,
                        line_total,
                        purchase_date
                    ))
                    
                    # Stop adding items if we've hit target spend for this order
                    if order_spend >= avg_spend_per_order * 1.2:  # Allow 20% variance
                        break
        
        print(f"✓ Generated {len(transactions)} purchase transactions across {len([c for c in customer_ids if customer_ids.index(c) / len(customer_ids) < 0.80])} customers")
        print(f"   Distribution: 20% Champions, 30% Loyal, 30% Potential, 20% Needs Attention")
        return transactions
    
    def seed_customer_purchase_history(self, transactions: List[Tuple]) -> int:
        """Insert customer purchase transactions into database"""
        print(f"💾 Seeding {len(transactions)} purchase transactions into PostgreSQL...")
        
        insert_query = """
        INSERT INTO customer_purchase_history 
            (customer_id, order_id, sku, product_name, quantity, unit_price, line_total, purchase_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        try:
            self.cursor.executemany(insert_query, transactions)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(transactions)} purchase transactions")
            return len(transactions)
        except psycopg.Error as e:
            print(f"✗ Error inserting purchase transactions: {e}")
            self.conn.rollback()
            raise
    
    def seed_suppliers(self, suppliers: List[Tuple]) -> int:
        """Insert suppliers into database"""
        print(f"💾 Seeding {len(suppliers)} suppliers into PostgreSQL...")
        
        insert_query = """
        INSERT INTO suppliers (supplier_id, name, mean_lead_time_days, reliability, min_order_qty)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (supplier_id)
        DO UPDATE SET
            name = EXCLUDED.name,
            mean_lead_time_days = EXCLUDED.mean_lead_time_days,
            reliability = EXCLUDED.reliability,
            min_order_qty = EXCLUDED.min_order_qty,
            updated_at = CURRENT_TIMESTAMP
        """
        
        try:
            self.cursor.executemany(insert_query, suppliers)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(suppliers)} suppliers")
            return len(suppliers)
        except psycopg.Error as e:
            print(f"✗ Error inserting suppliers: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def seed_replenishment_policies(self, policies: List[Tuple]) -> int:
        """Insert replenishment policies into database"""
        print(f"💾 Seeding {len(policies)} replenishment policies into PostgreSQL...")
        
        insert_query = """
        INSERT INTO replenishment_policy 
            (sku, location_id, supplier_id, reorder_point, order_quantity, safety_stock, lead_time_days)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (sku, location_id)
        DO UPDATE SET
            supplier_id = EXCLUDED.supplier_id,
            reorder_point = EXCLUDED.reorder_point,
            order_quantity = EXCLUDED.order_quantity,
            safety_stock = EXCLUDED.safety_stock,
            lead_time_days = EXCLUDED.lead_time_days,
            updated_at = CURRENT_TIMESTAMP
        """
        
        try:
            self.cursor.executemany(insert_query, policies)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(policies)} replenishment policies")
            return len(policies)
        except psycopg.Error as e:
            print(f"✗ Error inserting replenishment policies: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def seed_inventory(self, inventory: List[Tuple]) -> int:
        """Insert inventory records into database"""
        print(f"💾 Seeding {len(inventory)} inventory records into PostgreSQL...")
        
        insert_query = """
        INSERT INTO inventory (sku, location_id, quantity_on_hand, quantity_reserved, on_order_qty, reorder_point)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (sku, location_id) 
        DO UPDATE SET 
            quantity_on_hand = EXCLUDED.quantity_on_hand,
            quantity_reserved = EXCLUDED.quantity_reserved,
            on_order_qty = EXCLUDED.on_order_qty,
            last_updated = CURRENT_TIMESTAMP
        """
        
        try:
            self.cursor.executemany(insert_query, inventory)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(inventory)} inventory records")
            return len(inventory)
        except psycopg.Error as e:
            print(f"✗ Error inserting inventory: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def seed_products(self, products: List[Tuple]) -> int:
        """Insert products into database"""
        print(f"💾 Seeding {len(products)} products into PostgreSQL...")
        
        insert_query = """
        INSERT INTO products (name, description, category, price, stock_quantity, sku)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        try:
            self.cursor.executemany(insert_query, products)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(products)} products")
            return len(products)
        except psycopg.Error as e:
            print(f"✗ Error inserting products: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def seed_orders(self, orders: List[Tuple], order_items: List[Tuple]) -> int:
        """Insert orders and order items into database"""
        print(f"💾 Seeding {len(orders)} orders into PostgreSQL...")
        
        insert_order_query = """
        INSERT INTO orders (customer_id, order_date, total_amount, status, channel, payment_status, fulfillment_status, workflow_source, shipping_address, payment_method)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        insert_order_item_query = """
        INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
        VALUES (%s, %s, %s, %s, %s)
        """
        
        try:
            self.cursor.executemany(insert_order_query, orders)
            self.cursor.executemany(insert_order_item_query, order_items)
            self.conn.commit()
            print(f"✓ Successfully inserted {len(orders)} orders and {len(order_items)} order items")
            return len(orders)
        except psycopg.Error as e:
            print(f"✗ Error inserting orders: {e}")
            print(f"Error code: {e.pgcode if hasattr(e, 'pgcode') else 'N/A'}")
            print(f"Error details: {e.pgerror if hasattr(e, 'pgerror') else str(e)}")
            self.conn.rollback()
            raise
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        print("🔌 Database connection closed")


def main():
    """Main execution function"""
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments for phased seeding
    import argparse
    parser = argparse.ArgumentParser(description='Seed PostgreSQL with sample data')
    parser.add_argument('--phase', type=int, choices=[1, 2], default=None,
                       help='Phase 1: Tables/suppliers/products only. Phase 2: Import customers, seed policies/orders')
    args = parser.parse_args()
    
    # Get PostgreSQL configuration
    pg_host = os.getenv("POSTGRESQL_SERVER_FQDN")
    pg_database = os.getenv("POSTGRESQL_DATABASE_NAME")
    pg_user = os.getenv("POSTGRESQL_ADMIN_LOGIN")
    pg_password = os.getenv("POSTGRESQL_ADMIN_PASSWORD")
    
    if not all([pg_host, pg_database, pg_user, pg_password]):
        print("✗ Error: Missing PostgreSQL configuration in .env file")
        print("  Required: POSTGRESQL_SERVER_FQDN, POSTGRESQL_DATABASE_NAME, POSTGRESQL_ADMIN_LOGIN, POSTGRESQL_ADMIN_PASSWORD")
        sys.exit(1)
    
    print("=" * 60)
    print("🌱 PostgreSQL Data Seeding Script")
    if args.phase:
        print(f"   Mode: Phase {args.phase}")
    print("=" * 60)
    
    seeder = None
    try:
        # Initialize seeder
        seeder = PostgresSeeder(pg_host, pg_database, pg_user, pg_password)
        seeder.connect()
        seeder.create_tables()
        
        # PHASE 1: Create foundation data (suppliers, products)
        # This creates the product SKUs that CosmosDB carts/inventory events need
        if args.phase == 1 or args.phase is None:
            print("\n📦 Phase 1: Creating foundation data (suppliers, products)...")
            
            # Generate and seed suppliers first
            suppliers = seeder.generate_suppliers(count=50)
            seeder.seed_suppliers(suppliers)
            supplier_ids = [s[0] for s in suppliers]
            
            # Generate and seed products (creates SKUs)
            products = seeder.generate_products(count=50)
            seeder.seed_products(products)
            product_skus = [p[5] for p in products]  # SKU is 6th element (index 5)
            
            # Generate and seed inventory
            inventory = seeder.generate_inventory(product_skus)
            seeder.seed_inventory(inventory)
            
            print(f"✓ Phase 1 complete: {len(suppliers)} suppliers, {len(products)} products, inventory created")
            
            if args.phase == 1:
                print("💡 Next: Run CosmosDB seeding (Phase 1) to create customers")
                print("=" * 60)
                return
        
        # PHASE 2: Import customers and create dependent data (policies, orders)
        # This requires customers to exist in CosmosDB first
        if args.phase == 2 or args.phase is None:
            print("\n📦 Phase 2: Importing customers and creating dependent data...")
            
            # Fetch product SKUs and supplier IDs (they should exist from Phase 1)
            print("   Fetching existing products and suppliers...")
            seeder.cursor.execute("SELECT sku FROM products")
            product_skus = [row[0] for row in seeder.cursor.fetchall()]
            
            seeder.cursor.execute("SELECT supplier_id FROM suppliers")
            supplier_ids = [row[0] for row in seeder.cursor.fetchall()]
            
            seeder.cursor.execute("SELECT COUNT(*) FROM products")
            actual_product_count = seeder.cursor.fetchone()[0]
            
            if not product_skus or not supplier_ids:
                print("✗ Error: No products or suppliers found. Run Phase 1 first.")
                sys.exit(1)
            
            print(f"   Found {len(product_skus)} products, {len(supplier_ids)} suppliers")
            
            # Sync customers from CosmosDB (source of truth) to PostgreSQL
            cosmos_customers = seeder.fetch_customers_from_cosmos()
            seeder.seed_customers_from_cosmos(cosmos_customers)
            
            # Fetch customer IDs for purchase history generation
            seeder.cursor.execute("SELECT customer_id FROM customers")
            customer_ids = [row[0] for row in seeder.cursor.fetchall()]
            
            # Generate and seed synthetic purchase history (for RFM segmentation in Workflow 3)
            purchase_histories = seeder.generate_customer_purchase_history(customer_ids, product_skus)
            seeder.seed_customer_purchase_history(purchase_histories)
            
            # Generate and seed replenishment policies
            policies = seeder.generate_replenishment_policies(product_skus, supplier_ids)
            seeder.seed_replenishment_policies(policies)
            
            # Generate and seed orders (use actual product count from database)
            orders, order_items = seeder.generate_orders(count=500, product_count=actual_product_count)
            seeder.seed_orders(orders, order_items)
            
            print(f"✓ Phase 2 complete: customers imported, {len(policies)} policies, {len(orders)} orders created")
            
            if args.phase == 2:
                print("💡 Next: Run CosmosDB seeding (Phase 2) to create carts and events")
        
        print("=" * 60)
        print(f"✓ PostgreSQL seeding completed successfully")
        print("=" * 60)
        
    except Exception as e:
        print(f"✗ Error during seeding: {str(e)}")
        sys.exit(1)
    finally:
        if seeder:
            seeder.close()


if __name__ == "__main__":
    main()

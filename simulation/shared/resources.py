"""
Shared resource registry for multi-workflow simulations.

This module manages SimPy resources that can be accessed by multiple
workflow simulations, including:
- Checkout counters
- Fulfillment staff (pickers, packers)
- Inventory levels across locations
"""

import simpy
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import logging

from .config import ResourceConfig


logger = logging.getLogger(__name__)


@dataclass
class InventoryLevel:
    """Tracks inventory for a specific SKU at a location"""
    sku: str
    location: str
    quantity_on_hand: int
    quantity_reserved: int
    reorder_point: int
    
    @property
    def available(self) -> int:
        """Available quantity = on_hand - reserved"""
        return max(0, self.quantity_on_hand - self.quantity_reserved)
    
    def can_fulfill(self, quantity: int) -> bool:
        """Check if sufficient inventory is available"""
        return self.available >= quantity
    
    def reserve(self, quantity: int) -> bool:
        """Reserve inventory for an order"""
        if self.can_fulfill(quantity):
            self.quantity_reserved += quantity
            logger.debug(f"Reserved {quantity} of {self.sku} at {self.location}")
            return True
        return False
    
    def fulfill(self, quantity: int) -> bool:
        """Fulfill reserved inventory (decrements on_hand and reserved)"""
        if quantity <= self.quantity_reserved and quantity <= self.quantity_on_hand:
            self.quantity_on_hand -= quantity
            self.quantity_reserved -= quantity
            logger.debug(f"Fulfilled {quantity} of {self.sku} at {self.location}")
            return True
        return False
    
    def cancel_reservation(self, quantity: int):
        """Cancel a reservation"""
        self.quantity_reserved = max(0, self.quantity_reserved - quantity)
        logger.debug(f"Cancelled reservation of {quantity} for {self.sku} at {self.location}")
    
    def restock(self, quantity: int):
        """Add inventory (for returns or replenishment)"""
        self.quantity_on_hand += quantity
        logger.debug(f"Restocked {quantity} of {self.sku} at {self.location}")


class InventoryRegistry:
    """Manages inventory across all SKUs and locations"""
    
    def __init__(self):
        # Key: (sku, location) -> InventoryLevel
        self.inventory: Dict[Tuple[str, str], InventoryLevel] = {}
        self.stockout_events: list = []  # Track stockout occurrences
    
    def register_sku(self, sku: str, location: str, quantity: int, reorder_point: int = 10):
        """Register a SKU at a location with initial inventory"""
        key = (sku, location)
        self.inventory[key] = InventoryLevel(
            sku=sku,
            location=location,
            quantity_on_hand=quantity,
            quantity_reserved=0,
            reorder_point=reorder_point
        )
        logger.debug(f"Registered SKU {sku} at {location} with {quantity} units")
    
    def get_inventory(self, sku: str, location: str) -> Optional[InventoryLevel]:
        """Get inventory level for a SKU at a location"""
        return self.inventory.get((sku, location))
    
    def check_availability(self, sku: str, location: str, quantity: int) -> bool:
        """Check if inventory is available"""
        inv = self.get_inventory(sku, location)
        if not inv:
            logger.warning(f"SKU {sku} not found at {location}")
            return False
        return inv.can_fulfill(quantity)
    
    def reserve_inventory(self, sku: str, location: str, quantity: int) -> bool:
        """Reserve inventory for an order"""
        inv = self.get_inventory(sku, location)
        if not inv:
            return False
        
        success = inv.reserve(quantity)
        if not success:
            self.stockout_events.append({
                'sku': sku,
                'location': location,
                'requested': quantity,
                'available': inv.available
            })
            logger.warning(f"Stockout: {sku} at {location} (requested {quantity}, available {inv.available})")
        return success
    
    def fulfill_inventory(self, sku: str, location: str, quantity: int) -> bool:
        """Fulfill reserved inventory"""
        inv = self.get_inventory(sku, location)
        if not inv:
            return False
        return inv.fulfill(quantity)
    
    def cancel_reservation(self, sku: str, location: str, quantity: int):
        """Cancel inventory reservation"""
        inv = self.get_inventory(sku, location)
        if inv:
            inv.cancel_reservation(quantity)
    
    def restock_inventory(self, sku: str, location: str, quantity: int):
        """Restock inventory (for returns or replenishment)"""
        inv = self.get_inventory(sku, location)
        if inv:
            inv.restock(quantity)
        else:
            # If SKU not registered, register it
            self.register_sku(sku, location, quantity)
    
    def get_low_stock_items(self) -> list:
        """Get list of items below reorder point"""
        low_stock = []
        for (sku, location), inv in self.inventory.items():
            if inv.quantity_on_hand <= inv.reorder_point:
                low_stock.append({
                    'sku': sku,
                    'location': location,
                    'current': inv.quantity_on_hand,
                    'reorder_point': inv.reorder_point
                })
        return low_stock
    
    def get_stockout_count(self) -> int:
        """Get total number of stockout events"""
        return len(self.stockout_events)


class ResourceRegistry:
    """Central registry for all simulation resources"""
    
    def __init__(self, env: simpy.Environment, config: ResourceConfig):
        self.env = env
        self.config = config
        
        # Checkout resources (per location)
        self.checkout_counters: Dict[str, simpy.Resource] = {}
        for location in config.locations:
            if location.startswith("STORE-"):
                self.checkout_counters[location] = simpy.Resource(
                    env, 
                    capacity=config.checkout_counters_per_store
                )
        
        # Fulfillment resources
        self.warehouse_pickers = simpy.Resource(env, capacity=config.warehouse_pickers)
        self.warehouse_packers = simpy.Resource(env, capacity=config.warehouse_packers)
        
        # Store fulfillment staff (BOPIS orders)
        self.store_staff: Dict[str, simpy.Resource] = {}
        for location in config.locations:
            if location.startswith("STORE-"):
                self.store_staff[location] = simpy.Resource(
                    env,
                    capacity=config.store_fulfillment_staff
                )
        
        # Inventory registry
        self.inventory = InventoryRegistry()
        
        # Resource utilization tracking
        self.resource_usage = {
            'checkout': [],
            'pickers': [],
            'packers': [],
            'store_staff': []
        }
        
        logger.info("Resource registry initialized")
    
    def get_checkout_resource(self, location: str) -> Optional[simpy.Resource]:
        """Get checkout resource for a store location"""
        return self.checkout_counters.get(location)
    
    def get_store_staff_resource(self, location: str) -> Optional[simpy.Resource]:
        """Get store staff resource for BOPIS fulfillment"""
        return self.store_staff.get(location)
    
    def track_resource_usage(self, resource_type: str, in_use: int, timestamp: float):
        """Track resource utilization over time"""
        self.resource_usage[resource_type].append({
            'time': timestamp,
            'in_use': in_use
        })
    
    def get_utilization_stats(self) -> dict:
        """Calculate resource utilization statistics"""
        stats = {}
        
        # Checkout counters
        for location, resource in self.checkout_counters.items():
            stats[f'checkout_{location}'] = {
                'capacity': resource.capacity,
                'current_users': len(resource.users),
                'queue_length': len(resource.queue)
            }
        
        # Fulfillment resources
        stats['warehouse_pickers'] = {
            'capacity': self.warehouse_pickers.capacity,
            'current_users': len(self.warehouse_pickers.users),
            'queue_length': len(self.warehouse_pickers.queue)
        }
        
        stats['warehouse_packers'] = {
            'capacity': self.warehouse_packers.capacity,
            'current_users': len(self.warehouse_packers.users),
            'queue_length': len(self.warehouse_packers.queue)
        }
        
        # Store staff
        for location, resource in self.store_staff.items():
            stats[f'store_staff_{location}'] = {
                'capacity': resource.capacity,
                'current_users': len(resource.users),
                'queue_length': len(resource.queue)
            }
        
        # Inventory stats
        stats['inventory'] = {
            'total_skus': len(self.inventory.inventory),
            'stockouts': self.inventory.get_stockout_count(),
            'low_stock_items': len(self.inventory.get_low_stock_items())
        }
        
        return stats

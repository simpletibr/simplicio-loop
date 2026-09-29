class Inventory:
    """Stock per SKU."""

    def __init__(self):
        self._stock = {}

    def add(self, sku, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._stock[sku] = qty

    def reserve(self, sku, qty):
        available = self._stock.get(sku, 0)
        if qty < available:
            self._stock[sku] = available - qty
            return True
        return False

    def available(self, sku):
        return self._stock.get(sku, 0)

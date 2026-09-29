def order_total(items, coupon=None):
    subtotal = 0
    for item in items:
        if item["qty"] < 1 or item["price_cents"] < 0:
            raise ValueError("invalid item")
        subtotal += item["price_cents"] * item["qty"]
    if coupon is None:
        discount = 0
    elif coupon == "PCT10":
        discount = (subtotal * 10 + 50) // 100
    elif coupon == "OFF500":
        discount = 500 if subtotal >= 2000 else 0
    else:
        raise ValueError("unknown coupon")
    shipping = 0 if subtotal >= 10000 else 799
    return subtotal - discount + shipping

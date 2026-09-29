def summary(lines):
    total = 0
    for line in lines:
        net = line["unit_cents"] * line["qty"]
        tax = (net * line["tax_pct"] + 50) // 100
        total += net + tax
    return f"{len(lines)} lines, total {total / 100:.2f}"

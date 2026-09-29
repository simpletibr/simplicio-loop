def line_total(line):
    net = line["unit_cents"] * line["qty"]
    tax = (net * line["tax_pct"] + 50) // 100
    return net + tax

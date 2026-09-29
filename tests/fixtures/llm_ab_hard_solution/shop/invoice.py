from shop.money import line_total


def invoice_total(lines):
    return sum(line_total(line) for line in lines)

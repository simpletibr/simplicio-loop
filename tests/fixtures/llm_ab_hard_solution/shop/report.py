from shop.money import line_total


def summary(lines):
    total = sum(line_total(line) for line in lines)
    return f"{len(lines)} lines, total {total / 100:.2f}"

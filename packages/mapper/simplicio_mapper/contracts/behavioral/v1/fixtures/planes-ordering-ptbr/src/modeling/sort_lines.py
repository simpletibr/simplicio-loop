def sort_lines(lines):
    """Ordenacao de linhas: estrutural, temporal e modelagem por data de inicio."""
    return sorted(lines, key=lambda line: (line.kind, line.start_date))

def sort_lines(lines):
    # linhas estruturais primeiro; temporais e modelagem por data de inicio
    priority = {"estrutural": 0, "temporal": 1, "modelagem": 2}
    return sorted(lines, key=lambda item: (priority[item["tipo"]], item["inicio"], item["nome"]))

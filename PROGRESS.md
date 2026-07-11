# PROGRESS

- 2026-07-07: contexto obrigatório lido. `.starter-meta.json` ausente => modo `root`.
- Segurança/robustez implementadas: `mechanical_edit`, `dod`, auto-upgrade opt-in no `ecosystem`, guards de CLI/shared/bench/skill_router, writes atômicas e validação de comandos cross-platform para os testes/contracts existentes.
- Follow-up aplicado: a superfície MCP foi removida do dev-cli (`serve --mcp`, `mcp_server.py`, testes/fixtures/docs correlatos).
- Release prep concluído: `simplicio-mapper` mínimo atualizado para `>=0.18.0`, artefatos versionados de bench re-hashados, e API pública `simplicio.mapper_api` adicionada para expor o pacote `simplicio-mapper` instalado.
- Validações finais verdes: `ruff check .`, `ruff format --check .`, `mypy simplicio`, `pytest -q`, `python scripts/gen_package_interdependence.py --check`, `python -m build`, `python -m twine check dist/*`.
- 2026-07-11: iniciada drenagem das issues abertas. Slice P0 #129 implementado: extração de artifact de arquivo completo, reconstrução determinística de diff quando não há unified diff, fallback após patch stale/corrupt, persistência de parser strategy e metadados de modelo no JSON. Teste focado verde; suite completa ainda revela falhas preexistentes fora do slice.

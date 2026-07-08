# GOAL_RESULT

## Objective
Implementar as melhorias não rastreadas priorizadas para segurança/robustez, CI/release, dívida técnica, auto-upgrade opt-in, remoção da superfície MCP do dev-cli e preparar/publicar a release `0.10.0`.

## Outcome
Escopo técnico concluído e gate local completo verde. Branch pronta para merge/release/publicação.

## Delivered
- Harden de path/symlink + snapshots atômicos em `mechanical_edit.py`.
- DoD gates sem `shell=True` por padrão, com opt-in controlado.
- Auto-upgrade do ecosystem agora opt-in; comparação prerelease corrigida.
- JSONL com append travado, summary streaming, rotação simples e writes atômicas reutilizáveis.
- Guards adicionais em CLI/shared/bench/skill_router/pipeline/runtime.
- Remoção da superfície MCP do dev-cli (`serve --mcp`).
- CI/release atualizados (remoção de workflows mortos, Python 3.13, cache pip, smoke de wheel, Trusted Publishing).
- `simplicio-mapper` mínimo atualizado para `>=0.18.0`.
- API pública `simplicio.mapper_api` para expor o `simplicio-mapper` instalado a consumidores Python.
- Artefatos versionados de bench re-hashados para alinhar evidência e fixtures aos arquivos atuais.

## Validation
- PASS: `ruff check .`
- PASS: `ruff format --check .`
- PASS: `mypy simplicio`
- PASS: `pytest -q`
- PASS: `python scripts/gen_package_interdependence.py --check`
- PASS: `python -m build`
- PASS: `python -m twine check dist/*`

# PERSONAS — simplicio-mapper

Quem consome o mapper, em que contexto, e qual é a expectativa concreta
de cada um. Use isso para decidir prioridades e quebrar empates de design.

---

## P1 · Agent orchestrator (SendSprint / simplicio-sprint)

- **Quem** — bot que recebe uma sprint/issue e dispara agentes em lote.
- **Comando que chama** — `simplicio-mapper index <repo>` antes de cada
  execução de agente.
- **Quer**
  - Exit codes estáveis (0/1/2), JSON estável (`--json`), idempotência
    real (<200 ms quando nada mudou).
  - Mensagens de erro acionáveis (`status="failed"`, `error="..."`).
  - Lock que evita corridas com refreshes em background concorrentes.
- **Não tolera** — output não estruturado, schema drift, log ruidoso em
  no-op.

---

## P2 · LLM-driven dev CLI (simplicio-dev-cli)

- **Quem** — Python CLI 6-layer prompt (mapper + precedent + skill-router +
  core + test + verify + retry) que entrega tasks com modelos médios e
  fracos a >96 % de sucesso.
- **Comando que chama** — lê `.simplicio/project-map.json`,
  `precedent-index.json`, `architecture-inventory.json`, `symbol-index.json`,
  `call-graph.json` direto.
- **Quer**
  - Sinal alto por token: `roles`, `importance`, `entry_points`,
    `recent_changes`, `architecture.signals`.
  - Precedents pré-tagueados por `change_type` para retrieval orientado
    pela task.
  - Schema previsível para o `_mapper` plug-point em `prompt.py`.
- **Não tolera** — paths absolutos do host, hashes voláteis, schema
  divergente entre runtimes Node e Python.

---

## P3 · Engenheiro humano (manutenção/debug)

- **Quem** — pessoa que abre o repo, dá `simplicio-mapper docs .` e quer
  entender módulos, layers, símbolos e relações sem ler todo o código.
- **Comando que chama** — `simplicio-mapper docs <path> --json`,
  `simplicio-mapper export-docs <path> --target ./wiki-export`.
- **Quer**
  - Markdown derivado dos JSONs em `.simplicio/docs/*.md` com layers,
    call-graph, módulos.
  - Diff legível semana a semana.
- **Não tolera** — docs alucinados, prosa LLM, conteúdo que não bate com
  o código.

---

## P4 · CI / DoD gate (.github/workflows)

- **Quem** — workflows `dod.yml`, `python-ci.yml`, `scaffold-self-check.yml`,
  `publish-pypi.yml`.
- **Comando que chama** — não chama o mapper diretamente, mas depende do
  pacote Python ser instalável, dos testes (`unittest`/`pytest`) verdes e
  do lint (`ruff`) limpo.
- **Quer**
  - Build reproduzível (`hatchling>=1.27,<1.28`).
  - Versões alinhadas (`scripts/check-version-sync.js`).
  - Pytest verde antes de qualquer publish.
- **Não tolera** — divergência de versão entre `package.json`,
  `pyproject.toml`, `__init__.py`.

---

## P5 · Maintainer de pacote (release/PyPI)

- **Quem** — humano que faz o bump, escreve o changelog e dispara o
  publish.
- **Comando que chama** — `npm test`, `python -m pytest tests/python`,
  `python -m build`, `python -m twine check dist/*`, `git tag`.
- **Quer**
  - Changelog Keep-a-Changelog 1.1.0 atualizado.
  - Workflow `publish-pypi.yml` idempotente (skip se versão igual à
    publicada).
  - Wheels e sdist passando em `twine check`.
- **Não tolera** — release publicado sem changelog ou com testes
  vermelhos, secret de token vazando em commit/log.

---

## Não-personas

- **Não atendemos** agentes que pedem o mapper para gerar prosa ou opinar
  sobre código. Isso é deliberado: o mapper só extrai sinais
  observáveis. Quem opina é o consumidor.

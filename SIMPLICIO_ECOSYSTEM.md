# simplicio-loop no Ecossistema Simplicio

## Quem depende deste repo
Nenhum outro repositório Simplicio consome este repo como pacote/plugin. A partir do #115,
`simplicio-loop` também publica um **contrato exportável** — `simplicio.loop-execution/v1`
(`contracts/loop-execution/v1/`) — para que **`simplicio-runtime`** (ou qualquer outro consumidor)
reutilize a disciplina de execução converge/drain já validada aqui em vez de criar um segundo
contrato de execução incompatível. Ainda não é uma dependência formal (nenhum código deste repo
importa `simplicio-runtime` de volta, e o runtime ainda não consome o contrato) — é a superfície
publicada para essa reutilização acontecer. Ver `contracts/loop-execution/v1/SCHEMA.md`.

## De quem este repo depende
- [simplicio-mapper](packages/mapper/) — hard dep (binds `orient`), agora um pacote deste monorepo
- [simplicio-dev-cli](packages/dev-cli/) (pip pkg `simplicio-cli`) — hard dep (binds `execute`/`deterministic_edit`), agora um pacote deste monorepo

## Versão atual
3.22.2 (pyproject.toml)

## Versão mínima esperada pelos dependentes
Nenhuma — este repo não é dependência formal de outros Simplicios.

---

_Last updated: 2026-07-06_

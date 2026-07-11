# Memory handoff

## Goal

Entregar um slice real e determinístico da issue #89 sem depender de `ai-memory`
ou HRM em Rust: armazenamento markdown+git, recall por keywords, auditoria da
store e pacote de handoff entre agentes.

## User Flow

1. `simplicio-py memory init --dir <path>` cria `README.md` e `notes/`.
2. `simplicio-py memory store "<topic>" "<content>"` anexa uma entrada append-only.
3. `simplicio-py memory validate --json` audita integridade da store.
4. `simplicio-py memory handoff "<query>" --from-agent codex --to-agent claude --json`
   gera um pacote determinístico com resultados do recall + status de validação.

## Main Files

| Layer | Files |
|---|---|
| CLI | `simplicio/cli.py`, `simplicio/commands/memory.py` |
| Service/domain | `simplicio/memory_store.py` |
| Tests | `tests/python/test_memory_store.py`, `tests/python/test_commands_direct_namespace.py` |

## Business Rules

- O slice atual é **Zero-LLM**: sem embeddings, sem rede, sem FTS5.
- `validate` só verifica invariantes locais da store; não afirma integração HRM externa.
- `handoff` é derivado de `recall` + `validate`, então permanece determinístico e reproduzível.
- Se integração com repositórios Rust externos for exigida, o estado correto é blocker explícito.

## Test Scenarios

- Store válida retorna `ok=true` e conta notas/entries corretamente.
- Nota quebrada sem header `# <topic>` falha em `validate`.
- `handoff` preserva `from_agent`, `to_agent`, ator da entrada e tags.

## Known Risks

- Recall ainda é lexical; ranking semântico/FTS5 híbrido continua fora deste slice.
- `git` segue best-effort e nunca bloqueia a store.

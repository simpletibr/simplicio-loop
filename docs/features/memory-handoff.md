# Memory handoff

## Goal

Entregar um backend local, real e determinístico inspirado no `ai-memory`: armazenamento
markdown+git, índice SQLite FTS5, ranking lexical/vectorial híbrido, auditoria HRM
estrutural e pacote de handoff entre agentes. O Markdown continua sendo a fonte de
verdade; nenhum modelo ou serviço externo é necessário.

## User Flow

1. `simplicio-py memory init --dir <path>` cria `README.md` e `notes/`.
2. `simplicio-py memory store "<topic>" "<content>"` anexa uma entrada append-only.
3. `simplicio-py memory recall "<query>" --mode fts5|vector|hybrid` consulta o índice.
4. `simplicio-py memory validate --json` audita integridade da store e do índice.
5. `simplicio-py memory handoff "<query>" --from-agent codex --to-agent claude --json`
   gera um pacote determinístico com resultados do recall + status de validação.

## Main Files

| Layer | Files |
|---|---|
| CLI | `simplicio/cli.py`, `simplicio/commands/memory.py` |
| Service/domain | `simplicio/memory_store.py` |
| Tests | `tests/python/test_memory_store.py`, `tests/python/test_commands_direct_namespace.py` |

## Business Rules

- O backend é **Zero-LLM**: o modo `fts5` usa SQLite FTS5 e `vector` usa um vetor
  lexical hashado estável; `hybrid` combina os dois scores.
- `validate` só verifica invariantes locais da store; não afirma integração HRM externa.
- `handoff` é derivado de `recall` + `validate`, então permanece determinístico e reproduzível.
- A integração é compatível por contrato e não shella um daemon Rust: isso mantém
  instalação sem dependência nova e permite qualquer cliente consumir os arquivos.

## Test Scenarios

- Store válida retorna `ok=true` e conta notas/entries corretamente.
- Nota quebrada sem header `# <topic>` falha em `validate`.
- `handoff` preserva `from_agent`, `to_agent`, ator da entrada e tags.

## Known Risks

- O vetor local é uma aproximação lexical determinística, não um embedding neural
  treinado. Um modelo Rust/embedding externo pode ser adicionado atrás do mesmo
  contrato sem alterar o formato Markdown.
- `git` segue best-effort e nunca bloqueia a store.

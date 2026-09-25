# VISION — simplicio-mapper

Documento de uma página. Mantém o time alinhado sobre o porquê. Atualizar
quando a tese mudar; registrar versão anterior em ADR antes de reescrever.

---

## Problema

Agentes de coding (Claude Code, Codex, Copilot, Cursor, Aider, Simplicio Agent) abrem
qualquer repo sem contexto e gastam tokens redescobrindo a arquitetura, o
naming, os entry points e os precedents toda execução. Em projetos médios e
grandes, isso vira:

- variância alta entre runs (mesma task, resultados diferentes);
- prompts grandes e caros sem sinal claro;
- bugs por suposição (paths que não existem, dependências erradas, schemas
  divergentes do que o repo realmente expõe).

As soluções existentes ou são generalistas (RAG genérico em todo arquivo,
caro e ruidoso) ou específicas demais para um único framework.

---

## Quem usa

- **Agentes** rodando em CLIs, web app, IDE plugins, ou em sessões de
  orquestração (SendSprint, simplicio-dev-cli, simplicio-sprint, Hyperframes).
- **Humanos** que mantêm esses agentes — engenheiros que precisam que a
  primeira ação do agente no repo seja consistente, idempotente e barata.

---

## Proposta de valor

`simplicio-mapper` produz artefatos JSON estáveis e versionados sobre **um
repo qualquer**, em segundos, sem pedir LLM no caminho crítico:

- `.simplicio/project-map.json` — inventário determinístico de arquivos,
  linguagens, roles, imports/exports e importance score.
- `.simplicio/precedent-index.json` — exemplos de alta qualidade (snippets)
  para retrieval orientado por mudança.
- `.simplicio/architecture-inventory.json`, `symbol-index.json`,
  `call-graph.json` — visão de módulos, símbolos e relações.
- Bootstrap idempotente via `simplicio-mapper index <path>` que curto-circuita
  em <200 ms quando o repo não mudou (exit codes 0/1/2 estáveis para
  orquestradores).

Tudo opera offline, com dependências leves (`orjson`, `diskcache`) e um
fast-path opt-in em Rust via PyO3 para hashing/parsing em escala.

---

## Tese central

Contexto de projeto deve ser um **artefato compilável**, não um prompt cada
hora. Quem dá esse contexto para os agentes é uma camada determinística
versionada (schemas `simplicio.*/v1`), não o modelo. O modelo só decide.

---

## Out of scope

- Geração ou edição de código a partir dos artefatos.
- Orquestração multi-agente (responsabilidade de `simplicio-sprint`).
- LLM gateways, billing, pricing (responsabilidade de `simplicio-prompt`).

---

## Sucesso

- Agentes integrados com `simplicio-mapper` reduzem variância e tokens em
  tarefas reais (medido pelos consumidores: simplicio-dev-cli benchmarks,
  SendSprint progress tables).
- `simplicio-mapper index .` roda em <200 ms quando idempotente, e o JSON
  contract permanece compatível com agentes que já consomem `v1`.
- Toda mudança de schema vem com ADR e bump de versão.

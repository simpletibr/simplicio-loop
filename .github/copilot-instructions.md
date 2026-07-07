# Copilot Instructions

> Instruction file lido automaticamente pelo **GitHub Copilot Chat** e **Copilot Workspace / Agent Mode**.
>
> **Fonte canônica: [`../AGENTS.md`](../AGENTS.md).** Este arquivo era, até a issue #163, um hand-copy quase completo de `AGENTS.md` (Stack, Comandos, Workflow loop, Definition of Done, Padrões, Proibido, etc.) — mantido manualmente em paralelo, sujeito a drift. A partir de agora ele é um **stub curto**: só o que é genuinamente específico do Copilot Agent Mode vive aqui; tudo o mais (stack, comandos, workflow loop/DoD/proibido, onde encontrar contexto, yool/tuple/HAMT) **lê direto de `AGENTS.md`**. `scripts/check-doc-sync.js check` falha em CI se este arquivo voltar a crescer para um hand-copy completo (limite de linhas + checagem de que ainda aponta pra `AGENTS.md`).
>
> Ao trabalhar em Agent Mode, o Copilot pode delegar pra custom agents em [`.agents/`](../.agents/) (canônico, padrão AGENTS.md ecosystem) e/ou em `.github/copilot/agents/` (mirror lido pelo Copilot Coding Agent). Lista atual: `tdd.agent.md`, `reviewer.agent.md`, `architect.agent.md`.

---

## Onde ler o resto

Tudo que não é específico de Copilot Agent Mode vive em [`AGENTS.md`](../AGENTS.md) — leia de lá, não duplique aqui:

| Precisa de... | Onde está |
|---|---|
| Stack, comandos de dev/lint/test | `AGENTS.md` § Stack, § Comandos importantes |
| Workflow loop obrigatório (incluindo critério de E2E, issue #162) | `AGENTS.md` § Workflow loop OBRIGATÓRIO |
| Definition of Done | `AGENTS.md` § Definition of Done |
| Padrões de código | `AGENTS.md` § Padrões de código (`.specs/architecture/PATTERNS.md`) |
| Lista negra (proibido) | `AGENTS.md` § Proibido |
| yool / tuple / HAMT | `AGENTS.md` § yool / tuple / HAMT |
| Onde encontrar contexto de produto/arquitetura | `AGENTS.md` § Onde encontrar contexto |

Copilot Chat/Workspace segue o mesmo Conventional Commits, o mesmo DoD gate (`.github/workflows/dod.yml`), e a mesma política de dependência ("pergunta antes de adicionar") descritas em `AGENTS.md` — sem exceção específica de Copilot.

---

## O que é específico de Copilot Agent Mode (fica aqui, não em AGENTS.md)

### Custom agents (Copilot Workspace / Agent Mode)

Copilot pode delegar pra um custom agent quando a tarefa casa com a `description` do agent. Definidos em [`.agents/`](../.agents/) (canônico) e espelhados em `.github/copilot/agents/` (mirror para Copilot Coding Agent):

- **`ralph-loop.agent.md`** — Ralph Loop (padrão autônomo, Ralph Wiggum technique). Loop `read → plan → execute → lint → unit → Playwright → fix → repeat` até DoD verde. **No Copilot CLI**: `copilot --autopilot --yolo --max-autopilot-continues 20 -p "<prompt>"`. **No VS Code Agent Mode**: dropdown Mode → Agent + permission level **Autopilot** = continuous iteration nativo. Em outras ferramentas: Claude Code `/ralph-loop` (plugin oficial), Codex CLI `/goal`, Cursor Background Agent. Tools: `edit`, `terminal`, `search`.
- **`tdd.agent.md`** — TDD Specialist. Escreve teste falhando antes do código. Loop red-green-refactor. Tools: `edit`, `terminal`, `search`. Aciona quando tarefa exige cobertura nova ou regression test.
- **`reviewer.agent.md`** — Code Reviewer. Read-only. Comenta problemas e sugestões em PR. Tools: `search`, `read`. Aciona em revisão de PR aberto, sem editar arquivos.
- **`architect.agent.md`** — Architect. Desenha arquitetura, cria ADRs, atualiza `PATTERNS.md`. **Não escreve código de produção.** Tools: `edit`, `search`, `read`. Aciona em decisão arquitetural, refactor amplo, integração nova.

Pra invocar explicitamente em Copilot Chat: `@ralph-loop`, `@tdd`, `@reviewer`, `@architect`.

### Skills específicas do fluxo Copilot

- **`playwright-e2e`** — como escrever teste Playwright. Trigger: nova feature de UI / fluxo end-to-end (ver critério de quando E2E é obrigatório em `AGENTS.md`, issue #162).
- **`conventional-commits`** — regras de commit. Trigger: hora de commitar.

Detalhes completos de todas as skills: `.skills/README.md`.

---

## Notas finais

- **Idioma**: docs em pt-BR, código em inglês, commits em inglês (mesma regra de `AGENTS.md`).
- **Sem resumo no final** de resposta; sem estimativa de tempo; pergunta só em ambiguidade real.
- **Paralelismo** — research + read + review independentes rodam simultâneos em Agent Mode.

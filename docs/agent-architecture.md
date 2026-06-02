# Agent Architecture — simplicio-cli + ralph-loop

> Como o `simplicio-cli` se compõe com o padrão Ralph Loop para virar um agent autônomo, mantendo o foco do CLI no que ele faz melhor (prompt + precedent + bench).

Documento de visão única. Para a decisão arquitetural por trás disto, ver [`ADR-002-simplicio-ralph-composition`](../.specs/architecture/ADR-002-simplicio-ralph-composition.md).

---

## TL;DR

- `simplicio-cli` = **gerador de código** com prompt afiado (precedent + skill_router). Não é agent end-to-end.
- `ralph-loop` = **padrão de orquestração** autônoma (read → plan → execute → gates → fix → loop).
- `.agents/simplicio-ralph.agent.md` = **spec da composição**: ralph orquestra, `simplicio-py task` é uma das ferramentas no passo `execute`.
- Cobertura ampla (review, refactor amplo, debug, análise, arquitetura) vem do orquestrador externo (Claude Code, Codex CLI, Copilot, Cursor, Aider) **rotear** para ferramenta certa por tipo de task — não de inchar o CLI.

---

## Por que não "tudo no simplicio-cli"

Pergunta natural: pra ter **mais cobertura**, não deveríamos colocar tudo dentro do CLI? Resposta curta: **não**, porque:

| Critério | Inchar simplicio-cli | Compor com ralph-loop |
|---|---|---|
| Diferencial preservado | ✗ dilui (vira mais um agent) | ✓ prompt+precedent+bench seguem únicos |
| Manutenção (1 dev) | ✗ pesada (N subcomandos) | ✓ leve (1 arquivo markdown) |
| Sobreposição com Claude/Codex/Copilot | ✗ direta | ✓ aproveita o que já existe |
| Trocabilidade | ✗ acoplado | ✓ plug-in/out |
| Benchmark estável | ✗ código muda → bench muda | ✓ CLI intocado |
| Adesão padrão `AGENTS.md` | parcial | ✓ total |
| Coverage de tasks não-code-gen | manual (precisa codar) | ✓ delegado ao orquestrador |

ADR-002 documenta a decisão completa, com alternativas avaliadas e critério de revisão.

---

## Camadas

```
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 1 — Orquestrador (lê AGENTS.md + .agents/)         │
│  ──────────────────────────────────────────────────────────  │
│  Claude Code  Codex CLI  Copilot CLI  Cursor  Aider         │
│  /ralph-loop  /goal       autopilot   bg-agent  wrapper     │
│                                                             │
│  Responsável: ler task, orquestrar loop, gates,             │
│               evidência, exit signal, commit, PR.           │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ no passo "execute"
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 2 — Roteamento por tipo de task                    │
│  ──────────────────────────────────────────────────────────  │
│  type=code-gen        ───►  simplicio-py task --target ...     │
│  type=refactor amplo  ───►  edit direto (multi-file)        │
│  type=analise         ───►  search/read tools               │
│  type=review          ───►  .agents/reviewer.agent.md       │
│  type=arquitetura     ───►  .agents/architect.agent.md      │
│  type=tdd             ───►  .agents/tdd.agent.md            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ quando simplicio é escolhido
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 3 — simplicio-cli (gerador focado)                 │
│  ──────────────────────────────────────────────────────────  │
│  cli.py        →  argparse subcomandos                       │
│  precedent.py  →  indexa repo, extrai precedente             │
│  skill_router  →  escolhe skill por goal                     │
│  prompt.py     →  monta prompt final (goal+precedent+skill)  │
│  providers.py  →  chama LLM (claude/openai/openrouter/etc.)  │
│  pipeline.py   →  loop interno curto (3 attempts)            │
│  bench.py      →  mede pass-rate em cases.json               │
│                                                             │
│  Responsável: gerar código bom dada uma task code-gen.      │
│  Não responsável por: aplicar diff, gates, evidência, PR.   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  CAMADA 4 — Provedores LLM                                  │
│  ──────────────────────────────────────────────────────────  │
│  Anthropic  OpenAI  OpenRouter  modelos locais (llama.cpp)  │
└─────────────────────────────────────────────────────────────┘
```

---

## Fluxo end-to-end (caminho feliz)

```
1. Humano: "fecha task T-042"
        │
        ▼
2. Orquestrador (Camada 1)
   ├─ lê .specs/sprints/sprint-XX/T-042-*.task.md
   ├─ lê .agents/simplicio-ralph.agent.md
   ├─ decide: type=code-gen (alvo claro, AC mensurável)
   └─ roteia para simplicio (Camada 2)
        │
        ▼
3. Orquestrador chama: simplicio-py task "<goal>" --target <path>
        │
        ▼
4. simplicio-cli (Camada 3)
   ├─ precedent.py extrai precedente do repo
   ├─ skill_router escolhe skill (angular-reactive-forms, etc.)
   ├─ prompt.py monta prompt final
   ├─ providers.py chama LLM (Camada 4)
   ├─ recebe output (diff/blocos de código)
   └─ grava em .simplicio/last_output.txt
        │
        ▼
5. Orquestrador aplica edits no repo (camada 1 retoma)
        │
        ▼
6. Orquestrador roda gates:
   ├─ lint  → ok|fail
   ├─ unit  → ok|fail (coverage diff ≥ 80%)
   └─ e2e   → ok|fail (trace + screenshot + video em playwright-report/)
        │
        ▼
7. Verde + EXIT_SIGNAL: true?
   ├─ sim → commit (conventional) + PR (gh pr create --fill)
   └─ não → re-roda passo 3 com feedback=<log do erro>
```

---

## Roteamento por tipo de task (matriz)

| Sintoma da task | Tipo | Tool no execute | Por quê |
|---|---|---|---|
| "implementar form validation em foo.component.ts" | code-gen 1-file | `simplicio-py task` | Target claro + precedent ajuda |
| "renomear `User` para `Account` em 20 arquivos" | refactor amplo | edit direto / sed | Multi-file, mecânico |
| "por que o test X tá flaky?" | análise | search/read + debug | Sem código novo, só leitura |
| "revisar este PR" | review | `reviewer.agent.md` | Read-only, opina |
| "decidir banco SQL vs NoSQL" | arquitetura | `architect.agent.md` | ADR, sem código |
| "adicionar test pra bug Y" | tdd | `tdd.agent.md` | Red-green-refactor |
| "documentar API endpoint" | doc | edit direto | Markdown, sem precedent |
| "migration do schema" | migration | edit + dry-run | Reversibilidade importa |

Regra geral: simplicio brilha quando **precedente do repo + skill afiada** fazem diferença. Tasks mecânicas ou puramente exploratórias não ganham com isso.

---

## Como invocar (por ferramenta)

Mesma semântica, sintaxe diferente:

```bash
# Claude Code
/ralph-loop "use .agents/simplicio-ralph.agent.md; task=T-042; loop até DoD"

# Claude Code headless (CI)
claude -p "agent=simplicio-ralph; task=T-042" \
  --permission-mode acceptEdits \
  --max-turns 50

# Codex CLI ≥ 0.128
/goal seguir .agents/simplicio-ralph.agent.md para T-042

# Copilot CLI
copilot --autopilot --max-autopilot-continues 20 \
  -p "execute T-042 via simplicio-py task; loop DoD"

# Cursor ≥ 3.0
# UI: Background Agent → prompt referenciando .agents/simplicio-ralph.agent.md

# Aider (wrapper)
while ! grep -q "EXIT_SIGNAL: true" .ralph/state; do
  simplicio-py task "..." --target ...
  npm run lint && npm test && npx playwright test || continue
  echo "EXIT_SIGNAL: true" > .ralph/state
done
```

Pré-requisito comum em todas:

```bash
# 1ª vez ou após mudança grande no repo
simplicio-py index --root . --stack <stack>

# vars de ambiente do simplicio
export SIMPLICIO_PROVIDER=claude
export SIMPLICIO_MODEL=claude-sonnet-4-6
export SIMPLICIO_TEST_CMD="npm run lint && npm test && npx playwright test"
```

---

## Limitações conhecidas e como o orquestrador compensa

| Limite do simplicio-cli | Compensação pelo orquestrador |
|---|---|
| `MAX_ATTEMPTS = 3` hardcoded em [pipeline.py:6](../simplicio/pipeline.py) | Orquestrador relança quantas vezes precisar (cap via `--max-turns` / `--max-autopilot-continues`) |
| Apply de diff é stub ([pipeline.py:11](../simplicio/pipeline.py)) | Orquestrador interpreta output e aplica edits no repo |
| Sem `EXIT_SIGNAL` nativo (só `returncode == 0`) | Orquestrador injeta `EXIT_SIGNAL: true` no prompt, verifica no output, valida gates externos |
| Sem budget de token/custo | Orquestrador limita via `--max-turns` ou contador externo |
| Sem trace unificado | Logs em 2 lugares (`.simplicio/last_output.txt` + log do orquestrador). Debug exige cruzar. |
| Só code-gen (1 target) | Orquestrador roteia tasks fora desse perfil para outros agents/ferramentas |

Estes limites são **intencionais**: cada camada faz uma coisa. ADR-002 detalha por que aceitamos esses trade-offs.

---

## O que **não** muda neste design

- **`simplicio/*.py`** — código intocado.
- **`bench/`** — benchmarks reproduzíveis com mesma versão do código.
- **`README.md`** — narrativa do produto inalterada.
- **`README.pt-BR.md`** — idem.
- **Provedores LLM** — sem novos adapters.
- **Comandos do CLI** — `index`, `task`, `bench`, `smoke` continuam exatamente como estão.

Risco zero pra quem hoje usa só `simplicio-py task` standalone.

---

## O que **muda** neste design (aditivo)

| Arquivo | Status | Função |
|---|---|---|
| [`.agents/simplicio-ralph.agent.md`](../.agents/simplicio-ralph.agent.md) | **novo** | Spec da composição. Lido por orquestradores. |
| [`.agents/README.md`](../.agents/README.md) | atualizado | Lista o agent novo. |
| [`AGENTS.md`](../AGENTS.md) | atualizado | Entry na seção "Custom agents disponíveis". |
| [`CLAUDE.md`](../CLAUDE.md) | atualizado | Mirror do AGENTS.md. |
| [`.specs/architecture/ADR-002-simplicio-ralph-composition.md`](../.specs/architecture/ADR-002-simplicio-ralph-composition.md) | **novo** | Decisão arquitetural registrada. |
| [`docs/agent-architecture.md`](./agent-architecture.md) | **novo** | Este documento. |

Total: 2 arquivos novos + 3 listagens atualizadas. Zero linha de código mexida.

---

## Composição com outros agents do repo

```
                  ┌──────────────────────────┐
                  │ humano define a task     │
                  └────────────┬─────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │ orquestrador escolhe     │
                  │ agent pela natureza      │
                  └────────────┬─────────────┘
       ┌───────────────────────┼─────────────────────────┐
       │                       │                         │
       ▼                       ▼                         ▼
┌─────────────────┐  ┌────────────────────┐  ┌────────────────────┐
│ architect.agent │  │ simplicio-ralph    │  │ reviewer.agent     │
│ ─ decisão       │  │ ─ execução         │  │ ─ revisão          │
│ ─ ADR           │  │   via simplicio    │  │   read-only        │
│ ─ PATTERNS.md   │  │ ─ ralph loop       │  │ ─ comenta no PR    │
└────────┬────────┘  └─────────┬──────────┘  └──────────┬─────────┘
         │                     │                        │
         ▼                     ▼                        ▼
   (cria ADR se          (executa task             (após PR aberto)
   decisão nova,         até DoD verde,
   antes do exec)        com simplicio
                         como gerador)

         tdd.agent       ralph-loop.agent (padrão genérico)
         (variante:      (variante:
         test-first      execute sem simplicio,
         dentro do       edit direto)
         loop)
```

Cadeia típica de uma feature: `architect` (se decisão nova) → `tdd` (escreve teste) → `simplicio-ralph` (implementa) → `reviewer` (aprova).

---

## Critério de sucesso desta arquitetura

Sabemos que o design está funcionando quando:

1. **Bench permanece estável** — mesma versão do CLI = mesmo resultado. Verde.
2. **Cobertura amplia sem tocar CLI** — novo tipo de task aparece, basta novo agent spec, sem código novo no simplicio.
3. **Outros orquestradores adotam** — Codex e Copilot rodam o agent sem adaptação especial.
4. **PRs do projeto fecham via loop** — task fechada com evidência Playwright sem intervenção manual extra.
5. **Manutenção fica leve** — 1 dev consegue manter sem dívida acumulando.

Falha = qualquer um desses parar de valer. Aí revisitamos via novo ADR (ver `Critério de revisão` no ADR-002).

---

## Referências

- [`.specs/architecture/ADR-002-simplicio-ralph-composition.md`](../.specs/architecture/ADR-002-simplicio-ralph-composition.md) — decisão arquitetural completa.
- [`.agents/ralph-loop.agent.md`](../.agents/ralph-loop.agent.md) — padrão Ralph Loop neste repo.
- [`.agents/simplicio-ralph.agent.md`](../.agents/simplicio-ralph.agent.md) — spec da composição.
- [`.agents/README.md`](../.agents/README.md) — convenção `.agents/`.
- [`AGENTS.md`](../AGENTS.md) — master instruction file do repo.
- [`bench/results.md`](../bench/results.md) — números do benchmark que justificam o foco.
- [`simplicio/cli.py`](../simplicio/cli.py), [`pipeline.py`](../simplicio/pipeline.py), [`precedent.py`](../simplicio/precedent.py), [`skill_router.py`](../simplicio/skill_router.py) — código do CLI.
- Ralph Wiggum technique (origem do padrão): https://ghuntley.com/ralph/
- Anthropic plugin oficial `claude-plugins-official` (ralph-loop): instalado via `/plugin install ralph-loop@claude-plugins-official`.
- Codex CLI `/goal` (≥ 0.128): https://github.com/openai/codex
- GitHub Copilot CLI autopilot: `copilot --autopilot --help`

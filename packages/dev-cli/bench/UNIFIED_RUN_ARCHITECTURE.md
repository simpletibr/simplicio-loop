# `simplicio-py run` — unified orchestrator (task / feature / sprint)

> **Status:** design proposal. Não implementado.
> **Owner:** simplicio-dev-cli, tracking issue #TBD.
> **Date:** 2026-05-30.

---

## 1. Problema

Hoje temos 3 níveis de abstração espalhados por 3 entry-points distintos:

| nível | entry point hoje | escopo | re-plan? | exit gate |
|---|---|---|---|---|
| atomic task | `simplicio-py task` | 1 file, 1 test | não | test_command exit 0 |
| from-scratch project | `simplicio-py scratch` | repo novo, N tasks | parcial | scaffold + N tasks verde |
| existing repo, vague | **falta** | N files, multi-step | n/a | n/a |

A lacuna é o último — quando o user diz "consertar todos os testes falhando do PR", "implementar módulo de auth", "fechar sprint 12", **não temos onde meter**. Ele acaba indo pra Claude Code, Cursor BG, Codex `/goal`, Ralph loop manual — soluções de fora.

A direção: **un único `simplicio-py run`** que classifica a vagueza do goal e despacha pra primitivo apropriado, mantendo nosso cli+ag como spine atômica.

---

## 2. Os 3 modos sob um teto

```
simplicio-py run "<goal>" [--scope auto|task|feature|sprint]
                       [--max-cost $X] [--max-iter N]
                       [--existing|--scratch]
```

### Scope auto-detecção (default)

| sinal no goal | scope inferido |
|---|---|
| goal cita arquivo único + tem critério testável | **task** |
| goal é nome de feature (1-3 palavras de domínio) | **feature** |
| goal lista N items, fecha sprint, "implement entire X" | **sprint** |
| goal nomeia projeto inexistente | **scratch** (mode separado, já implementado) |

Override explícito via `--scope`.

### O que cada scope faz

#### scope=task (já existe — `simplicio-py task`)

```
goal → cli 6-layer → cli+ag verify-loop (max 3-5 attempts) → exit
```

- 1 LLM call + até 5 retries com feedback classificado
- Custo bounded: 1-5 calls
- Edita 1 arquivo

#### scope=feature (NOVO)

```
goal
  ↓ planner (DeepSeek-V4-Flash / sp default)
plan: 3-8 tasks ordenadas (depends_on)
  ↓ orchestrator Ralph-style:
    for task in plan:
        result = simplicio-py task (cli+ag)
        if result.passed: continue
        else: replan_remaining(failure_context) → continue
  ↓ exit when all tasks green OR max_iter reached
```

- 1 planner call + N × (1-5 doer calls)
- Custo bounded: configurável via --max-cost
- Multi-file (1 file por task, mas N tasks)
- Re-plan quando task X falha 5x — replanner recebe ("task X falhou com kind=Y" + estado atual) e propõe alternativa

#### scope=sprint (NOVO)

```
goal (vago) → de-vague step:
  - read .specs/sprints/sprint-XX/SPRINT.md (se existe)
  - lista tasks em .specs/sprints/sprint-XX/*.task.md
  ↓ batch mode:
    for task in sprint_tasks:
        run --scope feature "<task.goal>"
  ↓ exit when sprint DoD checklist verde
```

- N features × N tasks × cli+ag
- Custo escala MUITO — `--max-cost` é obrigatório
- Estado salvo a cada task em `.simplicio-loop/sprint_state.json` (resumível)
- Wall-clock pode passar horas — mensagem clara: "isso vai rodar X tempo, custar ~$Y, OK pressionar Enter?"

#### scope=scratch (já existe — `simplicio-py scratch`)

Mantém como está. `run` redireciona quando detecta que o repo não existe.

---

## 3. Arquitetura — o que muda, o que fica

```
                       ┌────────────────────────┐
                       │   simplicio-py run        │
                       │   intent classifier    │
                       └──────────┬─────────────┘
                                  │
            ┌─────────┬───────────┴───────────┬─────────┐
            ▼         ▼                       ▼         ▼
         task     feature                 sprint    scratch
            │         │                       │         │
            │         ▼                       ▼         │
            │   plan (planner)         sprint loader    │
            │         │                       │         │
            │         ▼                       ▼         │
            │   orchestrator              orch × N      │
            │   (Ralph-style              features      │
            │    replan)                              │
            │         │                       │         │
            └────┬────┴───────────────────────┴─────────┘
                 ▼
        ┌─────────────────┐
        │  pipeline.run   │  ← cli+ag (today's primitive,
        │  (atomic task)  │     6-layer + 3-5 retry)
        └─────────────────┘
                 │
                 ▼
            provider call
            (LLM)
```

### Componentes novos

1. **`simplicio/intent.py`** — `classify_goal(text) → IntentResult(scope, confidence, signals)`. Regex + heurísticas + LLM fallback.
2. **`simplicio/orchestrator/`** — Ralph-style replan loop entre tasks. Novo módulo.
3. **`simplicio/orchestrator/cost_governor.py`** — sumariza tokens/$$, mata loop ao bater `--max-cost`.
4. **`simplicio/sprint_loader.py`** — lê `.specs/sprints/sprint-XX/*.task.md` se existir; reusa o que `scratch` já tem.

### Componentes que ficam (não regridem)

- `simplicio.pipeline.run` (cli+ag verify-loop) — primitivo atômico
- `simplicio.scratch.planner.generate_plan` (planner) — usado pra `feature`
- `simplicio.scratch.executor.execute_plan` (task runner) — generalizado pra `feature` orchestrator

### Componentes a renomear/refatorar

- `simplicio.scratch.executor` → `simplicio.orchestrator.executor` (não é mais só pra scratch)
- `simplicio-py task` → fica como atalho pra `simplicio-py run --scope task`

---

## 4. Re-plan: o que Ralph traz que cli+ag sozinho não tem

Hoje cli+ag faz retry com feedback **dentro da mesma task**. Se task X tem 5 attempts e todas falham, simplicio desiste.

Ralph-style replan adiciona: **se task X falhou, replaneja as próximas tasks pra contornar X**.

```python
# orchestrator pseudo-code
for i, task in enumerate(plan):
    result = pipeline.run(task)
    if result.passed:
        continue
    # task X failed all attempts. Re-plan the remaining tasks.
    failure_ctx = classify_failure(result.log)
    if failure_ctx.kind == "dependency_missing":
        # planner: insert install-dep task BEFORE retrying X
        plan = planner.insert_dep_task(plan, i, failure_ctx)
    elif failure_ctx.kind == "design_wrong":
        # planner: redesign tasks i..end with new approach
        plan = planner.replan_from(plan, i, failure_ctx)
    elif failure_ctx.kind == "out_of_scope":
        # mark task as skipped, continue with next
        result.skipped = True
    else:
        # bail — manual intervention needed
        return ExitWithError(task, failure_ctx)
```

Essa é a peça que falta hoje. **cli+ag retry feedback é local** (mesma task, mesma especificação). **Orchestrator replan é global** (re-arranja o plano restante).

---

## 5. Cost governor — o que falta pra owner um sprint inteiro

Sem cap de custo, `--scope sprint` é roleta russa. Implementação:

```python
class CostGovernor:
    budget: Decimal  # USD
    spent: Decimal
    token_pricing: dict[str, dict]  # model → {prompt, completion} $/Mtok
    
    def charge(self, model, prompt_tokens, completion_tokens) -> bool:
        cost = price(model, prompt_tokens, completion_tokens)
        self.spent += cost
        return self.spent <= self.budget  # False = kill loop
    
    def report(self) -> dict:
        return {"budget": self.budget, "spent": self.spent,
                "remaining": self.budget - self.spent, ...}
```

Wraps every LLM call. Default budget pelo scope:
- task: $0.50
- feature: $5.00
- sprint: `--max-cost` obrigatório (sem default, fail fast)

Hook em `providers.generate` + `providers.planner_complete` + `sp_fanout_*`. Governor singleton lê do env `SIMPLICIO_MAX_COST=N` se não passado via flag.

---

## 6. DoD checklist — exit gate além de "test passou"

Ralph clássico usa DoD checklist. Hoje cli+ag exit gate é só `subprocess(test_cmd).returncode == 0`. Pra sprint orchestration, isso é fraco — pode passar testes e deixar lint quebrado, ou passar test mas faltar evidence/screenshot.

Proposta: `simplicio/dod.py` lê `.specs/workflow/DOD.md` (se existe) e cada item vira gate:

```yaml
# .specs/workflow/DOD.md → estruturado por seções
- [ ] Unit tests pass (`pnpm test`)
- [ ] E2E pass (`npx playwright test`) [evidence: playwright-report/]
- [ ] Lint clean (`pnpm lint`)
- [ ] Type check (`pnpm typecheck`)
- [ ] No console.log left behind (grep)
```

Cada gate vira função executável; sprint só fecha quando todas marcam ok.

---

## 7. Fases de entrega

| fase | escopo | esforço | depende de |
|---|---|---|---|
| **F0 — wire-up** | `simplicio-py run` argparse + intent classifier (regex-only) + route pra task/scratch existente | 2 dias | nada |
| **F1 — feature mode** | orchestrator com Ralph-replan simples; reusa scratch.planner.generate_plan | 1 semana | F0 |
| **F2 — cost governor** | CostGovernor + hooks em providers.* + --max-cost flag | 3 dias | F0 |
| **F3 — sprint mode** | sprint_loader + scope=sprint orchestration; reusa F1 | 1 semana | F1 + F2 |
| **F4 — DoD gates** | .specs/workflow/DOD.md parser + multi-gate exit | 4 dias | F3 |
| **F5 — bench** | head-to-head bench: cli+ag puro vs Ralph composto vs Codex `/goal` num sprint controlado | 1 semana | F3 |

Total: ~5 semanas pra v0.5 do `simplicio-py run`.

---

## 8. Decisões abertas

1. **Intent classifier**: regex-only ou LLM-assisted? Regex é mais determinístico e barato; LLM-assisted pega mais nuance mas adiciona 1 call. **Proposta**: regex primeiro, LLM fallback se ambíguo (`confidence < 0.7`).
2. **Replan via planner ou via doer?** Planner é frontier (DeepSeek-V4), doer é barato (Coder-Next). Replan exige raciocínio sobre arquitetura → **planner**.
3. **Sprint mode rodando em background ou foreground?** Pra sprint de 6h, foreground é insano. **Proposta**: sprint mode roda como daemon (`simplicio-py run --detach`), state salvo, `simplicio-py status` mostra progresso, log streamável.
4. **Como sprint mode lida com tasks que precisam de input humano** (ex: "decida entre opção A ou B")? **Proposta**: task pode declarar `requires_human: true` no plan; orchestrator pausa, salva state, pinga via webhook se configurado.
5. **Composição com .agents/ existente** (ralph-loop, tdd, reviewer, architect)? Eles são pre-existentes. **Proposta**: cada scope pode invocar agents via skill router — `--use-agents reviewer,tdd` agnóstico do scope.

---

## 9. Anti-padrões cravados

- **Não fazer detection LLM-only**: ambíguo demais, vira black-box. Regex + flags explícitos primeiro.
- **Não rodar sprint sem cost cap**: regra dura, sem `--max-cost` o sprint mode recusa start.
- **Não silenciar quando replanner não converge**: depois de 3 replan attempts, abortar com mensagem clara (não loop infinito).
- **Não misturar scratch + run**: scratch tem premissas diferentes (repo vazio), continua entry-point separado.
- **Não esquecer custo do replan**: replan = mais 1 planner call. Cost governor tem que considerar.

---

## 10. O que isso muda no posicionamento

| pitch antes | pitch depois |
|---|---|
| "simplicio-py task — verify-loop pra editar 1 arquivo" | "simplicio-py run — task / feature / sprint, mesmo CLI, cost-bounded" |
| "compete com Codex CLI, Claude Code" | "stack que vai do primitivo atômico ao orchestrator de sprint, escolhendo escala automaticamente" |
| "use simplicio quando souber o que quer editar" | "use simplicio quando souber o objetivo — ele descobre o escopo" |

---

## 11. Próximo passo

Abrir issue #38 (ou próximo) no `simplicio-dev-cli` com este markdown como body, label `tracking + roadmap`. Cada fase F0–F5 vira sub-issue. RFC fechado quando F0 + F1 estiverem implementados (suficiente pra task/feature em produção).

Issue body link:
[bench/UNIFIED_RUN_ARCHITECTURE.md](./UNIFIED_RUN_ARCHITECTURE.md)

---

## Histórico

- 2026-05-30 — design inicial em resposta à direção "quero o melhor dos dois — tasks vagas + features + sprints inteiras".

# Squads v2: três regras (#1504, parte de #1502)

O `/simplicio-loop` divide o trabalho em squads (1 coordenador + até 4 workers). A v2 acrescenta três regras determinísticas, cada uma em um módulo pequeno e sem chamada a modelo. O `plan_squads` (#1502) chama só a regra 3 (`contracts_for`) e devolve os contratos no plano; as regras 1 e 2 (`route`, `plan_train`/`run_train`) são chamadas à parte pelo coordenador geral.

## 1. Modelo pela complexidade (`simplicio_loop/squad_routing.py`)

`route(task)` decide o papel do **primeiro** worker. A tarefa é `execution` (Haiku ou equivalente) só se **todas** as condições valem:

- um único módulo;
- não integra módulos já existentes;
- não mexe em arquivo compartilhado;
- não é de segurança.

Qualquer outro caso é `coordination` (Sonnet ou equivalente). Dois módulos já é `coordination`. `route(task).explain()` lista os motivos. A escada de `escalation.py` continua valendo depois do primeiro worker.

## 2. Merge em lote (`simplicio_loop/merge_train.py`)

- `plan_train(approved_prs, order, max_batch=4)` monta lotes na ordem de merge definida pelo coordenador geral.
- `run_train(batch, test_fn, merge_fn)` integra o lote numa branch temporária e testa **uma vez**. Se passa, faz merge de todos em ordem, sem novo smoke.
- Se falha, faz bisseção: acha o primeiro PR que deixa o lote vermelho em log2(n) testes, marca como culpado, testa o restante **em cima do prefixo bom** e repete; todo teste é cumulativo (bons até aqui + trecho candidato), então o conjunto final foi testado verde como um todo. Nada entra no main antes de isolar os culpados; depois entram só os PRs bons, em ordem.
- O relatório traz `merged`, `failed`, `bisect_steps` e `wall_ms`. Nunca há force-push.

## 3. Interfaces primeiro (`simplicio_loop/squad_contracts.py`)

`plan_squads` deriva as arestas das dependências declaradas entre issues (`depends_on`, ou "depends on / depende de / parte de #N" no corpo): uma issue que depende de uma issue de **outro** squad é a aresta (squad produtor, squad consumidor). Cada par distinto sai como um contrato em `SquadPlan.contracts` (e em `contracts` no JSON de `plan --json`: produtor, consumidor, `module_path`, `test_path`, `signature`, `function`; o corpo do teste não vai no JSON). Dependência dentro do mesmo squad, ou ausência de dependência, não gera contrato. O `schema` continua `simplicio.squad-plan/v1` (campo aditivo).

O plano só **descreve** os contratos; ele não escreve nada em disco. Ainda não há chamada automática que grave os stubs no repositório antes de os workers começarem: hoje o coordenador geral chama `write_contracts(repo, plan.contracts)` à mão. Para arestas com assinatura própria, chame `contracts_for(edges)` direto.

`write_contracts(repo, contracts)` cria, no repositório alvo, o stub (a função levanta `NotImplementedError("contract: <squad>")`) e o teste ao lado dele, em `dest` (padrão `.simplicio-loop/contracts/`, configurável em `contracts_for(edges, dest=...)`; nunca dentro do pacote distribuído). Arquivos existentes nunca são sobrescritos. O squad consumidor codifica contra a assinatura; o produtor troca o corpo; o teste de contrato fica `xfail` até a implementação existir.

## 4. Quem aprova (`squads.squad_gate`, #1534)

O gate aceita `APROVADO PELO SQUAD` só se o **autor** do comentário for autorizado, além de o comentário ser mais novo que o último commit que não seja merge limpo da base. A autorização vem de quem chama; o padrão é **fail closed**:

- `squad_gate(pr, approvers=None, trusted_associations=())`: `approvers` é o conjunto de logins (sem diferenciar maiúsculas de minúsculas) que podem aprovar. `None` ou vazio, sem `trusted_associations`, rejeita toda aprovação (`reason: unauthorized_approval`).
- `trusted_associations` aceita `OWNER`, `MEMBER` e `COLLABORATOR` (o `authorAssociation` do comentário). Qualquer outro valor levanta `ValueError`. É opt-in: sem ele a associação não conta.
- Comentário sem autor, de autor não autorizado ou que só cita a frase (`> APROVADO PELO SQUAD`) é ignorado; ele não aprova e também não esconde a aprovação de um autor autorizado.
- Watcher 24/7: usa só o próprio login `gh` (`gh api user --jq .login`, uma vez por tick e só com `SIMPLICIO_247_AUTO_MERGE=1`); se o login não vier, nada é aprovado.
- CLI: `simplicio-loop squads gate --pr N --repo R --approver LOGIN [--approver ...] [--trusted-association MEMBER] --json`. Sem `--approver` nem `--trusted-association` sai com código 1 e `unauthorized_approval`.

## 5. Taxa de escalação e espera por dependência (`simplicio_loop/squad_metrics.py`, #1549)

Duas métricas que o repositório local não mede e que o comparativo "antes × depois" da v2 precisa: **quantas tarefas subiram de papel** e **quanto uma tarefa esperou o merge da sua dependência**. O watcher só **registra**; nenhuma regra muda por causa delas. Só entram valores medidos: o que não foi observado fica `null` com `proof_kind: UNVERIFIED` e o motivo, nunca uma estimativa.

### O que é registrado por tarefa

Cada task de worker do `simplicio.execution-report/v1` do squad (`<state_dir>/squads/.simplicio-loop/runtime/execution-reports/<run_id>.json`) ganha `squad_metrics`. O mesmo registro, mais o campo `issue`, vai em `status.json` → `squads.<repo>.task_metrics`, e o resumo do tick em `squads.<repo>.metrics`.

| Campo | Significado |
|-------|-------------|
| `initial_role`, `final_role` | papel do primeiro e do último passo que rodou de fato (os passos do worker, não a previsão do roteador) |
| `escalations` | uma entrada por subida de papel: `from`, `to`, `reason` (por que o passo anterior falhou, sempre um código curto: o `reason_code` do planejador como `bad_plan`, `verify_failed`, `verify_not_reported` quando o turbo aplicou mas nenhum verify verde voltou, ou `apply_<status>` com o status do turbo, `apply_unknown` se não for uma palavra curta) e `attempt` (o passo, a partir de 1, em que o novo papel rodou). Repetir o mesmo papel não é escalada. |
| `depends_on` | issues do mesmo lote de que esta depende (as mesmas arestas da ordem de merge) |
| `dependency_wait_s` | segundos entre o PR da tarefa ficar **pronto** (o squad postou `APROVADO PELO SQUAD`) e o merge da **última** dependência ser **observado** (`gh pr merge` com sucesso), no relógio monotônico. `0.0` medido quando não há dependência, ou quando a dependência já tinha entrado. |
| `final_outcome` | como a tarefa terminou, como o fluxo viu. `ok`: o worker terminou e abriu PR. `failed`: a escada acabou sem plano verificado, ou o worker caiu depois de rodar passos. `no_pr`: o worker terminou e nenhum PR saiu (sem diff, uma etapa bloqueou o PR, ou o push ou o `gh pr create` falhou). `null` quando não foi observado. |
| `proof_kind` | `{"escalations": ..., "dependency_wait": ..., "final_outcome": ...}`, cada um `measured` ou `UNVERIFIED` |
| `unverified` | o motivo de cada parte `UNVERIFIED` |

Quando é `UNVERIFIED` (e por isso fica fora de todo denominador):

- `no_steps_recorded`: nenhum passo rodou. É o caso do executor `openrouter` (não tem escada). É também o caso da tarefa que falhou antes do primeiro passo (por exemplo, o pedido do turbo falhou). É o caso da que nem chegou a rodar (lease de outro, precisa de humano). Não vira zero escalada. A tarefa que rodou passos e depois falhou, ou terminou sem PR, **é medida** (`final_outcome` `failed` ou `no_pr`).
- `outcome_not_observed` (em `unverified.final_outcome`): o fluxo não viu como a tarefa terminou. Nunca vira `ok`.
- `task_never_ready`: a tarefa tem dependência, mas o squad não aprovou o PR dela.
- `dependency_merge_not_observed: #N`: a dependência não teve merge observado neste tick (por exemplo, sem `SIMPLICIO_247_AUTO_MERGE=1`, `gate_blocked` ou `failed`).
- `metrics_error`: o próprio registro falhou. É fail-open: nenhum erro do registro muda quais PRs são aprovados ou mergeados, nem impede o tick de terminar; a tarefa só fica sem medida.

Limites conhecidos: a dependência só conta se está no mesmo lote do tick (a mesma regra do `plan_squads`); um merge feito em outro tick ou à mão não é observado e a espera fica `UNVERIFIED`. O relógio é `time.monotonic()` do processo do watcher.

Tarefa que falhou ou ficou sem PR (#1565): antes, o `run_exec` só devolvia os passos quando o worker terminava bem. Por isso a taxa de escalação cobria só as tarefas concluídas. Agora o worker que subiu de papel e depois falhou, ou terminou sem PR, é registrado com os seus passos e o seu `final_outcome`. Um registro é uma tentativa em um tick. A tarefa que falha em um tick e passa no seguinte aparece nos reports dos dois.

### Resumo e CLI

`squad_metrics.summarize(reports)` (puro) e `simplicio-loop squads metrics --reports <diretório|arquivos...> --json` agregam muitos reports. Um diretório é varrido por `*.json`, `latest.json` é ignorado (é cópia do último) e a mesma `run_id` conta uma vez; arquivo que não é `execution-report/v1` vai em `skipped` com o motivo (também: mais de 8 MiB, não é arquivo comum como FIFO ou dispositivo, link simbólico achado na varredura, JSON aninhado demais, `run_id` que não é texto); um arquivo ruim nunca derruba os outros. Espera negativa, infinita, `NaN` ou absurda (mais de 10^9 s) não é medida: a tarefa vira `UNVERIFIED`. Sem nenhum report, sai com código 2 e `status: BLOCKED` (com o `skipped`). `--compare` recusa (código 2) um resumo editado à mão com campo que não seja `null` ou número plausível.

| Campo do JSON | Significado |
|---------------|-------------|
| `reports`, `tasks`, `issues` | quantos reports, quantas tarefas com registro e quais (`repo#N`) |
| `escalation_n` | tarefas com escalada **medida**: é o denominador da taxa |
| `escalated`, `escalation_rate` | quantas subiram de papel e `escalated / escalation_n` (4 casas, `null` se `escalation_n` é 0). Cobre todos os resultados, também `failed` e `no_pr`. |
| `escalation_unverified` | tarefas fora da taxa por falta de dado |
| `by_initial_role` | `n`, `escalated` e taxa por papel inicial |
| `escalations_by_transition` | contagem por subida, por exemplo `execution->coordination` |
| `by_final_outcome` | a mesma taxa por resultado: `ok`, `failed` e `no_pr` (sempre presentes), cada um com `n`, `escalated` e `escalation_rate` (`null` se `n` é 0). A linha `unknown` só existe se algum registro com escalada medida não tem resultado observado. A soma dos `n` é `escalation_n`. A linha `ok` é a definição antiga (só tarefas concluídas). |
| `mode` | o modo dos reports: `baseline`, `v2`, `mixed` (reports dos dois modos no mesmo conjunto) ou `null` (nenhum report diz o modo). Só report com tarefas de squad conta. |
| `modes` | quantos reports por modo (`unknown` para o report sem modo) |
| `dependency_wait_n` | tarefas **com** dependência e espera medida: é a amostra dos percentis |
| `no_dependency_tasks` | tarefas sem dependência (espera 0 medida, fora da amostra) |
| `dependency_wait_unverified` | tarefas com espera `UNVERIFIED` |
| `dependency_wait_p50_s`, `_p95_s`, `_max_s` | percentis por **posto mais próximo** (sempre um valor observado, sem interpolar) |

Amostra pequena: o `n` vem sempre junto do número. Com `n` de 1 a 3, p50, p95 e max são o mesmo valor ou quase; não leia isso como tendência.

### Como coletar o "antes" e o "depois"

Nenhum dos dois é rodado por este PR: o comparativo real exige um drain de verdade e está **UNVERIFIED** até lá.

1. Escolha o conjunto de issues e use **o mesmo** (ou o mais parecido possível) nos dois lados. Os dois lados precisam rodar um build que tenha este registro; um report antigo, sem `squad_metrics`, não tem como entrar na conta (conta zero tarefas).
2. **Antes** = `SIMPLICIO_247_SQUADS_BASELINE=1` (exatamente `1`). **Depois** = o padrão (v2). A chave desliga só três regras da v2. Primeira, o roteamento por complexidade: todo worker começa em `execution`. Segunda, o lote de merge: 1 PR por trem, pelo mesmo `merge_train`. Terceira, os contratos entre squads: o plano não traz nenhum. Squads, posse de arquivos, ordem por dependência, revisão do squad, `squad_gate` com o login do watcher, `--match-head-commit` e o lock do repositório ficam como estão. A chave **nunca liga o merge e nunca afrouxa uma aprovação**. O merge continua exigindo `SIMPLICIO_247_AUTO_MERGE=1`. O modo vai em `status.json` → `squads.<repo>.mode` e em `mode` no report do tick.
3. Use `SIMPLICIO_247_AUTO_MERGE=1` nos dois lados. Sem merge, a espera por dependência fica `UNVERIFIED`. Use o executor `exec`, porque o `openrouter` não registra passos. Rode o watcher com **uma pasta de estado por lado**. Cada report guarda o seu modo. Uma pasta com os dois modos vira `mixed`, que o `--compare` recusa.

```bash
# antes: baseline
SIMPLICIO_247_AUTO_MERGE=1 SIMPLICIO_247_SQUADS_BASELINE=1 simplicio-loop watch247 --once --state-dir antes
# depois: v2 (sem a chave)
SIMPLICIO_247_AUTO_MERGE=1 simplicio-loop watch247 --once --state-dir depois

simplicio-loop squads metrics --reports antes/squads --json > before.json
simplicio-loop squads metrics --reports depois/squads --json > after.json
simplicio-loop squads metrics --compare before.json after.json          # tabela lado a lado
simplicio-loop squads metrics --compare before.json after.json --json   # o mesmo, em JSON (before_mode, after_mode, rows, warnings)
```

`--compare` rotula cada lado com o seu modo (`Before [baseline]` e `After [v2]` na tabela, `before_mode` e `after_mode` no JSON). Ele **recusa** (código 2, `BLOCKED`) duas rodadas do mesmo modo e um lado `mixed`. Ele só avisa quando um lado não tem modo gravado (`UNVERIFIED`) e quando a ordem é v2 antes de baseline.

Ele mostra os números dos dois lados com o `n` de cada um e **só avisa** sobre três coisas. A primeira é `n` menor que 10, por métrica e por lado. A segunda são conjuntos de issues diferentes (quantas só no antes, só no depois, em comum). A terceira são as tarefas `UNVERIFIED` excluídas. Ele não calcula diferença e não afirma significância. Cole na issue #1549 as duas saídas e os avisos como vierem.

### Limites desta comparação

- A espera por dependência só é observada com `SIMPLICIO_247_AUTO_MERGE=1` e quando a dependência está no mesmo lote do tick. Um merge feito em outro tick ou à mão não conta.
- Com `n` pequeno (menos de 10 por métrica e por lado) o `--compare` avisa. Não leia o número como tendência.
- O baseline é o mesmo código com três regras desligadas, não o código de antes da v2. Ele começa os workers em `execution`.
- Os dois lados precisam do mesmo conjunto de issues. Se diferem, aparece o aviso `task sets differ`.
- Um registro é uma tentativa em um tick, não uma tarefa única.
- Com o executor `openrouter` não há passos: a escalação fica `UNVERIFIED`.
- O comparativo real **não foi rodado** e continua **UNVERIFIED** até alguém rodar os dois drains.

## Uso no `/simplicio-loop`

1. O coordenador geral (planning) chama `plan_squads`: squads, ordem de merge e contratos das arestas de dependência.
2. `write_contracts(repo, plan.contracts)` grava os stubs (passo manual hoje); eles entram no main antes dos squads.
3. Para cada tarefa, `route` escolhe o papel do primeiro worker.
4. Os PRs aprovados pelos squads vão para `plan_train`; `run_train` faz o merge em lotes.

## Sizing (automatic squad count)

The loop selects the number of squads itself. It runs fast without overloading the machine. Call `simplicio-loop squads plan` with option `--squads auto` (the default). The 24/7 watcher probes once each tick. The JSON from `squads plan` has a `capacity` block. The block lists numbers and `reasons`.

The plan still lists all squads. The `capacity` block tells how many squads and workers run at the same time. When a worker ends, start the next one. In the watcher, the same number is the batch size of the tick, so one issue is no longer the default limit.

### Demand

Demand is the widest dependency level of the issues. Issues that share a file path do not run together. Count only one of them. A chain of six dependent issues gives width one.

### Supply

The machine probe collects cores, load average (one, five and fifteen minutes), free memory and free disk. Each limit gives a worker count. The minimum is one worker.

- **cpu**: floor(0.8 × cores)
- **load**: floor(0.8 × cores - max(load 1 min, load 5 min))
- **memory**: floor((available memory - 512 MiB) ÷ 1.25 GiB). Use 1.25 GiB per worker as an estimate.
- **disk**: floor((free disk - 2 GiB) ÷ 1 GiB). Use 1 GiB per worker as an estimate. If free disk falls below the 2 GiB floor, the result is one. The reason names the disk limit.
- **budget**: what remains of the watcher daily cap (issues and PRs). It may be zero.

### Result

Total workers equals the smallest of demand and the supply limits. The `limited_by` field names the smallest one. Choose from: demand, cpu, load, memory, disk, budget, or override.

Calculate `workers_per_squad` as min(4, total workers). Calculate `squads` as ceil(total workers ÷ workers_per_squad).

Example: three independent issues on an idle 64-core host yield one squad of three workers. Demand limits the result.

### Unknown value

If the probe cannot measure a value, the loop uses one worker. Set `proof_kind` to UNVERIFIED with the reason. The loop never assumes unlimited capacity. Measured values set `proof_kind` to MEASURED.

### Override

Pass `--squads N` or set `SIMPLICIO_SQUADS=N`. This overrides machine limits. N must be one or more. Zero is not valid. The flag wins over the variable. The loop never makes more squads than issues that can run together.

Set `SIMPLICIO_PRISM_SLOTS` or `SIMPLICIO_LOOP_OPERATOR_WORKERS` to a value that the economy profile did not set. This fixes the worker count. The economy profile exports its own value to every session. That value is not an override, and the machine limits still decide.

In the watcher, `SIMPLICIO_247_CONCURRENCY` is the override. The daily budget always caps an override.

### Between waves

`resize` shrinks the plan at once when the load rises. It grows the plan only after the load remains low for one full wave. One full wave is two samples in a row. The `recheck_after_s` field tells when to measure again.

### Merge rules

Sizing decides only how many squads and workers run at the same time. It never decides what may merge. The squad gate, `SIMPLICIO_247_AUTO_MERGE` setting, merge train and repo lock remain unchanged.

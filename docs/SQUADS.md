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

O gate aceita `REVISÃO AUTOMÁTICA: APROVADA (nível N)` só se o **autor** do comentário for autorizado, além de o comentário ser mais novo que o último commit que não seja merge limpo da base. A autorização vem de quem chama; o padrão é **fail closed**:

- `squad_gate(pr, approvers=None, trusted_associations=())`: `approvers` é o conjunto de logins (sem diferenciar maiúsculas de minúsculas) que podem aprovar. `None` ou vazio, sem `trusted_associations`, rejeita toda aprovação (`reason: unauthorized_approval`).
- `trusted_associations` aceita `OWNER`, `MEMBER` e `COLLABORATOR` (o `authorAssociation` do comentário). Qualquer outro valor levanta `ValueError`. É opt-in: sem ele a associação não conta.
- Comentário sem autor, de autor não autorizado ou que só cita a frase (`> REVISÃO AUTOMÁTICA: APROVADA (nível 1)`) é ignorado; ele não aprova e também não esconde a aprovação de um autor autorizado.
- Watcher 24/7: usa só o próprio login `gh` (`gh api user --jq .login`, uma vez por tick e só com `SIMPLICIO_247_AUTO_MERGE=1`); se o login não vier, nada é aprovado.
- CLI: `simplicio-loop squads gate --pr N --repo R --approver LOGIN [--approver ...] [--trusted-association MEMBER] --json`. Sem `--approver` nem `--trusted-association` sai com código 1 e `unauthorized_approval`.

## 4a. Portão automático de revisão (`simplicio_loop/review_gate/`, #1649)

O coordenador do squad não aprova mais por "o verify do worker passou". Antes de postar a aprovação ele roda o portão, que reprova com razão determinística. A aprovação do squad que só olhava `check.py --tests-only` e a posse de arquivos deixou passar um PR com 11 testes que passam em `main` sem a mudança (#1640) e um módulo novo sem chamador (#1641).

| Checagem | O que exige | Reprova quando |
|---|---|---|
| `redgreen` | cada teste novo ou alterado roda em dois worktrees descartáveis: o head (todos passam) e `main` com os testes do head por cima (todos falham) | teste novo passa em `main` sem a mudança (a razão lista o id), teste novo falha no head, mudança de produção sem teste novo. Um teste cujo nome ou docstring diz `characterization` fica isento e é listado |
| `mutation` | amostra determinística (semente = head) de 12 mutantes das linhas de produção adicionadas, feitos pela AST: troca de comparação, `and`/`or`, `True`/`False`, constante inteira, `+`/`-`, `return` vira `None`, condição negada, chamada removida. Nunca muta string, comentário nem docstring, e o mutante precisa compilar | menos de 60% dos mutantes morrem sob os testes do PR (mais os testes existentes que importam o módulo alterado), ou os testes já falham sem mutante (erro, não aprovação), ou não há teste para rodar |
| `usage` | todo símbolo público novo (nível de módulo ou de classe) e todo módulo novo tem um chamador fora dos testes | símbolo ou módulo sem chamador |
| `coverage` | cada critério `- [ ]` da issue casa com um teste novo ou com um arquivo de produção alterado | critério sem cobertura: o PR é parcial, precisa de `Parte de #N` e da lista do que falta |
| `docs` | `ste-lint` das linhas novas não piora. Afirmação nova em doc precisa de teste ou do rótulo `UNVERIFIED` | doc pior ou afirmação sem prova |
| `identity` | o comentário registra autor, revisor automático e revisor independente (papel, modelo, host) | o autor aprova o próprio PR, ou o revisor tem o mesmo papel do autor |

Níveis: **T0** só docs e testes, até 200 linhas adicionadas, **T1** código comum, **T2** segurança (o caminho de código tem `sandbox`, `daemon`, `token`, `uninstall`, `mapper`, `login`, `secret` e similares). O comentário é `REVISÃO AUTOMÁTICA: APROVADA (nível N)` ou `REVISÃO AUTOMÁTICA: REPROVADA` com a causa de cada checagem. Em T2 o portão sozinho nunca aprova: `squads.squad_gate` exige também um comentário `REVISAO INDEPENDENTE: APROVADA` com as linhas `revisor:`, `papel:`, `modelo:`, `host:` e `head:` (prefixo do head atual), de um autor autorizado, de um agente que não seja o autor nem o portão. O loop, o revisor e o dono comentam com a mesma conta do GitHub: o marcador registra a declaração do revisor, não prova independência (UNVERIFIED).

Uso à mão: `python -m simplicio_loop.review_gate --repo <clone> --pr N --issue M --base <sha> --head <sha> --author ID [--json]` (saída 0 aprovado, 1 reprovado. O relatório JSON fica em `<clone>/.simplicio-loop/review-gate/`). No watcher, `watcher247/squad_review.evaluate` roda o portão no clone dentro do sandbox, e `squad_flow._review` posta o veredito. Um passo que não consegue rodar (por exemplo, o interpretador fora dos binds do sandbox) aparece no PR com a causa e nunca vira aprovação.

Provas medidas nesta máquina (`python -m simplicio_loop.review_gate` sobre os commits de `main`, cada um contra o pai dele):

| Commit | Veredito | Causas medidas | Tempo |
|---|---|---|---|
| `31ff4ce6` (#1640, testes vácuos) | REPROVADA (nível 2) | 3 dos 4 testes novos passam em `main`. `ste-lint` do `INSTALL.md` subiu de 3 para 4. Nível 2 sem revisor independente. 0 de 3 critérios cobertos | 152,6 s |
| `1fb7ce48` (#1641, módulo sem chamador) | REPROVADA (nível 1) | `redirect_target` e `read_private_text` sem chamador fora dos testes. 7 de 12 mutantes mortos. 0 de 2 critérios cobertos | 29,3 s |
| `f42e9e49` (docs de #1647), corpo `Parte de #1601` e lista `Falta` de 6 itens | APROVADA (nível 0) | nenhuma | 3,1 s |
| `cda7e73e` (#1642), corpo `Parte de #1550` e lista `Falta` de 2 itens | APROVADA (nível 1) | nenhuma | 2,8 s |

Limites conhecidos (UNVERIFIED): o nível sai das palavras do caminho dos arquivos, não do assunto do PR. A independência do revisor é a declaração do marcador, não uma prova. A lista `Falta` é conferida só pela contagem de itens `- [ ]`. O tempo da mutação cresce com os testes vizinhos que importam o módulo (139,5 s no #1640). Só Python é mutado.

## 5. Taxa de escalação e espera por dependência (`simplicio_loop/squad_metrics.py`, #1549)

Duas métricas que o repositório local não mede e que o comparativo "antes × depois" da v2 precisa: **quantas tarefas subiram de papel** e **quanto uma tarefa esperou o merge da sua dependência**. O watcher só **registra**; nenhuma regra muda por causa delas. Só entram valores medidos: o que não foi observado fica `null` com `proof_kind: UNVERIFIED` e o motivo, nunca uma estimativa.

### O que é registrado por tarefa

Cada task de worker do `simplicio.execution-report/v1` do squad (`<state_dir>/squads/.simplicio-loop/runtime/execution-reports/<run_id>.json`) ganha `squad_metrics`. O mesmo registro, mais o campo `issue`, vai em `status.json` → `squads.<repo>.task_metrics`, e o resumo do tick em `squads.<repo>.metrics`.

| Campo | Significado |
|-------|-------------|
| `initial_role`, `final_role` | papel do primeiro e do último passo que rodou de fato (os passos do worker, não a previsão do roteador) |
| `escalations` | uma entrada por subida de papel: `from`, `to`, `reason` (por que o passo anterior falhou, sempre um código curto: o `reason_code` do planejador como `bad_plan`, `verify_failed`, `verify_not_reported` quando o turbo aplicou mas nenhum verify verde voltou, ou `apply_<status>` com o status do turbo, `apply_unknown` se não for uma palavra curta) e `attempt` (o passo, a partir de 1, em que o novo papel rodou). Repetir o mesmo papel não é escalada. |
| `depends_on` | issues do mesmo lote de que esta depende (as mesmas arestas da ordem de merge) |
| `dependency_wait_s` | segundos entre o PR da tarefa ficar **pronto** (o squad postou `REVISÃO AUTOMÁTICA: APROVADA (nível N)`) e o merge da **última** dependência ser **observado** (`gh pr merge` com sucesso), no relógio monotônico. `0.0` medido quando não há dependência, ou quando a dependência já tinha entrado. |
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

The plan still lists all squads. The `capacity` block tells how many squads and workers run at the same time. When a worker ends, start the next one. In the watcher, each tick sizes its batch from the supply only. Demand does not limit it. If five issues are in one repo, the tick claims all five. They run one at a time behind the repo lock.

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

Set `SIMPLICIO_PRISM_SLOTS` or `SIMPLICIO_LOOP_OPERATOR_WORKERS` to a value above the static figure of the economy profile. This fixes the worker count. The static figure depends on the cores and the total memory only. The economy profile exports its own value to every session. It lowers that value when free memory is low. A value at or below the static figure is the profile's own value. It is not an override, and the machine limits still decide.

In the watcher, `SIMPLICIO_247_CONCURRENCY` is the override. The daily budget always caps an override. Use a whole number from 1 to 999999 in ASCII digits. An empty value means that the variable is not set. Any other value is invalid, for example `0`, `-1`, `2.0` or `lots`. An invalid value is not an override and does not stop the tick. The automatic sizing decides. The plan gets a `WARN:` reason that names the invalid value.

To run fewer workers than the machine allows, pass `--squads N` with `--max-workers M`. The loop then runs at most N times M workers. For example, `--squads 1 --max-workers 2` runs two workers. The option `--squads 2` alone allows eight workers, because each squad has up to four. A low `SIMPLICIO_PRISM_SLOTS` does not lower the count, as the paragraph above says. In the watcher, set `SIMPLICIO_247_CONCURRENCY=2` to run two workers.

An override can start more workers than the machine allows. The plan then starts its first reason with `WARN:`. The `warnings` list of the `capacity` block has the same warning. `squads plan` prints it to stderr, and the watcher writes it once to the log of each tick. The plan keeps its `limited_by` and `proof_kind` fields. `proof_kind` only tells if the probe measured every value.

### Between waves

`resize` shrinks the plan at once when the load rises. It grows the plan only after the load remains low for one full wave. One full wave is two samples in a row. The `recheck_after_s` field tells when to measure again.

### Merge rules

Sizing decides only how many squads and workers run at the same time. It never decides what may merge. The squad gate, `SIMPLICIO_247_AUTO_MERGE` setting, merge train and repo lock remain unchanged.

## Where the review gate runs a PR's code (#1649)

The automatic review gate runs the tests and the mutants of the PR, which is the PR author's code. It runs them in bwrap (`sandbox.wrap`, through `review_gate/isolation.py`). `sandbox.scrubbed_env` strips the environment (no `GH_TOKEN`, no `keep`) and the HOME stays empty. Nothing of `~/.simplicio` or `~/.config/gh` is visible. Without bwrap the gate rejects the PR with `sandbox_unavailable`. It never runs the code unsandboxed, and `SIMPLICIO_247_ALLOW_UNSANDBOXED` has no effect there.

Residual risk: `sandbox.wrap` does not `--unshare-net`, so the PR code can still reach the network. It holds no secret of the watcher to send. It can send anything it can see inside the jail: the trees of the PR and the read-only system.

The approval of `squad_gate` belongs to the full 40-character oid of the head (`squad-approval:<oid>` in the comment), never to a date. The gate raises its level to the level that the files of the diff need.

## Threat model of the review gate (#1649)

The gate filters pull requests that are vacuous or that add dead code. It expects an author who is honest but lazy. It does not stop an author who writes code to fool it. The human merge, the protected paths and the sandbox are the security boundary.

The gate does not prove these shapes:

- A test module or helper that forces its own result. The gate copies the test modules of the PR to the base tree on purpose, so this code runs on both trees.
- A plugin or an entry point that is present only on the head.

The gate sets the level to T2 for each file that changes how Python or pytest starts. These files are `conftest.py`, the pytest configuration (`pytest.ini`, `pytest.toml`, `pyproject.toml`, `tox.ini`, `setup.cfg`), `sitecustomize.py`, `usercustomize.py`, `*.pth`, `*.egg-info/` and `*.dist-info/`. A test module that sets `pytest_plugins` is T2 too. A T2 PR needs a human reviewer.

Each item of the `Falta` list must name one criterion. The gate rejects an item that names several criteria.

The next step is per-test mutant attribution. Each new test that fails on main must kill at least one mutant of the changed production lines. If it kills none, the author marks it as characterization.

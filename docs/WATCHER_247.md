# Watcher 24/7 (`simplicio_loop.watcher247`)

O servico `simplicio-loop-247` (unit em `packaging/systemd/`) observa issues novas dos repos `simpletibr/simplicio-*` que
habilitaram o loop (`.simplicio/loop.toml`) e abre PRs. Estado, claims e logs ficam em `SIMPLICIO_247_STATE_DIR`.

## Motor único

O watcher é o turbo do simplicio-loop (#1469) com o registro de extensões (`simplicio_loop/watcher247/points/`).
Não há um `runner.py` embutido: o turbo + points é o motor único. Ver `docs/EXTENSION_POINTS_SERVICE.md`.

## Modo host 24/7

O executor padrao e `exec` (`SIMPLICIO_EXECUTOR`, ver `simplicio_loop/executor_select.py`). Um CLI agentico em modo
exec so **planeja**; quem escreve em arquivo e sempre o **dev-cli**, via `simplicio-loop turbo --apply -`.
O `openrouter` nao e mais o caminho padrao: so roda com `SIMPLICIO_EXECUTOR=openrouter` **e** `OPENROUTER_API_KEY`
(uma chave sozinha nao seleciona nada). `SIMPLICIO_EXECUTOR=host` nao serve ao servico (nao ha modelo invocante)
e bloqueia o tick com `executor_host_not_headless`.

Fluxo de cada tick (implementado em `watcher247/tick.py` e `watcher247/host_mode.py`):

1. **Preflight de login.** `exec_auth.check_all` nas familias de `SIMPLICIO_EXEC_FAMILIES` (padrao
   `claude,codex,grok,gemini`). Se nenhuma estiver usável, o tick nao processa nada e `status.json` mostra
   `phase=blocked` e `reason_code=login_missing:<cli>` (ou `cli_missing:<cli>`). So as familias autenticadas entram
   no fallback. Login: `claude auth login`, `codex login`, `grok login` como o usuario do servico; nenhum segredo vai
   para log, comentario ou recibo.
2. **Plano.** `exec_planner.run_planner_with_fallback` roda o CLI em modo somente-plano (sem escrita) com o texto da
   task e o modelo/esforco de `model_roles.resolve(familia, papel)`. Issue nova usa o papel que `squad_routing.route` indica para o worker (`execution`, ou `coordination` se tocar varios
   modulos, arquivo compartilhado ou seguranca; ver "Squads"); `planning` e o topo da escada.
3. **Aplicacao.** O plano JSON entra no stdin de `simplicio-loop turbo --repo <clone> --apply - --verify <testes>`,
   dentro de `sandbox.wrap` e com env filtrado (sem `OPENROUTER_API_KEY`). A abertura do PR depende do verify
   (`verify.decide`), como antes.
4. **Escalada.** Se o apply ou o verify falhar, a escada de `escalation.py` (execution, depois coordination, depois
   planning; execution repete uma vez) escolhe o proximo papel e o planner tenta de novo com a saida da falha, apos
   `git reset --hard` do clone. Teto: `MAX_STEPS` (4) por execucao e os tetos de `EscalationState`
   (`SIMPLICIO_247_ATTEMPT_CEILING_ISSUE` / `_DAY`, `SIMPLICIO_247_TOKEN_CEILING_ISSUE` / `_DAY`). Tokens nao medidos
   (host mode) ficam UNVERIFIED e contam so como tentativas.
5. **Recibo de papel.** Cada etapa grava uma task em `simplicio.execution-report/v1` (no clone,
   `.simplicio-loop/runtime/execution-reports/latest.json`) com `role`, `model`, `effort`, `family` e resultado.
6. **Patrulha de PRs.** Os PRs `loop/issue-N` abertos passam por `watcher_github.patrol_open_prs`. Comentario de
   review, check vermelho ou conflito viram task de correcao no PR existente, com o papel `coordination`
   (e `planning` se falhar). O fix faz push na mesma branch, sem force; o loop nunca faz merge nem fecha PR.

O planner roda por `sandbox.wrap` (o mesmo bwrap do apply) e com `sandbox.scrubbed_env`: so a allowlist do sandbox, `HOME`
e a chave do proprio CLI (`host_mode.FAMILY_ENV`); `OPENROUTER_API_KEY` e outros segredos do servico nunca chegam a ele.
Cada CLI recebe apenas flags de somente-plano (ver `exec_planner.py`). A config de deny do `opencode` fica em
`<state_dir>/opencode/` (o bwrap monta tmpfs em `/tmp` e esconderia o arquivo, rodando o CLI sem as regras de deny) e e
removida ao fim da chamada.

### Login dos CLIs (`watch247 login-check`)

`simplicio-loop watch247 login-check` roda `exec_auth.check_all` nas familias habilitadas e imprime, por CLI, `ok` ou o
comando exato que corrige, por exemplo `sudo -u simplicio-loop -H codex login`. Exit 0 quando todos estao ok, 1 caso
contrario. Nao le nem imprime token. O mesmo estado derruba o tick com `login_missing:<cli>`.

## Squads (`watcher247/squad_flow.py`)

O tick usa o mesmo padrao da skill `/simplicio-loop` (#1505). Nada disso muda a concorrencia: o lote continua limitado por
`SIMPLICIO_247_CONCURRENCY`, pelo teto diario (`budget.py`) e pelo lock por repo; escritas no clone sao seriais.

1. **Coordenador geral** (`planning`). As issues novas admitidas de cada repo viram `squads.plan_squads`: squads de ate 4
   workers e 1 coordenador (`coordination`) cada, dono de arquivo por caminho citado na issue, ordem de merge por
   dependencia. Fixes de review (PR ja aberto) ficam fora dos squads.
2. **Workers.** Cada issue segue o fluxo de host mode acima, comecando no papel de `squad_routing.route`. Sandbox,
   `scrubbed_env` e a escada de escalonamento (2 falhas sobem um papel) valem para todos, sem mudanca.
3. **Revisao do squad.** Para cada PR aberto o coordenador do squad confere (a) o verify do worker foi
   `MEASURED|verify_passed` e (b) nenhum arquivo alterado e compartilhado ou de outro squad. Aprovado: posta
   `APROVADO PELO SQUAD` no PR com `pr_evidence.publish_comment` (um comentario por commit de head, para o horario do
   comentario ser sempre mais novo que o commit). Reprovado: nada e postado e o motivo vai para `status.json`.
4. **Merge: desligado por padrao.** Sem `SIMPLICIO_247_AUTO_MERGE=1` o watcher para em "aprovado" e nunca faz merge
   (#1434). Com a variavel, cada PR aprovado passa por `squads.squad_gate` (aprovacao mais nova que o ultimo commit) e os
   que passam entram em `merge_train` em lotes de ate 4, na ordem do plano: uma branch temporaria `loop/merge-train`
   integra os PRs sobre `main`, roda os testes do repo uma vez (no sandbox) e, se ficar vermelho, faz a bisseccao; so o que
   ficou verde recebe `gh pr merge --squash`. Sem force-push.
5. **Recibo.** Um `simplicio.execution-report/v1` por tick em
   `<state_dir>/squads/.simplicio-loop/runtime/execution-reports/latest.json`: uma task por agente (coordenador geral,
   coordenador de cada squad, cada worker) com `agent.role`, `agent.model` e `agent.effort`; o worker mostra o ultimo
   papel que realmente rodou (apos escalada). `consolidated.tasks_by_role` conta por papel.

Limites de seguranca: `squad_gate` confere a frase e os horarios, nao o autor do comentario (um so usuario `gh`). Por isso
so entram no merge os PRs que a revisao do proprio watcher aprovou no mesmo tick, e cada `gh pr merge` usa
`--match-head-commit` com o head revisado e testado. Caminhos citados na issue entram so como padrao de posse (nunca sao
abertos) e `..`, absolutos e `~` sao descartados. Um ciclo de `depende de #N` entre issues nao para o tick: o plano sai sem a
ordem declarada.

`status.json` ganha `squads.<repo>`: `squads` (id, coordenador, workers, issues), `approved`, `rejected`, `merge`
(`disabled` ou `enabled`) e, com merge ligado, `merged`, `failed` e `gate_blocked` (numeros de PR).

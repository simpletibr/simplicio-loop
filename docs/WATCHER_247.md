# Watcher 24/7 (`simplicio_loop.watcher247`)

O servico `simplicio-loop-247` (unit em `packaging/systemd/`) observa issues novas dos repos `simpletibr/simplicio-*` que
habilitaram o loop (`.simplicio/loop.toml`) e abre PRs. Estado, claims e logs ficam em `SIMPLICIO_247_STATE_DIR`.

## Primeira execução (credenciais)

O watcher não traz credenciais embutidas. Na primeira execução, `simplicio-loop watch247 setup` coleta duas informações
do operador: o e-mail da conta Simplicio (visível) e um token de API do GitHub (entrada oculta, nunca ecoada).

- **Modo interativo** (terminal disponível, padrão):
  ```
  simplicio-loop watch247 setup
  ```
  Pede o e-mail e depois o token sem eco.

- **Modo não-interativo** (automação, sem terminal):
  ```
  read -rs -p 'GitHub token: ' GHT; echo
  printf '%s' "$GHT" | simplicio-loop watch247 setup --email user@example.com --github-token-stdin
  unset GHT
  ```
  O token entra via stdin, nunca em argv (visível em `ps`); `--github-token <valor>` é recusado com exit 2 e o valor
  não é repetido na mensagem. Sem terminal e sem `--github-token-stdin`, setup recusa com exit 2.
- **Só a conta** (depois do login, sem pedir o token de novo): `simplicio-loop watch247 setup --check`. Usa o e-mail
  gravado em `account.json` (ou `--email`).

Como root, com o arquivo de env do serviço, aponte `SIMPLICIO_247_LOGIN` para o `login.json` do usuário do serviço
(`/home/simplicio-loop/.simplicio/login.json`); o setup mantém o dono desse arquivo se um refresh o reescrever.

**Armazenamento e validação do token:**
- Gravado como `GH_TOKEN=...` em `SIMPLICIO_247_ENV_FILE` (padrão `/etc/simplicio-loop-247.env`), modo 600, escrita atômica.
- Recusa se o arquivo existe com modo 640 ou mais permissivo (imprime `chmod 600 <path>`); recusa symlink.
- Valida o token com `gh api user` (token passado apenas na env do child). Imprime o login e os escopos.
- Avisa (WARN, não falha) se os escopos incluem `admin:*`, `delete_repo`, `workflow`, `write:packages`, `delete:packages` ou `codespace`; recomenda token fine-grained limitado aos repos de interesse (Contents, Issues, Pull requests: read and write).

**Conta Simplicio:**
- Setup grava o e-mail (não é segredo) em `<state_dir>/account.json` (modo 600).
- Sem `~/.simplicio/login.json` o tick fica ocioso com `phase=setup_required`, `reason_code=login_missing`. Setup imprime:
  ```
  sudo -u simplicio-loop -H simplicio login google
  ```
  E verifica a assinatura. Reason codes: `ok`, `login_missing`, `subscription_required`, `refresh_failed`, `entitlement_required`, `validate_unreachable`, `account_mismatch`.
  Com `account_mismatch`, o login.json pertence a outra conta: `sudo -u simplicio-loop -H simplicio logout` e faça login novamente.

**Saída do setup:**
- Exit 0: tudo pronto (reason `ok`).
- Exit 1: passo ainda aberto (token rejeitado, login pendente, assinatura inativa).
- Exit 2: recusado (entrada ruim, arquivo inseguro; nada foi alterado).

Após gravação bem-sucedida do token, reinicie o serviço: `systemctl restart simplicio-loop-247`.

**Idle durante setup:**
Sem `GH_TOKEN` (ou `GITHUB_TOKEN`) ou sem `login.json`, o tick não chama o GitHub nem processa nada, e o processo não
cai (sem loop de crash com `Restart=always`). O `status.json` mostra o motivo e o comando exato:
- Sem token: `phase=setup_required`, `reason_code=github_token_missing`, `command="simplicio-loop watch247 setup"`.
- Sem login: `phase=setup_required`, `reason_code=login_missing`, o mesmo `command`.
- Outras falhas da assinatura continuam em `phase=subscription_required`.

O login do `gh` guardado em `~/.config/gh` não vale mais para o serviço: o token precisa estar no ambiente.
`watch247 --once --dry-run` sem token só registra `setup required` no log e não grava nada.

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

## Isolamento do sandbox (`watcher247/sandbox.py`, issue #1563)

Todo subprocesso do watcher (planner, `turbo --apply`, git, testes do merge train, pontos de extensão) roda sob `bwrap`
(`sandbox.wrap`) com o env filtrado por `scrubbed_env`. O `scrubbed_env` só limpa o env do **filho**; o env do **pai** é
coberto pelo namespace de pid.

**Escondido do processo no sandbox**
- O `EnvironmentFile` do serviço (`GH_TOKEN`, `OPENROUTER_API_KEY`, ...) vive em `/proc/<pid do watcher>/environ`, legível por
  qualquer processo do mesmo uid. `sandbox.wrap` passa `--unshare-pid` e remonta `/proc` (`--proc /proc`) para o novo
  namespace: o pid do watcher não é listado e `/proc/<pid>/{environ,cmdline,maps,status}` não abrem. O filho é o pid 2 (o
  `bwrap` é o pid 1), então `/proc/1/environ` é o env já filtrado.
- Efeito medido do mesmo flag: o timeout (`proc.run`, `exec_planner`) e o `SIGKILL` do watcher agora derrubam a árvore
  inteira. Antes, o comando ficava em outra sessão/grupo que o `killpg` do watcher não alcança (`--die-with-parent` não o
  derrubava) e os netos sobreviviam como órfãos; como o `Process.wait()` do Python 3.14 só retorna quando os pipes fecham (medido), o
  `proc.run` com timeout ficava preso enquanto um neto vivo segurasse o pipe.
- Filesystem somente leitura (exceto o clone e o state dir), `/tmp` privado, `--die-with-parent`, `--new-session`.

**Continua visível (decisão e limites conhecidos)**

| Canal | Estado | Motivo |
|-------|--------|--------|
| `/proc/<pid do watcher>/environ`, `cmdline`, `maps`, `status` | oculto | namespace de pid |
| `/proc/self/*`, `/proc/1/*` (o bwrap) | legível | é o env filtrado do próprio filho |
| `HOME` do usuário do serviço (`~/.claude`, `~/.codex`, `~/.simplicio/login.json`, ...) | **legível** | os CLIs exec leem o próprio login; o `--ro-bind / /` não separa `HOME` por família, então um planner pode ler o login de outro CLI |
| `/etc/simplicio-loop-247.env` | legível só se o usuário do serviço for o dono | o `setup` grava modo 600; mantenha `root:root` (o systemd lê como root) |
| rede (`/proc/net/*`, localhost, sockets abstratos) | compartilhada | sem `--unshare-net`: o planner precisa da rede do provedor |
| `/proc/self/mountinfo`, `cpuinfo`, `meminfo` | legível | informação do host sem segredo |
| `/run` (sockets do systemd/dbus acessíveis ao uid) | legível | `--ro-bind / /`; não coberto por este issue |

O teste `tests/watcher247/test_sandbox_proc.py` usa o `bwrap` real (pula sem `bwrap` ou sem user namespaces): um "watcher"
com um segredo falso no próprio env roda um comando por `sandbox.wrap`; o comando não lê o `environ`, não lista o pid e o
controle sem `--unshare-pid` vaza o segredo (prova de que a sonda enxerga o canal).

**`SystemCallFilter` e a unit.** `--unshare-pid` é `clone(CLONE_NEWPID)`. O `strace -f` do `bwrap` com e sem o flag mostra os
mesmos 50 syscalls; só `mount`, `pivot_root` e `umount2` ficam fora de `@system-service`, e o `@mount` da unit os cobre.
`clone`, `clone3`, `unshare` e `setns` já estão em `@system-service` (o filtro do systemd não olha os argumentos de `clone`).
Medido com `systemd-run` (systemd 259, bubblewrap 0.11.1, `User=nobody`, mais as diretivas de sandbox da unit): a tabela está
em `packaging/systemd/README.md`. Achado dessa medição: com `ProtectKernelTunables=yes` o bwrap não root falha com `Can't
mount proc on /newroot/proc: Operation not permitted` quando usa `--unshare-pid`; por isso a unit não traz mais essa
diretiva (o serviço é não root, com `CapabilityBoundingSet=` vazio, e não escreve em `/proc/sys` de qualquer forma). O mesmo
sintoma aparece em contêiner com `/proc` mascarado.

**UNVERIFIED:** a unit real sob o gerenciador do sistema como `User=simplicio-loop` (só unidades transitórias de curta duração,
sem instalar nada); a leitura de `environ` por uid não root em host **sem** o confinamento AppArmor `bwrap//&unpriv_bwrap` (no
host medido o processo do sandbox já não lê `environ`/`maps`, mas lista o pid e lê `cmdline` e `status`; a regra não foi
inspecionada; como root o vazamento de `environ` foi reproduzido sem o flag); outras distribuições e kernels sem user namespaces.

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
4a. **PR como draft (#1589).** Sem `SIMPLICIO_247_PR_DRAFT=1` o watcher abre o PR pronto (padrao).
   Com a variavel exatamente `1`, a criacao da PR passa `--draft` ao `gh pr create`: o PR fica rascunho ate alguem
   executar `gh pr ready` antes do merge. Com PR draft, `SIMPLICIO_247_AUTO_MERGE=1` exigira `gh pr ready` antes
   (UNVERIFIED: nao testado aqui; a validacao fica com o operador).
5. **Recibo.** Um `simplicio.execution-report/v1` por tick em
   `<state_dir>/squads/.simplicio-loop/runtime/execution-reports/latest.json`: uma task por agente (coordenador geral,
   coordenador de cada squad, cada worker) com `agent.role`, `agent.model` e `agent.effort`; o worker mostra o ultimo
   papel que realmente rodou (apos escalada). `consolidated.tasks_by_role` conta por papel.

Limites de seguranca: `squad_gate` so aceita `APROVADO PELO SQUAD` escrito por um autor autorizado (#1534): o `author.login` do
comentario (de `gh pr view --json comments`) precisa ser o login `gh` do proprio watcher (`gh api user --jq .login`, uma
chamada por tick e so quando o merge esta ligado). Sem login conhecido o gate nega tudo (fail closed), e o comentario de
qualquer outra pessoa, mesmo com a frase exata, e ignorado e nao esconde a aprovacao real. Alem disso so entram no merge os
PRs que a revisao do proprio watcher aprovou no mesmo tick, e cada `gh pr merge` usa `--match-head-commit` com o head
revisado e testado. Caminhos citados na issue entram so como padrao de posse (nunca sao
abertos) e `..`, absolutos e `~` sao descartados. Um ciclo de `depende de #N` entre issues nao para o tick: o plano sai sem a
ordem declarada.

`status.json` ganha `squads.<repo>`: `squads` (id, coordenador, workers, issues), `approved`, `rejected`, `merge`
(`disabled` ou `enabled`), `mode` (`v2` ou `baseline`), `task_metrics` e `metrics` e, com merge ligado, `merged`, `failed` e
`gate_blocked` (numeros de PR). `task_metrics` e uma lista com um registro por tarefa de worker (`issue` mais escalacao,
espera por dependencia e `final_outcome`: `ok`, `failed` ou `no_pr`) e `metrics` e o resumo do repo no tick, com `n` em cada
taxa. O mesmo registro vai em `squad_metrics` na task do worker do execution-report do tick, que tambem traz `mode` no topo.
Os campos e os limites estao em `docs/SQUADS.md`, secao 5. Uma tarefa que escalou e falhou, ou ficou sem PR, tambem entra.

**Modo baseline (#1565).** `SIMPLICIO_247_SQUADS_BASELINE=1` (exatamente `1`) e a rodada "antes" da comparacao da #1549.
Desliga tres regras da v2: o roteamento por complexidade (todo worker comeca em `execution`), o lote de merge (1 PR por
trem, pelo mesmo `merge_train`) e os contratos entre squads. Nao muda a revisao do squad, o `squad_gate`, o
`SIMPLICIO_247_AUTO_MERGE=1`, o lock do repo nem o `--match-head-commit`. Nunca liga o merge e nunca afrouxa uma aprovacao. O padrao
e `v2`. Uso e limites: `docs/SQUADS.md`, secao 5.

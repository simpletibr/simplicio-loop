# Watcher 24/7 (`simplicio_loop.watcher247`)

O servico `simplicio-loop-247` (unit em `packaging/systemd/`) observa issues novas dos repos `simpletibr/simplicio-*` que
habilitaram o loop (`.simplicio-loop/loop.toml`) e abre PRs. Estado, claims e logs ficam em `SIMPLICIO_247_STATE_DIR`.

## loop.toml do repo (`.simplicio-loop/loop.toml`)

O loop guarda todos os seus arquivos em `.simplicio-loop/`. A pasta `.simplicio/` é do Runtime: o loop não lê nem grava nada nela. Um repo que só tem o arquivo antigo não está habilitado, e o log mostra o caminho novo. O watcher lê o arquivo da **branch padrão** do repo (`gh api .../contents/.simplicio-loop/loop.toml`, uma vez por tick), nunca
do clone: um plano pode editar o arquivo na branch `loop/issue-N` (#1567) e afrouxar o próprio gate.

```toml
enabled = true
allowed_authors = ["fulano"]
verify = "python3 -m pytest -q tests/test_x.py tests/test_y.py"
```

| chave | obrigatória | o que faz |
|---|---|---|
| `enabled` | sim | literal `true`; sem ela o repo não entra (`skipped_repos`: `not_opted_in`) |
| `allowed_authors` | não | logins confiáveis além de OWNER, MEMBER e COLLABORATOR |
| `verify` | sim, para o watcher | comando de teste **direcionado**, uma string; é o `--verify` do turbo e o teste do merge train |

Não há detecção do comando de teste e não há fallback: sem `verify` (ausente, vazio ou que não seja string) nenhuma issue
do repo vira trabalho, nem issue nova nem fix de review. Cada uma aparece em `status.json` como
`skipped_issues["repo#N"] = "verify_not_configured"` e o log diz o repo. Um fix de review continua na fila até o
`verify` existir. A suíte completa não é o padrão: o comando cobre o que a issue toca, e a suíte inteira roda só em
release.

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
  sudo -u simplicio-loop -H simplicio-loop login
  ```
  E verifica a assinatura. Reason codes: `ok`, `login_missing`, `login_insecure`, `subscription_required`, `refresh_failed`, `entitlement_required`, `validate_unreachable`, `account_mismatch`.
  Com `login_insecure`, o `login.json` é um symlink. Ou grupo e outros o leem. Ou ele fica numa pasta que eles gravam. Rode `chmod 600` no arquivo (ou `chmod 700` na pasta) e rode `--check`. Remova um symlink.
  Com `account_mismatch`, o login.json pertence a outra conta: `sudo -u simplicio-loop -H simplicio-loop logout --yes` e faça login novamente.

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
3. **Aplicacao.** O plano JSON entra no stdin de `simplicio-loop turbo --repo <clone> --apply - --verify <verify do loop.toml>`,
   dentro de `sandbox.wrap` e com env filtrado (sem `OPENROUTER_API_KEY`). A abertura do PR depende do verify
   (`verify.decide`), como antes.
4. **Escalada.** Se o apply ou o verify falhar, a escada de `escalation.py` (execution, depois coordination, depois
   planning; execution repete uma vez) escolhe o proximo papel e o planner tenta de novo com a saida da falha, apos
   `git reset --hard` do clone. Teto: `MAX_STEPS` (4) por execucao e os tetos de `EscalationState`
   (`SIMPLICIO_247_ATTEMPT_CEILING_ISSUE` / `_DAY`, `SIMPLICIO_247_TOKEN_CEILING_ISSUE` / `_DAY`). Tokens nao medidos
   (host mode) ficam UNVERIFIED e contam so como tentativas.
5. **Recibo de papel.** Cada etapa grava uma task em `simplicio.execution-report/v1` (no worktree,
   `.simplicio-loop/runtime/execution-reports/latest.json`) com `role`, `model`, `effort`, `family` e resultado.
6. **Patrulha de PRs.** Os PRs `loop/issue-N` abertos passam por `watcher_github.patrol_open_prs`. Comentario de
   review, check vermelho ou conflito viram task de correcao no PR existente, com o papel `coordination`
   (e `planning` se falhar). O fix faz push na mesma branch, sem force; o loop nunca faz merge nem fecha PR.

O planner roda por `sandbox.wrap` (o mesmo bwrap do apply) e com `sandbox.scrubbed_env`: so a allowlist do sandbox, `HOME`
e a chave do proprio CLI (`host_mode.FAMILY_ENV`); `OPENROUTER_API_KEY` e outros segredos do servico nunca chegam a ele.
Cada CLI recebe apenas flags de somente-plano (ver `exec_planner.py`). A config de deny do `opencode` fica em
`<state_dir>/opencode/` (o bwrap monta tmpfs em `/tmp` e esconderia o arquivo, rodando o CLI sem as regras de deny) e e
removida ao fim da chamada (o sandbox só a lê: o state dir é somente leitura).
O `HOME` do planner é um tmpfs vazio com só as pastas da própria família (`host_mode.FAMILY_HOME`, tabela em "Isolamento do
sandbox"): o login de outro CLI, `~/.ssh`, `~/.config/gh`, `~/.aws` e `~/.simplicio/login.json` não existem para ele.

### Login dos CLIs (`watch247 login-check`)

`simplicio-loop watch247 login-check` roda `exec_auth.check_all` nas familias habilitadas e imprime, por CLI, `ok` ou o
comando exato que corrige, por exemplo `sudo -u simplicio-loop -H codex login`. Exit 0 quando todos estao ok, 1 caso
contrario. Nao le nem imprime token. O mesmo estado derruba o tick com `login_missing:<cli>`.

## Executor autor (`SIMPLICIO_247_EXECUTOR=author`, issue #1669)

O executor padrao e o fluxo de plano. Para tarefas que um plano JSON nao cobre, ligue o fluxo autor. Veja `docs/AUTHOR_FLOW.md`.

| Variavel | Valores | Padrao |
|---|---|---|
| `SIMPLICIO_247_EXECUTOR` | `plan` ou `author` | sem a variavel: `plan` |
| `SIMPLICIO_247_AUTHOR_ROUNDS` | numero inteiro de 1 a 10 | `3` |
| `SIMPLICIO_247_AUTHOR_TIMEOUT_S` | segundos de uma rodada da CLI, inteiro de 60 a 3600. Outro valor e ignorado | `900` |
| `SIMPLICIO_247_AUTHOR_RUN_TESTS` | `1` deixa a CLI rodar pytest | sem a variavel: a CLI so le e edita arquivos |
| `SIMPLICIO_247_AUTHOR_HOME_BASE` | caminho absoluto dentro do HOME | `~/.cache/simplicio-loop-author` |
| `SIMPLICIO_247_ALLOW_UNSANDBOXED` | `1` roda a CLI sem sandbox | sem a variavel: sem sandbox nao roda |

- Outro valor para o servico na partida. O log mostra a variavel e os valores aceitos. `status.json` mostra `reason_code=executor_env_invalid`.
- O fluxo autor exige `SIMPLICIO_EXECUTOR` sem valor ou `exec`. Com `openrouter` o tick bloqueia com `author_needs_exec`.
- O watcher usa a primeira familia com login que o fluxo autor aceita. Hoje so `claude`. Outra familia falha com `unsupported_family`.
- A CLI do LLM edita o worktree do proprio item (`<repo>.wt/<n>`). Nunca edita o clone base. Outro caminho falha com `worktree_mismatch`.
- O watcher roda o `verify` do `loop.toml`. Um verify vermelho volta para a mesma sessao da CLI, ate o numero de rounds.
- O watcher nao faz commit nem push antes do resultado `ok`. Com `ok`, a entrega e a mesma do fluxo de plano: commit, push, PR com `Parte de #N`, revisao do squad, eventos, orcamento e claim.
- Sem `ok`, o claim e liberado como em um run de plano que falhou. A regra de retry e de fila morta nao muda. O `reason_code` do claim e o do fluxo autor, por exemplo `verify_failed`.
- O log e o `error` do claim trazem o `reason_code`, os rounds, os tipos de falha e o uso medido. Sem contador da CLI, o uso e `none`. O loop nao estima numero.
- O orcamento `model_calls` soma um por round que rodou.
- A CLI nao recebe `GH_TOKEN`, `GITHUB_TOKEN` nem chave de API. O watcher nao passa env nenhum ao fluxo autor.
- Os caminhos protegidos valem para o fluxo autor. Um round que muda um deles falha com `protected_path`. A unica excecao e `.simplicio-loop/orchestrator/runs/`: o host grava telemetria ali durante o run (o heartbeat do lease), e o snapshot ignora os arquivos regulares dali. Um symlink, hard link, fifo ou socket nessa pasta e mudanca (`protected_path`), porque o host anexaria uma linha ao alvo do link. `.simplicio-loop/loop.toml` e os outros caminhos de `.simplicio-loop` continuam protegidos.
- Por padrao a CLI nao recebe nenhuma ferramenta Bash: so le, busca e edita arquivos. O prompt avisa que ela nao roda testes. O host roda o `verify` e devolve as falhas. Com `SIMPLICIO_247_AUTHOR_RUN_TESTS=1` a CLI roda `pytest` no sandbox dela, onde o HOME privado (copia do login) esta montado e a rede esta aberta. **Aviso:** um conftest do autor pode ler o login e enviar para fora, entao um vazamento de credencial e possivel. Ligue so para repositorios confiaveis.
- Com o HOME protegido (`ProtectHome=read-only`) a unit nao grava em `~/.cache`. Aponte `SIMPLICIO_247_AUTHOR_HOME_BASE` para uma pasta dentro do HOME e inclua essa pasta em `ReadWritePaths=` da unit, por exemplo `ReadWritePaths=/home/simplicio-loop/.simplicio /home/simplicio-loop/.simplicio/authors`. O operador edita a unit. Um caminho relativo, o proprio HOME ou um caminho fora do HOME falha com `home_unavailable`.
- A CLI nao le o HOME privado nem o arquivo de login: as regras `--disallowedTools` `Read`, `Grep`, `Glob`, `Edit` e `Write` negam `//<home privado>/**` e o `.credentials.json` pelo caminho. Um arquivo mudado que contem o arquivo de login ou um `accessToken`/`refreshToken` falha o round com `secret_in_diff`. O detalhe cita o arquivo e nunca o segredo. A sintaxe das regras (`Tool(//caminho/absoluto/**)`) segue a documentacao de permissoes do Claude Code e nao foi provada contra a CLI real (UNVERIFIED): prove com a CLI antes de confiar nela. Mesmo assim a varredura `secret_in_diff` vale.
- UNVERIFIED: o bind do HOME privado dentro do jail aninhado nao foi provado sob a unit empacotada (`packaging/systemd`, com `ProtectHome=read-only`). Rode um item de teste na unit real antes de ligar `SIMPLICIO_247_EXECUTOR=author`.
- Um erro permanente de configuracao devolve a tentativa, mesmo quando rounds anteriores ja rodaram. O item nao perde a tentativa por uma falha do host.
- Antes do commit, o watcher confere com `git symbolic-ref HEAD` que o worktree ainda esta no branch do item. Outro HEAD falha com `head_moved` e nada e commitado.
- Falha de configuracao do host nao gasta tentativa do item: `unsupported_family`, `sandbox_unavailable`, `claude_login_missing`, `cli_unavailable` e `home_unavailable`. O claim volta para `retry` e espera o backoff. O item nunca vira morto por isso.
- `SIMPLICIO_247_EXECUTOR` vazio vale como sem a variavel (`plan`). A CLI sem sandbox so roda com `SIMPLICIO_247_ALLOW_UNSANDBOXED=1`.
- O relatorio de execucao traz `cache_read_tokens` ao lado de `input_tokens` e `output_tokens`, quando a CLI os mede. Se o relatorio nao grava, o resultado do autor continua valendo.

## Caminhos protegidos (`plan_paths.PROTECTED_PATHS`, issue #1567)

Alguns arquivos controlam o próprio watcher, a esteira de entrega ou o que o host executa sozinho. Um plano que os edite deixa o
passo seguinte aprovar a própria mudança. Por isso nenhum plano cria, edita, move ou apaga um deles. O portão fica em
`plan_paths.operations_refusal`, que `turbo.apply_plan`, o `apply` e o runner chamam antes do dev-cli. O `apply` também recusa o
`ops.json` inteiro (`BLOCKED`) antes de gravar a primeira tarefa. A razão é sempre `protected_path: '<caminho>' touches protected
'<entrada>'`.

| entrada | por que |
|---|---|
| `.github` (workflows, templates, `CODEOWNERS`), `CODEOWNERS`, `docs/CODEOWNERS` | a esteira e quem revisa |
| `.simplicio-loop` | `loop.toml` (opt-in, autores, `verify`) e o estado do loop |
| `packaging/systemd`, `scripts/check.py` | a unidade do serviço e o CI local |
| `hooks`, `plugin/hooks`, `simplicio_loop/_bundle/hooks` | os hooks que o host roda (portão de ação, parada, pre-commit) |
| `.githooks`, `.husky`, `.pre-commit-config.yaml`, `.vscode/tasks.json` | o que o git, o pre-commit e o editor rodam sozinhos |
| `.codex/hooks.json`, `.codex/config.toml`, `.claude/settings.json`, `.claude/settings.local.json`, `.claude/hooks`, `.cursor/hooks.json`, `.kiro/hooks` | hooks e comandos dos hosts |
| `simplicio_loop/plan_paths.py`, `intake_gate.py` | este portão e o opt-in do repo |
| `watcher247/sandbox.py`, `secret_scan.py`, `prompt_guard.py`, `env_guard.py`, `squad_flow.py`, `verify.py` | isolamento, segredos, injeção, revisão do squad e o comando `verify` |
| `watcher247/points/judge.py`, `points/delivery_gate.py` | o juiz e o portão de entrega |

- Uma entrada vale para ela mesma e para tudo abaixo dela. Um diretório que contém uma entrada (`packaging`, `plugin`,
  `simplicio_loop`) também conta, porque mover ou apagar o pai levaria o arquivo junto.
- Uma entrada `.py` vale também para os irmãos que o Python importa no lugar dela: o pacote `nome/`, `nome.so`, `nome.pyc` e
  `__pycache__/nome.*`. Sem isso, criar `simplicio_loop/intake_gate/__init__.py` trocaria o portão sem tocar nele.
- O caminho é comparado como o sistema de arquivos o lê: caixa, `\`, `.`, `..`, pontos e espaços no fim, caracteres de largura
  zero e formas de compatibilidade (ponto de largura total). Os symlinks são seguidos antes: `ln -s .github x` não abre
  `x/workflows/ci.yml`, nem como origem nem como `dest` de um `move_file`. Um caminho sem componente (`./`, `.//`, `.\`) é a
  raiz e é recusado como `unsafe_path`.
- Um plano completo (`simplicio.mechanical-edit/v1` ou `simplicio.dev-cli.edit-plan/v1`) com `validation` não vazio é recusado
  inteiro. O dev-cli roda esses comandos depois do apply, a partir da raiz, e eles escrevem em qualquer lugar. O loop roda o
  `--verify` por conta própria, fora do plano.
- Só a escrita é recusada. Um plano ainda pode pedir um trecho (`need`) de um arquivo protegido.
- A lista vale a partir da raiz de **qualquer** repo que o watcher atende, sem rótulo de liberação. Um `hooks/use-x.ts` de um app
  Next.js, um `scripts/check.py` ou um `docs/CODEOWNERS` seriam recusados. Hoje só o simplicio-loop tem `loop.toml`, e o
  portão de plano corre para todo repo que o runner toca.
- Neste repo, os planos do próprio watcher sobre os portões listados também são bloqueados. Um humano edita esses arquivos com
  um commit e um PR dele, revisados como os demais. Não existe rótulo nem variável de ambiente que libere um plano.
  `.claude/skills`, `AGENTS.md`, `tick.py` e `host_mode.py` ficam fora da lista de propósito, porque o loop se constrói por plano
  neles.
- Um link físico para um arquivo protegido não é visto (o dev-cli troca o arquivo em vez de escrever através dele, medido).
- Um teste falha se uma entrada deixar de existir no repo, para que um rename não tire a proteção em silêncio. As entradas que
  este repo ainda não tem estão listadas no teste.

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
- Filesystem somente leitura, state dir inteiro incluído (#1656). O item escreve só o que a lista "O que o item pode escrever" abaixo traz. `/tmp` privado, `--die-with-parent`, `--new-session`.

**O que o item pode escrever (lista exata)**

O item é tudo que roda em `sandbox.wrap` por conta de uma issue (planner, `turbo`, testes). Dentro do sandbox ele escreve só estes caminhos:

| Caminho | Escrita | Motivo |
|---------|---------|--------|
| `<WORK>/<repo>.wt/<issue>` (o worktree do próprio item) | sim | o dev-cli aplica o plano aqui |
| `<git-dir>/worktrees/<issue>` (o admin dir do próprio item) | sim | commit e status do próprio item |
| `<git-dir>/objects` | sim, compartilhado entre os itens do repo | limite conhecido (#1656 item 3, desenho à parte) |
| `<git-dir>/simplicio` | sim | base central do mapper |
| `<HOME>/<pasta da família>` (só o planner) | sim | login, renovação de token, log e sessão do CLI. Tabela abaixo |
| `/tmp`, `/dev` e o `HOME` do planner fora das pastas da família | tmpfs privado | some ao fim da chamada. Nada chega ao host |

Todo o resto é somente leitura. Isso inclui o state dir inteiro: `claims.json`, `budget.json`, `STOP`, `status.json`, `fixes.json`,
`baseline.json`, `issues-disabled.json`, `work/`, `logs/` e `opencode/`. Então o item não cria `STOP` (nem para o watcher), não
enfileira fix com texto livre, não esconde issue e não reescreve o status. Também são somente leitura `config`, `hooks`, `refs` e
`packed-refs` do `<git-dir>` e o worktree e o admin dir dos outros itens. O host continua escrevendo o state dir (a
restrição vale só para a visão do sandbox). A config de deny do `opencode` é escrita pelo host em `<state_dir>/opencode/` e o
sandbox só a lê.

**`HOME` do planner por família** (`host_mode.FAMILY_HOME`, #1570)

O `HOME` é um tmpfs vazio e gravável (some ao fim) e cada família recebe de volta só estas pastas. Pastas, nunca um arquivo
(`~/.claude.json` não é ligado: o `rename` atômico do CLI falharia com EBUSY. Sem ele o `claude` segue logado pelo
`~/.claude/.credentials.json`). `-try`: a pasta que não existe é pulada, e uma família sem login ainda roda (e falha com o erro
de login do próprio CLI). Se o `HOME` não for um diretório absoluto (ou for `/`), `sandbox.wrap` levanta `SandboxUnavailable`.

| Família | Pastas (grava / lê) | Medido com o CLI real |
|---------|---------------------|-----------------------|
| `claude` | grava `~/.claude`. Lê `~/.local/share/claude` e o link `~/.local/bin/claude` | `claude -p` ok. Sem `~/.claude`: "Not logged in" |
| `codex` | grava `~/.codex`. Lê o link `~/.local/bin/codex` | antes: `failed to initialize ... Read-only file system`. Depois inicia e autentica |
| `grok` | grava `~/.grok`. Lê o link `~/.local/bin/grok` | antes: `Couldn't create session ... Read-only file system`. Depois responde |
| `agy` | grava `~/.gemini/antigravity-cli`. Lê `~/.local/bin/agy` | `agy -p` ok só com essa pasta |
| `opencode` | grava `~/.local/share/opencode`. Lê `~/.config/opencode` | antes: `FileSystem.open (...opencode.log)`. Depois inicia (o binário fica em `/usr/local`) |
| `gemini` | grava `~/.gemini`, menos `~/.gemini/antigravity-cli` (escondida) | DOC-BASED: o CLI não está instalado onde se mediu |

Binário fora do `HOME` (`/usr`, `/usr/local`) não precisa de linha. Um link em `~/.local/bin` é recriado como link, então o alvo
entra na tabela (para o `claude`, `~/.local/share/claude`. Para o `codex` e o `grok`, a própria pasta de login).

**Continua visível (decisão e limites conhecidos)**

| Canal | Estado | Motivo |
|-------|--------|--------|
| `/proc/<pid do watcher>/environ`, `cmdline`, `maps`, `status` | oculto | namespace de pid |
| `/proc/self/*`, `/proc/1/*` (o bwrap) | legível | é o env filtrado do próprio filho |
| `HOME` do usuário do serviço, no **planner** | só as pastas da família | tmpfs vazio + as pastas da tabela abaixo (#1570). O login de outro CLI, `~/.ssh`, `~/.config/gh`, `~/.aws` e `~/.simplicio/login.json` não aparecem |
| `HOME` do usuário do serviço, no `turbo` e nos testes (`verify`) | **legível**, somente leitura | ainda não medido o que leem do `HOME` (`~/.cargo`, `~/.cache/uv`), passo 2 do #1570 |
| Pasta da família no `HOME` do planner (`~/.claude`, `~/.codex`, ...) | **gravável e persiste** | o CLI renova o token e grava log e sessão ali. Um planner comprometido pode alterar a config ou os hooks do próprio CLI. O `login-check` ou o operador roda esse CLI fora do sandbox (UNVERIFIED que o `login-check` execute hooks) |
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

O tick usa o mesmo padrao da skill `/simplicio-loop` (#1505). O lote continua limitado por `SIMPLICIO_247_CONCURRENCY` e pelo
teto diario (`budget.py`). Os itens de um mesmo repo rodam ao mesmo tempo, cada um no seu worktree (#1601, `watcher247/worktrees.py`).

- **Base e worktree.** A base `<WORK>/<repo>` nao e editada por nenhum item. Cada issue roda em `<WORK>/<repo>.wt/<issue>`, na branch
  `loop/issue-N`. O worktree some ao fim do item: sucesso, falha, cancelamento ou SIGTERM.
- **Escopo do lock.** O lock por repo cobre so os passos curtos: atualizar a base, `git worktree add/remove` e o push (`git push -u`
  grava o `.git/config` compartilhado). Nunca cobre o plano, o turbo, o apply, o verify nem o PR. O merge train segue serial e usa o lock.
- **Limpeza exata.** Um item remove so o proprio caminho e a entrada de `<git-dir>/worktrees` cujo `gitdir` e igual a `<caminho>/.git`
  (igualdade, nunca prefixo: a issue 1 nao toca a 10). Nao existe `git worktree prune`: ele esqueceria worktrees de outros itens.
  A sobra de uma execucao morta por SIGKILL fica no caminho que a proxima execucao da mesma issue usa, e e limpa la.
- **Estado do item.** O que o item guarda em `.simplicio-loop/` (escada de escalonamento, runs, relatorios) e copiado para
  `<WORK>/<repo>.state/<issue>/` quando o worktree sai e volta no proximo worktree da mesma issue. Links simbolicos nao sao copiados.
- **Arquivo em comum.** Itens do lote que citam o mesmo arquivo-alvo (`squad_flow.target_paths`) rodam em serie, na ordem do lote.
  Os outros rodam em paralelo. Um arquivo que o corpo da issue nao cita so aparece no review ou no merge train.
- **Disco e limite.** No maximo o tamanho do lote em worktrees vivos (o plano de capacidade, ou `SIMPLICIO_247_CONCURRENCY` quando fixado). Com menos de 2 GiB livres o item e adiado sem gastar tentativa.
- **Sandbox.** O bwrap liga o state dir inteiro como somente leitura (#1656): os arquivos de controle, `work/` (os worktrees dos
  outros itens, os admin dirs deles e os clones base, com `config`, `hooks` e `refs`), `logs/` e `opencode/`. Por cima liga como
  gravavel so o worktree do proprio item, o admin dir dele, `<git-dir>/objects` e `<git-dir>/simplicio` (base central do mapper). Os caminhos vem do layout
  fixo, nao do arquivo `.git` do worktree. O `git` do host (status, commit, push do tick) roda no item com `GIT_DIR`, `GIT_COMMON_DIR` e
  `GIT_WORK_TREE` do layout fixo: reescrever o `.git` ou o `commondir` do proprio item nao leva o git do host ao admin dir de outro.
  Limite que fica: `objects/` e compartilhado entre os itens do repo (gravavel por todos). A lista exata do que o item escreve esta em "Isolamento do sandbox".

1. **Coordenador geral** (`planning`). As issues novas admitidas de cada repo viram `squads.plan_squads`: squads de ate 4
   workers e 1 coordenador (`coordination`) cada, dono de arquivo por caminho citado na issue, ordem de merge por
   dependencia. Fixes de review (PR ja aberto) ficam fora dos squads.
2. **Workers.** Cada issue segue o fluxo de host mode acima, comecando no papel de `squad_routing.route`. Sandbox,
   `scrubbed_env` e a escada de escalonamento (2 falhas sobem um papel) valem para todos, sem mudanca.
3. **Revisao do squad.** Para cada PR aberto o coordenador do squad confere (a) o verify do worker foi
   `MEASURED|verify_passed` e (b) nenhum arquivo alterado e compartilhado ou de outro squad. Depois roda o portao automatico de revisao
   (`review_gate`, ver `docs/SQUADS.md`, secao 4a) sobre o clone e posta o veredito no PR com `pr_evidence.publish_comment`:
   `REVISÃO AUTOMÁTICA: APROVADA (nível N)` (um comentario por commit de head, para o horario do comentario ser sempre mais
   novo que o commit) ou `REVISÃO AUTOMÁTICA: REPROVADA` com a causa. Reprovado por (a) ou (b): nada e postado e o motivo
   vai para `status.json`.
4. **Merge: desligado por padrao.** Sem `SIMPLICIO_247_AUTO_MERGE=1` o watcher para em "aprovado" e nunca faz merge
   (#1434). Com a variavel, cada PR aprovado passa por `squads.squad_gate` (aprovacao mais nova que o ultimo commit) e os
   que passam entram em `merge_train` em lotes de ate 4, na ordem do plano: uma branch temporaria `loop/merge-train`
   integra os PRs sobre `main`, roda o `verify` do repo uma vez (no sandbox) e, se ficar vermelho, faz a bisseccao; so o que
   ficou verde recebe `gh pr merge --squash`. Sem force-push.
4a. **PR como draft (#1589).** Sem `SIMPLICIO_247_PR_DRAFT=1` o watcher abre o PR pronto (padrao).
   Com a variavel exatamente `1`, o `gh pr create` recebe `--draft` e o PR fica rascunho ate alguem executar `gh pr ready`.
   Um rascunho nao entra em merge: com `SIMPLICIO_247_AUTO_MERGE=1` tambem ligado, o status mostra `merge: draft`,
   o watcher nao roda o trem nem o `gh pr merge`, e o merge fica com o operador depois do `gh pr ready`.
4b. **Texto do PR sem palavra de fechamento (#1644).** O titulo (`loop: #N titulo`, ate 70 caracteres, corte em palavra com
   reticencias, `#N` sempre inteiro), a mensagem de commit e o corpo do PR usam `Parte de #N`. A funcao `closing_words.sanitize`
   reescreve qualquer `Closes`/`Fixes`/`Resolves` (qualquer caixa, `#N`, `owner/repo#N`, URL) e recusa publicar se sobrar um.
   Fechar a issue e decisao humana. O texto cru do planejador de cada passo fica em `logs/<repo>-<N>-<tentativa>-s<passo>.raw.log`
   (segredos redigidos antes, limite de 20000 caracteres).
5. **Recibo.** Um `simplicio.execution-report/v1` por tick em
   `<state_dir>/squads/.simplicio-loop/runtime/execution-reports/latest.json`: uma task por agente (coordenador geral,
   coordenador de cada squad, cada worker) com `agent.role`, `agent.model` e `agent.effort`; o worker mostra o ultimo
   papel que realmente rodou (apos escalada). `consolidated.tasks_by_role` conta por papel.

Limites de seguranca: `squad_gate` so aceita `REVISÃO AUTOMÁTICA: APROVADA (nível N)` escrito por um autor autorizado (#1534): o `author.login` do
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

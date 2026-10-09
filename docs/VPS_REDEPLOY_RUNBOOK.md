# Runbook: redeploy do watcher 24/7 no VPS (#1476)

Ensaiado em isolamento em 2026-10-09 sobre `origin/main` 5478fdc2 (nada foi instalado, nenhuma unit foi copiada, nenhum usuário foi criado, o serviço não foi tocado). Quem executa estes passos é uma pessoa com root e com as credenciais do dono; os passos marcados `[CRED]` precisam delas.

## O que o ensaio provou (MEASURED)

- A versão **publicada** 3.48.1 (PyPI e GitHub Release) **não contém** `simplicio_loop/watcher247`, `exec_auth`, `sandbox`, `host_mode`, `squad_flow`: a main está 123 commits à frente. Os critérios 1 e 2 do #1476 pedem uma versão nova (ou um wheel intermediário gerado da main, que não é uma versão publicada).
- O wheel gerado da main (`simplicio_loop-3.48.1`, 5,06 MiB, 1395 arquivos) traz o `watcher247` (42 arquivos), o mapper da fonte única (`simplicio_mapper` 0.26.35, carimbado com o commit de origem) e o dev-cli (`simplicio` 0.18.16). Instalou em um venv limpo com as dependências do PyPI.
- No venv: `simplicio-loop --version`, `simplicio-mapper --version` e `simplicio-dev-cli --version` saem com 0. `doctor stack`, `doctor mapper`, `doctor source` e `doctor --storage` saem com 0 e READY. **`doctor` sozinho sai com 2**: exige um subcomando.
- `watch247 --once --dry-run` sem tokens não grava nada. Um tick real com o arquivo de env em modo 640 recusa iniciar (`env_file_permissions`); com 600 e sem `login.json` fica ocioso em `setup_required` / `login_missing`, ou sem `GH_TOKEN` em `github_token_missing`.
- `systemd-analyze verify` na unit empacotada: sem erro.
- O sandbox funciona para um usuário não-root sem capacidades (`setpriv --reuid=65534 --bounding-set=-all --no-new-privs bwrap ...` sai com 0). Como root com o conjunto de capacidades vazio, o bwrap falha: por isso a unit precisa manter `User=simplicio-loop`.
- O estado vivo em `/var/lib/simplicio-loop-247` (baseline, claims) carrega no watcher novo (testado em uma cópia); um claim `running` órfão vira `retry`. Contém um arquivo `STOP`: o watcher fica ocioso até ele ser removido.

## Achados que mudam os comandos

1. O wheel **não traz** a unit nem o `env.example`: copie-os de um checkout no mesmo commit (`packaging/systemd/`).
2. Use um venv dedicado, `/opt/simplicio-loop-247/venv`. O Python do sistema é `EXTERNALLY-MANAGED` e tem outro `simplicio_mapper` editável. **Não reuse** `/opt/simplicio-loop` (é um venv de desenvolvimento).
3. O `ExecStart` empacotado usa `/usr/bin/python3 -m simplicio_loop.watcher247`; para um venv, troque-o por `sed`. O `PATH` do `env.example` não inclui o venv: edite.
4. `claude` e `grok` estão em `/root/.local/bin`, inalcançáveis para outro usuário; `codex` e `opencode` estão em `/usr/local/bin`. O padrão `SIMPLICIO_EXEC_FAMILIES=claude,codex,grok,gemini` falha com `cli_missing`; use `codex,opencode` ou instale os outros para todos.
5. A unit usa `HOME=/home/simplicio-loop`. `ReadWritePaths` precisa de `/home/simplicio-loop/.simplicio` já criado, senão a unit falha com `226/NAMESPACE`.
6. As variáveis do env antigo (`OPENROUTER_API_KEY`, `SIMPLICIO_TURBO_MODEL`) só servem com `SIMPLICIO_EXECUTOR=openrouter` (o padrão agora é `exec`). Novas: `SIMPLICIO_247_STATE_DIR`, `_CONCURRENCY`, `_LOGIN`. O auto-merge segue desligado (`SIMPLICIO_247_AUTO_MERGE`).
7. O `git push` do usuário do serviço precisa do helper de credenciais do `gh`, configurado antes de iniciar (`ProtectHome=read-only`).

## O que o ensaio NÃO provou (UNVERIFIED)

- Tráfego real com o GitHub (o `gh` foi simulado): nenhuma issue foi reivindicada, nenhum PR aberto, nenhum push pelo usuário do serviço.
- Validade de tokens e logins: direito de assinatura, logins dos CLIs, escopo do `GH_TOKEN`.
- A unit rodando sob o systemd como `User=simplicio-loop` (inclusive `226/NAMESPACE`, `ProtectHome` contra `~/.gitconfig` e gravação do refresh de token dos CLIs, que não estão em `ReadWritePaths`), e o sandbox sob o `SystemCallFilter` e o AppArmor reais (só a aproximação com `setpriv` e a tabela documentada em `packaging/systemd/README.md`).
- Um ciclo real de turbo apply/verify no sandbox com o `PATH` editado.

---

# Runbook #1476 - redeploy of the 24/7 watcher (root, ordered)

Rehearsed in isolation (wheel built from origin/main 5478fdc2, version 3.48.1+unreleased). Every step marked
[CRED] needs a credential only the owner has. Anything not run for real is UNVERIFIED.

## 0. Decide the artifact (owner decision)
The PUBLISHED v3.48.1 (PyPI and GitHub Release) does NOT contain `simplicio_loop/watcher247` or `exec_auth.py`.
Criterion (2) cannot be met from it. Pick one:
- A (matches criterion 1): cut a new release from main (see "Cutting a release"), then `VER=<new>` and install from PyPI.
- B (interim): install a wheel built from main: `python3 -m build --wheel` (see step 5b). Not a "published" version.

## 1. Pre-checks (read only)
    systemctl is-active simplicio-loop-247      # expect: inactive
    systemctl is-enabled simplicio-loop-247     # expect: disabled
    df -h / ; du -sh /var/lib/simplicio-loop-247  # root disk had 2.1G free; venv needs ~160M
    ls -l /var/lib/simplicio-loop-247/STOP        # exists: the watcher stays idle until it is removed

## 2. Backup (legacy script, unit, env, small state)
    # The backup directory is written to a file so the ROLLBACK works from a NEW shell (it does not rely on $BK surviving).
    BK="/root/backup-247-$(date +%Y%m%d-%H%M%S)"
    install -d -m 700 "${BK:?}" && echo "$BK" > /root/.vps247-backup-dir
    cp -a /usr/local/sbin/simplicio-loop-247.py /etc/systemd/system/simplicio-loop-247.service \
          /etc/simplicio-loop-247.env "${BK:?}"/
    cp -a /var/lib/simplicio-loop-247/{baseline.json,claims.json,issues-disabled.json,status.json} "${BK:?}"/
    python3 -m pip list --format=freeze > "${BK:?}"/system-pip-freeze.txt
    (cd "${BK:?}" && sha256sum * > SHA256SUMS) ; echo "$BK"
    # STOP HERE if any cp above failed: do not continue to step 3 without a complete backup.

## 3. Service user (the unit and env.example use /home/simplicio-loop, NOT /var/lib/simplicio-loop)
    useradd --system --user-group --create-home --home-dir /home/simplicio-loop \
            --shell /usr/sbin/nologin simplicio-loop
    chmod 700 /home/simplicio-loop
    install -d -o simplicio-loop -g simplicio-loop -m 700 /home/simplicio-loop/.simplicio   # unit ReadWritePaths: missing path = status 226/NAMESPACE
    # git push uses the gh credential helper (root has the same in ~/.gitconfig); the unit makes $HOME read-only, so set it now:
    sudo -u simplicio-loop -H git config --global credential.https://github.com.helper '!/usr/bin/gh auth git-credential'
    sudo -u simplicio-loop -H git config --global user.name simplicio-loop

## 4. State dir ownership (service is inactive; legacy files are root:root and the clones in work/ are root-owned,
##    git refuses them as "dubious ownership" for another user)
    chown -R simplicio-loop:simplicio-loop /var/lib/simplicio-loop-247
    chmod 700 /var/lib/simplicio-loop-247
    # Legacy baseline.json / claims.json load as-is (rehearsed on a copy: 1 'running' claim became 'retry', 143 dead kept).

## 5. Install the package into a DEDICATED venv /opt/simplicio-loop-247/venv
Why a venv and not the system python: (a) /usr/lib/python3.14/EXTERNALLY-MANAGED (PEP 668); (b) dist-packages already
holds a separate `simplicio_mapper-0.26.35` dist (editable from /projetos/ai/simplicio-mapper) that owns the same
`simplicio_mapper/` dir the new wheel bundles - installing over it mixes two mappers, defeating "single source";
(c) no impact on the other tools using system 3.46.1; (d) rollback = delete the dir.
Do NOT reuse /opt/simplicio-loop: it exists (uv dev venv, editable simplicio_loop 3.43.13).
    python3 -m venv /opt/simplicio-loop-247/venv
    # 5a (release):  
    /opt/simplicio-loop-247/venv/bin/pip install "simplicio-loop==${VER}"
    # 5b (interim): build on a machine with the checkout, copy the wheel, then
    #   /opt/simplicio-loop-247/venv/bin/pip install /path/simplicio_loop-3.48.1-py3-none-any.whl
    V=/opt/simplicio-loop-247/venv/bin
    $V/simplicio-loop --version ; $V/simplicio-mapper --version

## 6. doctor (criterion 3; attach the output). NOTE: bare `doctor` exits 2 - a subcommand is required.
    cd /tmp
    { $V/simplicio-loop doctor stack; $V/simplicio-loop doctor mapper; $V/simplicio-loop doctor source; \
      $V/simplicio-loop doctor --storage; } 2>&1 | tee /root/doctor-1476.txt     # expect READY / OK, rc 0 each

## 7. Unit and env
    # the wheel does NOT ship the unit/env: take them from the repo checkout at the same commit (packaging/systemd/)
    sed 's#^ExecStart=.*#ExecStart=/opt/simplicio-loop-247/venv/bin/python -m simplicio_loop.watcher247#' \
        packaging/systemd/simplicio-loop-247.service > /etc/systemd/system/simplicio-loop-247.service
    install -m 600 -o root -g root packaging/systemd/simplicio-loop-247.env.example /etc/simplicio-loop-247.env
    # EDIT BY HAND (never print it) - required changes vs the example:
    #   PATH=/opt/simplicio-loop-247/venv/bin:/usr/local/bin:/usr/bin:/bin   # bare `simplicio-loop`, `gh`, `git` are resolved from PATH,
    #                                                                          # and the sandbox passes PATH on
    #   SIMPLICIO_EXEC_FAMILIES=codex,opencode      # claude/grok live in /root/.local/bin, unreachable for the service user
    #   (GitHub token is written by watch247 setup in step 8; do not edit by hand)
    #   optional first-day caps: SIMPLICIO_247_MAX_ISSUES_PER_DAY=1 SIMPLICIO_247_MAX_PRS_PER_DAY=1
    # env file MUST stay 600: the watcher refuses to start with env_file_permissions otherwise.
    chmod 600 /etc/simplicio-loop-247.env
    systemctl daemon-reload
    systemd-analyze verify /etc/systemd/system/simplicio-loop-247.service   # expect no output about this unit

## 8. Credentials for the service user [CRED]
The owner gives two things here; nobody edits the env file by hand. `watch247 setup` asks for the Simplicio account
e-mail and the GitHub token (hidden input), checks the token with `gh api user`, writes `GH_TOKEN` to the env file
(mode 600, atomic) and reports the subscription reason code. It never prints the token.

    # a) as root, in a terminal: the prompts ask for the e-mail and the token (the token is not echoed)
    export SIMPLICIO_247_ENV_FILE=/etc/simplicio-loop-247.env
    export SIMPLICIO_247_LOGIN=/home/simplicio-loop/.simplicio/login.json
    /opt/simplicio-loop-247/venv/bin/simplicio-loop watch247 setup
    # exit 1 with `login_missing` is expected at this point: the token is stored, the login comes next.
    # exit 2 = refused, nothing changed (bad input, or an env file readable by group/others: use the printed chmod 600).
    # Without a terminal: read -rs GHT; printf '%s' "$GHT" | <same command> --email <account e-mail> --github-token-stdin; unset GHT
    # (the token is never an argument: argv shows in ps)

    # b) the Simplicio login belongs to the service user (the Runtime command; this repo has no login flow of its own)
    sudo -u simplicio-loop -H simplicio login google

    # c) check the account step, no token asked; expect exit 0 and `Simplicio subscription: ok`
    /opt/simplicio-loop-247/venv/bin/simplicio-loop watch247 setup --check

    # d) CLI logins as the service user
    sudo -u simplicio-loop -H codex login
    sudo -u simplicio-loop -H opencode auth login
    # (claude and grok only after installing them system-wide)

The service loads `GH_TOKEN` at start, so the restart in step 11 picks it up. Do not start the service here.
Until both credentials exist, the unit stays idle and `status.json` shows `phase=setup_required` with the reason
(`github_token_missing` or `login_missing`) and the command `simplicio-loop watch247 setup`.

## 9. Dry run as the service user (non-root)
    # root shell sources the env file, then drops to the service user (the file is 600 root, the user cannot read it)
    # Literal path (no variable) on every command that can delete or change ownership.
    install -d -o simplicio-loop -g simplicio-loop -m 700 /run/simplicio-247-dry
    cp -a /var/lib/simplicio-loop-247/{baseline.json,claims.json,issues-disabled.json} /run/simplicio-247-dry/
    chown -R simplicio-loop:simplicio-loop /run/simplicio-247-dry
    run_as() { env -i bash -c 'set -a; . /etc/simplicio-loop-247.env; set +a; export SIMPLICIO_247_ENV_FILE=/etc/simplicio-loop-247.env
               exec setpriv --reuid=simplicio-loop --regid=simplicio-loop --init-groups "$@"' _ "$@"; }
    run_as /opt/simplicio-loop-247/venv/bin/simplicio-loop watch247 login-check   # rc 0 when all enabled CLIs are logged in
    run_as /opt/simplicio-loop-247/venv/bin/simplicio-loop watch247 --once --dry-run --state-dir /run/simplicio-247-dry
    # (dry-run ignores a STOP file only if absent: the real dir has STOP, hence the copy in /run/simplicio-247-dry)
    rm -rf -- /run/simplicio-247-dry

## 10. Sandbox smoke under the unit's filters (the documented check in packaging/systemd/README.md; transient unit, root)
    systemd-run --pipe --wait --quiet -p User=simplicio-loop -p Group=simplicio-loop \
      -p NoNewPrivileges=yes -p CapabilityBoundingSet= -p 'SystemCallFilter=@system-service @mount' \
      -p 'RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX' -p LockPersonality=yes -p RestrictSUIDSGID=yes \
      bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp \
            --bind /var/lib/simplicio-loop-247/work /var/lib/simplicio-loop-247/work --die-with-parent --new-session -- true
    echo rc=$?     # expect 0 (159 = SIGSYS)

## 11. Enable / start (criterion 4: #1434 is closed)
    systemctl enable --now simplicio-loop-247      # still idle: STOP exists
    # to let it work, the owner removes the switch:   rm /var/lib/simplicio-loop-247/STOP
    # (legacy baseline.json is kept, so issues opened since 2026-10-05 will be processed; to avoid that,
    #  `mv /var/lib/simplicio-loop-247/baseline.json{,.old}` first: the first tick re-baselines and processes nothing)
    journalctl -u simplicio-loop-247 -n 50 --no-pager
    cat /var/lib/simplicio-loop-247/status.json    # expect phase processed/idle, not blocked/setup_required
    ps -o user= -C python | sort -u                # expect simplicio-loop, never root
    # Attach /root/doctor-1476.txt to issue #1476.

## ROLLBACK
    # Works from a new shell: the backup directory was recorded in step 2.
    BK="$(cat /root/.vps247-backup-dir)"; test -d "${BK:?}" && test -f "${BK:?}"/SHA256SUMS || { echo "backup dir missing: stop"; exit 1; }
    (cd "${BK:?}" && sha256sum -c SHA256SUMS)                              # the backup is intact before anything is overwritten
    systemctl disable --now simplicio-loop-247
    cp -a "${BK:?}"/simplicio-loop-247.service /etc/systemd/system/simplicio-loop-247.service
    cp -a "${BK:?}"/simplicio-loop-247.env     /etc/simplicio-loop-247.env      # restores the 600 root file
    cp -a "${BK:?}"/simplicio-loop-247.py      /usr/local/sbin/simplicio-loop-247.py
    systemctl daemon-reload
    chown -R root:root /var/lib/simplicio-loop-247                        # then cp -a "${BK:?}"/{baseline,claims,...}.json back if needed
    systemctl is-enabled simplicio-loop-247 ; systemctl is-active simplicio-loop-247   # original state: disabled / inactive
    # Version pin: the system python (3.46.1) was never touched, so nothing to repin. Do not `pip install simplicio-loop==3.46.1`:
    # it is not on PyPI (only 3.46.0 and 3.48.1 are) and the local wheel dist/simplicio_loop-3.46.1 is gone.
    # Optional cleanup: rm -rf /opt/simplicio-loop-247 ; userdel simplicio-loop (keeps /home until `userdel -r`).

## Cutting a release (owner's decision; nothing here was run)
    python3 scripts/version_sync.py apply --version X.Y.Z     # pyproject, npm, cursor plugin, __init__ fallback
    # add "## [X.Y.Z] - date" to CHANGELOG.md
    python3 scripts/check.py --full                           # AGENTS.md: authoritative gate before a tag
    python3 scripts/release_rehearsal.py run --repo .         # local build+checksums+SBOM+install smoke, publishes nothing
    # commit/PR to main, then tag vX.Y.Z and publish (manual, token based per docs/RELEASE.md; no CI): UNVERIFIED exact commands:
    #   python3 -m build ; gh release create vX.Y.Z dist/* ; twine upload dist/*   (no ~/.pypirc on this host)

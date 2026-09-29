# Installer mutation inventory (issue #293 §1)

Exact inventory of every disk/PATH/service mutation the installer can perform, which script
performs it, its scope, its reversibility, and how it differs across Windows/macOS/Linux. This is
the "mapear todos os efeitos" + "matriz Windows/macOS/Linux e runtime por runtime" deliverable —
read alongside the machine-checkable plan a `--dry-run` prints
(`contracts/install-transaction/v1/schema.json`, produced by `scripts/install_plan.py`).

**Generated file — do not hand-edit.** Run `python3 scripts/gen_install_mutations_doc.py`
after changing `MUTATIONS`/`OS_DIFFS`/`_consent_rows()` in that script; `scripts/claims_audit.py`
fails the gate if this file drifts from what the generator produces.

## 1. Effect inventory, by source file

| Source | Function | Effect | Scope | Reversible | Consent required |
|---|---|---|---|---|---|
| `install_lib.py` | `copy_skills()` | copies the 7 skills into `<target>/.claude/skills/<skill>` | project/user | yes (delete dir) | no (default-mode effect) |
| `install_lib.py` | `sync_global_vscode_copilot()` | for global VS Code installs, copies skills into `~/.copilot/skills`, writes the personal Copilot instructions file, and merges the `simplicio` MCP server into `~/.copilot/mcp-config.json` and the VS Code user `mcp.json` | user (global vscode only) | yes (delete/restore the managed files) | no (default-mode effect; unrelated config is preserved) |
| `install_lib.py` | `copy_hooks()` | copies `hooks/` into `<target>/hooks` (project) or `<target>/.claude/hooks` (global) | project/user | yes | no |
| `install_lib.py` | `copy_scripts()` | copies `scripts/*.py` (minus `__pycache__`/`*.pyc`) into `<target>/scripts` (project) or `<target>/.claude/scripts` (global) | project/user | yes | no |
| `install_lib.py` | `ensure_entry()` | creates/updates the runtime's entry file (`AGENTS.md`, `GEMINI.md`, `QWEN.md`, `.github/copilot-instructions.md`, `.kiro/steering/simplicio-loop.md`, `.continue/rules/simplicio-loop.md`, `CONVENTIONS.md`) between `<!-- simplicio-loop:begin/end -->` markers | project/user | yes (marker-delimited block is removable without touching the rest of the file) | no |
| `install_lib.py` | `merge_claude_hooks()` | merges `Stop` (+ project-local `PreToolUse`) hook entries into `.claude/settings.json` | project/user | yes (JSON merge; existing unrelated keys untouched) | no |
| `install_lib.py` | `install_git_precommit_hook()` | writes `.git/hooks/pre-commit` (only if the target is a git repo and no foreign hook already lives there) | project only | yes (file replace/delete) | no — but a *foreign* existing hook is never overwritten (logged, not clobbered) |
| `install_lib.py` | `ensure_operators() / _pip_install()` | `pip install -U simplicio-loop` (ships the 2 required operator binaries) | **global** Python environment (whatever `sys.executable` resolves to — a venv if active, else the system/user Python) | **not reversible by this installer** (a real `pip uninstall` is a separate, manual step) | **yes for `--break-system-packages`** — only attempted when pip's stderr specifically reports `externally-managed-environment` AND `--allow-break-system-packages` (or `SIMPLICIO_ALLOW_BREAK_SYSTEM_PACKAGES=1`) was explicitly passed (#293 §3 hardening, see below) |
| `install_lib.py` | `_link_console_script() / _link_operator_bins()` | symlinks console-scripts (`simplicio-dev-cli`, `simplicio-mapper`, `simplicio-loop`) into `~/.local/bin` when a `--user` pip install dropped them off PATH | user (`~/.local/bin`) | yes (remove symlink) | no (best-effort, never fails the install) |
| `install_lib.py` | `install_all_deps()` | `pip install -U .[ml]` / `simplicio-loop[ml]` + tray dep (`pystray`+`pillow` or `rumps` on macOS) — #293 audit fix: was `.[onnx]`, an extra pyproject.toml no longer declares (removed in CHANGELOG 3.11.0) | global Python environment | not reversible by this installer | **yes** — only runs when `--with-service`/`--full-stack` consent is given (#293 fix: no longer runs by default) |
| `install_lib.py` | `copy_full_stack()` | copies `engine/` (capture-proxy code) and `app/` (tray code) into the target — the file surface of `full-stack` mode | project/user | yes (delete dir) | **yes** — only in `--mode full-stack` with explicit `--with-service`/`--with-proxy` |
| `install_lib.py` | `setup_monitor()` | registers the always-on capture proxy (`install_services.py install`/`wire` on Linux/Windows, `setup_simplicio.sh` — launchd — on macOS) + opens the Token Monitor dashboard once | system service scope | services: yes (`install_services.py uninstall`); dashboard open: not applicable (no persistent mutation) | **yes** — requires `--with-service` (or `--full-stack`); OFF by default (#293 fix: was previously default-on, gated only by opt-out `--minimal`) |
| `install_services.py` | `install() / wire()` | Linux: writes a `systemd --user` unit; Windows: registers a Startup-folder shim; wiring: edits provider base-URL env for Claude/Codex/Simplicio Agent | user/system, OS-specific | yes (`uninstall()`) | same as `setup_monitor()` above |
| `install_executor.py` | `apply()` | wraps every one of the above FILE effects (skills/hooks/scripts/entry/claude_settings, + `engine`/`app` in full-stack mode) with a pre-mutation backup + before/after hash + persisted receipt under `<target>/.simplicio-loop/receipts/<id>.json`; automatic rollback of every already-applied step if a later step raises | project/user | yes, byte-for-byte via `rollback()` | governed entirely by the plan's `permissions_required` (see `install_plan.py`) |
| `install_executor.py` | `manifest reconciliation (_stale_skills() + the reconcile step)` | removes a skill directory that a PRIOR install's manifest recorded but the CURRENT release no longer declares (an N-1 → N upgrade cleanup) | project/user | yes (same backup/restore mechanism as every other step) | no (this only ever removes paths the transaction's OWN prior manifest claims responsibility for) |

## 2. OS-specific differences

| Concern | Linux | macOS | Windows |
|---|---|---|---|
| Global install target | `HOME` (from `os.path.expanduser("~")`) | `HOME` | `HOME` (`%USERPROFILE%`) |
| `~/.local/bin` symlink target | real symlink (`os.symlink`) | real symlink | `os.symlink` requires Developer Mode or admin — falls back silently (best-effort; `_link_console_script` swallows `OSError`) |
| `chmod +x` on `.git/hooks/pre-commit` | applied (`0o755`) | applied | `os.chmod` is a no-op on most Windows filesystems; git only needs the file to be invocable via `sh` (`#!/usr/bin/env sh` shebang), which the file already has — the failed `chmod` is caught and logged as non-fatal |
| Externally-managed Python (PEP 668) | common on Debian/Ubuntu system Python | common on Homebrew Python | rare (python.org/Store installs are not externally-managed) — the detection in `_is_externally_managed_error()` still applies uniformly; it simply never fires here |
| Capture-proxy service registration | `install_services.py` → `systemd --user` unit | `setup_simplicio.sh` → `launchd` agent | `install_services.py` → Startup-folder shim |
| Path separators in receipts/manifest | POSIX (`/`) | POSIX (`/`) | `os.path` mixed; hashing walks (`_hash_path`) normalize relative paths to `/` before hashing so a receipt/manifest hash is stable across OSes for the same tree content |
| Console-script extension | none | none | `.exe` (pip) or `.CMD`/`.EXE` shims — `install_smoke.py`'s clean-room check and `_link_console_script()` both branch on `os.name == "nt"` |

## 3. Consent matrix (what requires an explicit flag)

Per `install_plan.py::_permissions_required()` and `build_plan()`'s `blocked_reasons` gate:

| Effect | Trigger | Required consent |
|---|---|---|
| `global_package` | `scope in (user, system)` or `mode == full-stack` | scope/mode itself is the explicit choice (no separate flag) |
| `break_system_packages` | pip refuses with PEP 668's `externally-managed-environment` | `--allow-break-system-packages` / `SIMPLICIO_ALLOW_BREAK_SYSTEM_PACKAGES=1` — **never applied unconditionally** |
| `path_write / symlink` | `scope != project` | implied by `--global` |
| `service` | `--with-service` or `mode == full-stack` | explicit flag; **`mode == full-stack` alone is NOT enough** — full-stack additionally requires `--with-service` **and** `--with-proxy` together, or the plan stays `BLOCKED` (`blocked_reasons: ["full_stack_confirmation"]`, #293 fix: mode name is never itself treated as consent) |
| `proxy` | `--with-proxy` or `mode == full-stack` | same as `service` above |

A plan with an ungated `break_system_packages` permission, or a `full-stack` mode selected
without both `--with-service` and `--with-proxy`, is returned with `status: "BLOCKED"`
and mutates nothing (`install_plan.py` is a pure planner; `install_executor.py::apply()`
returns the BLOCKED plan as-is without persisting a transaction).

## 4. Status (this round)

- `setup_monitor()` (capture proxy + dashboard + tray) in the legacy (non-transactional)
  `install_lib.py main()` flow now requires the SAME explicit `--with-service`/`--full-stack`
  consent the transactional path already required — it no longer runs by default. A plain
  `install_lib.py <runtime>` with no flags registers no service, rewrites no `OPENAI_BASE_URL`/
  `ANTHROPIC_BASE_URL`, and opens no browser (#293 AC1).
- `install_executor.py` now has a real, distinct file surface per mode: `minimal`/`runtime`/`ci`
  apply the same skills/hooks/scripts/entry/settings steps (no services, no engine/app code);
  `full-stack` additionally copies `engine/`+`app/` (the capture-proxy/dashboard/tray CODE).
  OS-level service registration (systemd `--user` unit on Linux, Startup-folder shim on Windows)
  is now wired into `apply()` itself as a backed-up, rollback-eligible `"service"` step whenever
  `with_service=True` — no longer a separate manual `python3 scripts/install_services.py install`
  step a human has to remember to run afterward. macOS stays the documented separate `bash
  scripts/setup_simplicio.sh` (launchd) path — `install_services.py` has no launchd backend to wire in.
- `--ci` (mode `ci`) now resolves and PINS an exact operator-package version (`simplicio-cli==X.Y.Z`,
  via `install_lib.resolve_pinned_version()`) instead of a floating `pip install -U`, for a
  reproducible CI install; the plan's `version_pinning` field (`"pinned"`/`"floating"`) surfaces this
  intent even in `--dry-run`, before any pip call runs. If neither an already-installed version nor
  `pip index versions` is reachable (offline), it falls back to a floating install with an explicit
  warning — never a fabricated pin.
- This document is now GENERATED from `scripts/gen_install_mutations_doc.py`, not hand-maintained
  prose, closing the drift risk called out in an earlier round of #293. A machine-readable JSON
  rendering of the SAME source-of-truth data (`docs/install-mutations.json`, schema `simplicio.install-mutations/v1`) is
  emitted alongside this `.md` (`python3 scripts/gen_install_mutations_doc.py` writes both; `--check`
  fails the gate if either drifts) — a third, non-prose consumer no longer has to scrape markdown.
- Real container/VM-level clean-install tests (`tests/system/test_clean_install.py`'s matrix
  entry) remain infeasible in this sandbox: no Docker/VM runtime is available here (`docker --version`
  fails with "command not found"). Not fabricated; tracked as a genuine, environment-limited gap.

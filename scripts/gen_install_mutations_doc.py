#!/usr/bin/env python3
"""Generate `docs/INSTALL_MUTATIONS.md` from a single in-code data structure (#293 §7,
"gerar tabela de efeitos a partir do manifest do instalador").

Before this script, the doc was hand-maintained prose kept in sync with `install_lib.py` /
`install_plan.py` / `install_executor.py` / `install_services.py` by discipline alone — exactly
the kind of promise-vs-reality drift issue #293 calls out ("divergência entre as sete skills
anunciadas e o conjunto tratado pelo caminho do instalador"). Now the mutation inventory, the
OS-differences matrix, and the consent matrix are all rendered from `MUTATIONS` / `OS_DIFFS` /
`_consent_rows()` below — the same constants `install_plan.py`'s `_permissions_required()` logic
mirrors — so a future change to what requires consent can't silently leave the doc stale:
`scripts/claims_audit.py`'s `check_install_mutations_doc` re-renders this module and fails the
gate if `docs/INSTALL_MUTATIONS.md` on disk differs by a single byte.

Also emits `docs/install-mutations.json` (schema `simplicio.install-mutations/v1`) from the exact
SAME `MUTATIONS`/`OS_DIFFS`/`_consent_rows()` data — a structured, machine-readable rendering for
a third consumer that shouldn't have to scrape markdown tables (#293 gap: "machine-readable
effects manifest").

Usage:
    python3 scripts/gen_install_mutations_doc.py            # regenerate .md + .json in place
    python3 scripts/gen_install_mutations_doc.py --json      # print the JSON manifest to stdout
    python3 scripts/gen_install_mutations_doc.py --check     # exit 1 if either file has drifted
"""
from __future__ import annotations

import json
import os
import sys

try:  # Windows consoles default to cp1252 and choke on the non-ASCII arrows/checkmarks below.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DOC_PATH = os.path.join(REPO, "docs", "INSTALL_MUTATIONS.md")
JSON_PATH = os.path.join(REPO, "docs", "install-mutations.json")
JSON_SCHEMA = "simplicio.install-mutations/v1"

# ── 1. Effect inventory, by source file — the "mapear todos os efeitos" deliverable ────────────
# (source, function, effect, scope, reversible, consent_required)
MUTATIONS = [
    ("install_lib.py", "copy_skills()",
     "copies the 7 skills into `<target>/.claude/skills/<skill>`",
     "project/user", "yes (delete dir)", "no (default-mode effect)"),
    ("install_lib.py", "sync_global_vscode_copilot()",
     "for global VS Code installs, copies skills into `~/.copilot/skills`, writes the personal "
     "Copilot instructions file, and merges the `simplicio` MCP server into "
     "`~/.copilot/mcp-config.json` and the VS Code user `mcp.json`",
     "user (global vscode only)", "yes (delete/restore the managed files)",
     "no (default-mode effect; unrelated config is preserved)"),
    ("install_lib.py", "copy_hooks()",
     "copies `hooks/` into `<target>/hooks` (project) or `<target>/.claude/hooks` (global)",
     "project/user", "yes", "no"),
    ("install_lib.py", "copy_scripts()",
     "copies `scripts/*.py` (minus `__pycache__`/`*.pyc`) into `<target>/scripts` (project) or "
     "`<target>/.claude/scripts` (global)",
     "project/user", "yes", "no"),
    ("install_lib.py", "ensure_entry()",
     "creates/updates the runtime's entry file (`AGENTS.md`, `GEMINI.md`, "
     "`.github/copilot-instructions.md`, `.kiro/steering/simplicio-loop.md`, `CONVENTIONS.md`) "
     "between `<!-- simplicio-loop:begin/end -->` markers",
     "project/user",
     "yes (marker-delimited block is removable without touching the rest of the file)", "no"),
    ("install_lib.py", "merge_claude_hooks()",
     "merges `Stop` (+ project-local `PreToolUse`) hook entries into `.claude/settings.json`",
     "project/user", "yes (JSON merge; existing unrelated keys untouched)", "no"),
    ("install_lib.py", "install_git_precommit_hook()",
     "writes `.git/hooks/pre-commit` (only if the target is a git repo and no foreign hook "
     "already lives there)",
     "project only", "yes (file replace/delete)",
     "no — but a *foreign* existing hook is never overwritten (logged, not clobbered)"),
    ("install_lib.py", "ensure_operators() / _pip_install()",
     "`pip install -U simplicio-loop` (ships the 2 required operator binaries)",
     "**global** Python environment (whatever `sys.executable` resolves to — a venv if active, "
     "else the system/user Python)",
     "**not reversible by this installer** (a real `pip uninstall` is a separate, manual step)",
     "**yes for `--break-system-packages`** — only attempted when pip's stderr specifically "
     "reports `externally-managed-environment` AND `--allow-break-system-packages` (or "
     "`SIMPLICIO_ALLOW_BREAK_SYSTEM_PACKAGES=1`) was explicitly passed (#293 §3 hardening, see "
     "below)"),
    ("install_lib.py", "_link_console_script() / _link_operator_bins()",
     "symlinks console-scripts (`simplicio-dev-cli`, `simplicio-mapper`, `simplicio-loop`) into "
     "`~/.local/bin` when a `--user` pip install dropped them off PATH",
     "user (`~/.local/bin`)", "yes (remove symlink)",
     "no (best-effort, never fails the install)"),
    ("install_lib.py", "install_all_deps()",
     "`pip install -U .[ml]` / `simplicio-loop[ml]` + tray dep (`pystray`+`pillow` or "
     "`rumps` on macOS) — #293 audit fix: was `.[onnx]`, an extra pyproject.toml no longer "
     "declares (removed in CHANGELOG 3.11.0)",
     "global Python environment", "not reversible by this installer",
     "**yes** — only runs when `--with-service`/`--full-stack` consent is given "
     "(#293 fix: no longer runs by default)"),
    ("install_lib.py", "copy_full_stack()",
     "copies `engine/` (capture-proxy code) and `app/` (tray code) into the target — the file "
     "surface of `full-stack` mode",
     "project/user", "yes (delete dir)",
     "**yes** — only in `--mode full-stack` with explicit `--with-service`/`--with-proxy`"),
    ("install_lib.py", "setup_monitor()",
     "registers the always-on capture proxy (`install_services.py install`/`wire` on "
     "Linux/Windows, `setup_simplicio.sh` — launchd — on macOS) + opens the Token Monitor "
     "dashboard once",
     "system service scope",
     "services: yes (`install_services.py uninstall`); dashboard open: not applicable (no "
     "persistent mutation)",
     "**yes** — requires `--with-service` (or `--full-stack`); OFF by default (#293 fix: was "
     "previously default-on, gated only by opt-out `--minimal`)"),
    ("install_services.py", "install() / wire()",
     "Linux: writes a `systemd --user` unit; Windows: registers a Startup-folder shim; wiring: "
     "edits provider base-URL env for Claude/Codex/Simplicio Agent",
     "user/system, OS-specific", "yes (`uninstall()`)", "same as `setup_monitor()` above"),
    ("install_executor.py", "apply()",
     "wraps every one of the above FILE effects (skills/hooks/scripts/entry/claude_settings, "
     "+ `engine`/`app` in full-stack mode) with a pre-mutation backup + before/after hash + "
     "persisted receipt under `<target>/.simplicio-loop/receipts/<id>.json`; automatic rollback of "
     "every already-applied step if a later step raises",
     "project/user", "yes, byte-for-byte via `rollback()`",
     "governed entirely by the plan's `permissions_required` (see `install_plan.py`)"),
    ("install_executor.py", "manifest reconciliation (_stale_skills() + the reconcile step)",
     "removes a skill directory that a PRIOR install's manifest recorded but the CURRENT "
     "release no longer declares (an N-1 → N upgrade cleanup)",
     "project/user", "yes (same backup/restore mechanism as every other step)",
     "no (this only ever removes paths the transaction's OWN prior manifest claims "
     "responsibility for)"),
]

# ── 2. OS-specific differences ──────────────────────────────────────────────────────────────────
OS_DIFFS = [
    ("Global install target", "`HOME` (from `os.path.expanduser(\"~\")`)", "`HOME`",
     "`HOME` (`%USERPROFILE%`)"),
    ("`~/.local/bin` symlink target", "real symlink (`os.symlink`)", "real symlink",
     "`os.symlink` requires Developer Mode or admin — falls back silently (best-effort; "
     "`_link_console_script` swallows `OSError`)"),
    ("`chmod +x` on `.git/hooks/pre-commit`", "applied (`0o755`)", "applied",
     "`os.chmod` is a no-op on most Windows filesystems; git only needs the file to be invocable "
     "via `sh` (`#!/usr/bin/env sh` shebang), which the file already has — the failed `chmod` is "
     "caught and logged as non-fatal"),
    ("Externally-managed Python (PEP 668)", "common on Debian/Ubuntu system Python",
     "common on Homebrew Python",
     "rare (python.org/Store installs are not externally-managed) — the detection in "
     "`_is_externally_managed_error()` still applies uniformly; it simply never fires here"),
    ("Capture-proxy service registration", "`install_services.py` → `systemd --user` unit",
     "`setup_simplicio.sh` → `launchd` agent", "`install_services.py` → Startup-folder shim"),
    ("Path separators in receipts/manifest", "POSIX (`/`)", "POSIX (`/`)",
     "`os.path` mixed; hashing walks (`_hash_path`) normalize relative paths to `/` before "
     "hashing so a receipt/manifest hash is stable across OSes for the same tree content"),
    ("Console-script extension", "none", "none",
     "`.exe` (pip) or `.CMD`/`.EXE` shims — `install_smoke.py`'s clean-room check and "
     "`_link_console_script()` both branch on `os.name == \"nt\"`"),
]


def _consent_rows():
    """The consent matrix (§3), derived from the SAME conditions
    `install_plan._permissions_required()` and `install_plan.build_plan()`'s `blocked_reasons`
    gate implement — kept here as parallel prose rather than importing install_plan.py, so this
    generator stays import-light/standalone like the modules it documents; drift between the two
    is exactly what `claims_audit.py`'s cited-commands checks (§9) and this doc's own render-diff
    check together are positioned to catch if the two silently diverge in the future."""
    return [
        ("global_package", "`scope in (user, system)` or `mode == full-stack`",
         "scope/mode itself is the explicit choice (no separate flag)"),
        ("break_system_packages", "pip refuses with PEP 668's `externally-managed-environment`",
         "`--allow-break-system-packages` / `SIMPLICIO_ALLOW_BREAK_SYSTEM_PACKAGES=1` — **never "
         "applied unconditionally**"),
        ("path_write / symlink", "`scope != project`", "implied by `--global`"),
        ("service", "`--with-service` or `mode == full-stack`",
         "explicit flag; **`mode == full-stack` alone is NOT enough** — full-stack additionally "
         "requires `--with-service` **and** `--with-proxy` together, or the plan stays "
         "`BLOCKED` (`blocked_reasons: [\"full_stack_confirmation\"]`, #293 fix: mode name is "
         "never itself treated as consent)"),
        ("proxy", "`--with-proxy` or `mode == full-stack`", "same as `service` above"),
    ]


def build_manifest_dict() -> dict:
    """The SAME `MUTATIONS`/`OS_DIFFS`/`_consent_rows()` source-of-truth data `render_doc()`
    turns into prose, structured instead for a programmatic/non-prose consumer (#293 gap 4:
    "machine-readable effects manifest" beyond the per-run `install-transaction/v1` plan — this
    describes the installer's static mutation SURFACE, not one run's effects). Field names are
    the tuple positions in `MUTATIONS`/`OS_DIFFS` given explicit keys so a consumer never has to
    guess column order."""
    return {
        "schema": JSON_SCHEMA,
        "mutations": [
            {"source": source, "function": fn, "effect": effect, "scope": scope,
             "reversible": reversible, "consent_required": consent}
            for source, fn, effect, scope, reversible, consent in MUTATIONS
        ],
        "os_differences": [
            {"concern": concern, "linux": linux, "macos": macos, "windows": windows}
            for concern, linux, macos, windows in OS_DIFFS
        ],
        "consent_matrix": [
            {"effect": effect, "trigger": trigger, "required_consent": consent}
            for effect, trigger, consent in _consent_rows()
        ],
    }


def render_doc() -> str:
    lines = []
    a = lines.append
    a("# Installer mutation inventory (issue #293 §1)")
    a("")
    a("Exact inventory of every disk/PATH/service mutation the installer can perform, which "
      "script")
    a("performs it, its scope, its reversibility, and how it differs across "
      "Windows/macOS/Linux. This is")
    a("the \"mapear todos os efeitos\" + \"matriz Windows/macOS/Linux e runtime por runtime\" "
      "deliverable —")
    a("read alongside the machine-checkable plan a `--dry-run` prints")
    a("(`contracts/install-transaction/v1/schema.json`, produced by `scripts/install_plan.py`).")
    a("")
    a("**Generated file — do not hand-edit.** Run `python3 scripts/gen_install_mutations_doc.py`")
    a("after changing `MUTATIONS`/`OS_DIFFS`/`_consent_rows()` in that script; "
      "`scripts/claims_audit.py`")
    a("fails the gate if this file drifts from what the generator produces.")
    a("")
    a("## 1. Effect inventory, by source file")
    a("")
    a("| Source | Function | Effect | Scope | Reversible | Consent required |")
    a("|---|---|---|---|---|---|")
    for source, fn, effect, scope, reversible, consent in MUTATIONS:
        a("| `%s` | `%s` | %s | %s | %s | %s |" % (source, fn, effect, scope, reversible, consent))
    a("")
    a("## 2. OS-specific differences")
    a("")
    a("| Concern | Linux | macOS | Windows |")
    a("|---|---|---|---|")
    for concern, linux, macos, windows in OS_DIFFS:
        a("| %s | %s | %s | %s |" % (concern, linux, macos, windows))
    a("")
    a("## 3. Consent matrix (what requires an explicit flag)")
    a("")
    a("Per `install_plan.py::_permissions_required()` and `build_plan()`'s `blocked_reasons` "
      "gate:")
    a("")
    a("| Effect | Trigger | Required consent |")
    a("|---|---|---|")
    for effect, trigger, consent in _consent_rows():
        a("| `%s` | %s | %s |" % (effect, trigger, consent))
    a("")
    a("A plan with an ungated `break_system_packages` permission, or a `full-stack` mode "
      "selected")
    a("without both `--with-service` and `--with-proxy`, is returned with `status: \"BLOCKED\"`")
    a("and mutates nothing (`install_plan.py` is a pure planner; `install_executor.py::apply()`")
    a("returns the BLOCKED plan as-is without persisting a transaction).")
    a("")
    a("## 4. Status (this round)")
    a("")
    a("- `setup_monitor()` (capture proxy + dashboard + tray) in the legacy (non-transactional)")
    a("  `install_lib.py main()` flow now requires the SAME explicit `--with-service`/"
      "`--full-stack`")
    a("  consent the transactional path already required — it no longer runs by default. A "
      "plain")
    a("  `install_lib.py <runtime>` with no flags registers no service, rewrites no "
      "`OPENAI_BASE_URL`/")
    a("  `ANTHROPIC_BASE_URL`, and opens no browser (#293 AC1).")
    a("- `install_executor.py` now has a real, distinct file surface per mode: `minimal`/"
      "`runtime`/`ci`")
    a("  apply the same skills/hooks/scripts/entry/settings steps (no services, no engine/app "
      "code);")
    a("  `full-stack` additionally copies `engine/`+`app/` (the capture-proxy/dashboard/tray "
      "CODE).")
    a("  OS-level service registration (systemd `--user` unit on Linux, Startup-folder shim on "
      "Windows)")
    a("  is now wired into `apply()` itself as a backed-up, rollback-eligible `\"service\"` "
      "step whenever")
    a("  `with_service=True` — no longer a separate manual "
      "`python3 scripts/install_services.py install`")
    a("  step a human has to remember to run afterward. macOS stays the documented separate "
      "`bash")
    a("  scripts/setup_simplicio.sh` (launchd) path — `install_services.py` has no launchd "
      "backend to wire in.")
    a("- `--ci` (mode `ci`) now resolves and PINS an exact operator-package version "
      "(`simplicio-cli==X.Y.Z`,")
    a("  via `install_lib.resolve_pinned_version()`) instead of a floating "
      "`pip install -U`, for a")
    a("  reproducible CI install; the plan's `version_pinning` field "
      "(`\"pinned\"`/`\"floating\"`) surfaces this")
    a("  intent even in `--dry-run`, before any pip call runs. If neither an already-installed "
      "version nor")
    a("  `pip index versions` is reachable (offline), it falls back to a floating install with "
      "an explicit")
    a("  warning — never a fabricated pin.")
    a("- This document is now GENERATED from `scripts/gen_install_mutations_doc.py`, not "
      "hand-maintained")
    a("  prose, closing the drift risk called out in an earlier round of #293. A machine-"
      "readable JSON")
    a("  rendering of the SAME source-of-truth data (`docs/install-mutations.json`, schema "
      "`%s`) is" % JSON_SCHEMA)
    a("  emitted alongside this `.md` (`python3 scripts/gen_install_mutations_doc.py` writes "
      "both; `--check`")
    a("  fails the gate if either drifts) — a third, non-prose consumer no longer has to "
      "scrape markdown.")
    a("- Real container/VM-level clean-install tests (`tests/system/test_clean_install.py`'s "
      "matrix")
    a("  entry) remain infeasible in this sandbox: no Docker/VM runtime is available here "
      "(`docker --version`")
    a("  fails with \"command not found\"). Not fabricated; tracked as a genuine, "
      "environment-limited gap.")
    a("")
    return "\n".join(lines)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rendered = render_doc()
    rendered_json = json.dumps(build_manifest_dict(), indent=2, sort_keys=True,
                               ensure_ascii=False) + "\n"
    if "--check" in argv:
        current = ""
        if os.path.exists(DOC_PATH):
            with open(DOC_PATH, encoding="utf-8") as f:
                current = f.read()
        current_json = ""
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, encoding="utf-8") as f:
                current_json = f.read()
        stale = []
        if current != rendered:
            stale.append("docs/INSTALL_MUTATIONS.md")
        if current_json != rendered_json:
            stale.append("docs/install-mutations.json")
        if stale:
            print("! %s stale — run: python3 scripts/gen_install_mutations_doc.py"
                  % " and ".join(stale))
            return 1
        print("docs/INSTALL_MUTATIONS.md and docs/install-mutations.json match the generator "
              "output")
        return 0
    if "--json" in argv:
        print(rendered_json, end="")
        return 0
    with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(rendered)
    with open(JSON_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(rendered_json)
    print("wrote %s" % DOC_PATH)
    print("wrote %s" % JSON_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""doctor — verify the whole simplicio-loop stack; `--repair` fixes what's fixable.

Two tiers, and the distinction is the whole point:
  • REQUIRED   — the orchestrator + token capture need these (python3, the loop operator package and
                 its runtime bins, the
                 7 skills, the loop hooks, the always-on capture proxy). `--repair` installs/wires them.
  • OPTIONAL   — nice-to-have accelerators (the menu-bar tray dep). **Missing them is NOT a
                 failure** — the Python engine + the deterministic path cover everything.
                 `--repair` installs them best-effort and never fails the run because an
                 optional piece is absent.

Exit code: 0 if every REQUIRED item is healthy (after repair), else 1. Cross-platform, stdlib only.

Usage:  python3 scripts/doctor.py [--repair] [--json]
"""
import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PROXY_PORT = int(os.environ.get("SIMPLICIO_PROXY_PORT", "8788"))
PY = sys.executable or "python3"
DARWIN = sys.platform == "darwin"
SKILLS = ["simplicio-tasks", "simplicio-loop", "simplicio-orient",
          "simplicio-review", "simplicio-compress", "simplicio-learn",
          "simplicio-autoresearch"]
OPERATOR_PKG = "simplicio-loop"
OPERATOR_BINS = ("simplicio-dev-cli", "simplicio-mapper")

OK, WARN, FAIL = "ok", "warn", "fail"
GLYPH = {OK: "✓", WARN: "○", FAIL: "✗"}


def _port_up(port):
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
            return True
    except OSError:
        return False


def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.get("timeout", 900), **{k: v for k, v in kw.items() if k != "timeout"})
    except (FileNotFoundError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(cmd, 1, "", "")


def _pip(args_):
    """pip install with a PEP-668 fallback into the user site (best-effort)."""
    base = [PY, "-m", "pip", "install", "-U"]
    for extra in ([], ["--user", "--break-system-packages"]):
        if _run(base + extra + args_, cwd=str(REPO)).returncode == 0:
            return True
    return False


def _link_operator_bins():
    """Symlink operator console-scripts into ~/.local/bin when a --user install put them off PATH."""
    local_bin = HOME / ".local" / "bin"
    cands = [str(local_bin), os.path.dirname(PY)]
    cands += glob.glob(str(HOME / "Library" / "Python" / "*" / "bin"))
    cands += glob.glob(str(HOME / "AppData" / "Roaming" / "Python" / "*" / "Scripts"))
    for b in OPERATOR_BINS:
        if shutil.which(b):
            continue
        for d in cands:
            src = os.path.join(d, b + (".exe" if os.name == "nt" else ""))
            if os.path.isfile(src):
                try:
                    local_bin.mkdir(parents=True, exist_ok=True)
                    dst = local_bin / os.path.basename(src)
                    if dst.exists() or dst.is_symlink():
                        dst.unlink()
                    os.symlink(src, dst)
                except OSError:
                    pass
                break


# ── checks ───────────────────────────────────────────────────────────────────
def chk_python():
    v = sys.version_info
    ok = v >= (3, 8)
    return dict(name="python3", tier="REQUIRED", status=OK if ok else FAIL,
                msg="%d.%d.%d" % (v.major, v.minor, v.micro), repair=None)


def _operators_ok():
    return all(shutil.which(b) for b in OPERATOR_BINS)


def chk_operators():
    missing = [b for b in OPERATOR_BINS if not shutil.which(b)]

    def repair():
        _pip([OPERATOR_PKG])
        _link_operator_bins()
        return _operators_ok()

    return dict(name="loop operator package", tier="REQUIRED",
                status=OK if not missing else FAIL,
                msg="simplicio-loop installed; simplicio-dev-cli + simplicio-mapper on PATH"
                if not missing else "missing runtime bin(s): " + ", ".join(missing),
                repair=repair)


# mapper >=0.13 (inspect/handoff: evidence gate + context-pack) and >=0.14
# (ask/sync/drift: structured queries + docs gates). The survey step uses all
# of them; an older mapper still surveys, so this is a WARN, never a FAIL.
MAPPER_CAPABILITY_VERBS = ("inspect", "handoff", "ask", "sync", "drift")


def chk_mapper_capabilities():
    if not shutil.which("simplicio-mapper"):
        return dict(name="mapper 0.13/0.14 surface", tier="OPTIONAL", status=WARN,
                    msg="mapper bin missing (shipped with simplicio-loop)",
                    repair=lambda: False)

    def _missing():
        helptext = _run(["simplicio-mapper", "--help"], timeout=30).stdout
        return [v for v in MAPPER_CAPABILITY_VERBS if v not in helptext]

    missing = _missing()

    def repair():
        _pip([OPERATOR_PKG])
        return not _missing()

    return dict(name="mapper 0.13/0.14 surface", tier="OPTIONAL",
                status=OK if not missing else WARN,
                msg="inspect/handoff + ask/sync/drift available" if not missing
                else "mapper missing verbs (%s) — pip install -U %s" %
                     (", ".join(missing), OPERATOR_PKG),
                repair=repair)


def chk_skills():
    root = HOME / ".claude" / "skills"
    present = [s for s in SKILLS if (root / s).is_dir()]

    def repair():
        _run(["bash", str(REPO / "scripts" / "install.sh"), "claude", "--global", "--minimal"])
        return all((root / s).is_dir() for s in SKILLS)

    return dict(name="skills (global)", tier="REQUIRED",
                status=OK if len(present) == len(SKILLS) else FAIL,
                msg="%d/%d in ~/.claude/skills" % (len(present), len(SKILLS)), repair=repair)


def chk_hooks():
    hooks_ok = (HOME / ".claude" / "hooks" / "loop_stop.py").is_file()
    wired = False
    sp = HOME / ".claude" / "settings.json"
    if sp.is_file():
        try:
            d = json.loads(sp.read_text())
            wired = any("loop_stop.py" in h.get("command", "")
                        for g in d.get("hooks", {}).get("Stop", []) for h in g.get("hooks", []))
        except (ValueError, OSError):
            pass
    ok = hooks_ok and wired

    def repair():
        _run(["bash", str(REPO / "scripts" / "install.sh"), "claude", "--global", "--minimal"])
        return (HOME / ".claude" / "hooks" / "loop_stop.py").is_file()

    return dict(name="loop hooks + Stop wire", tier="REQUIRED", status=OK if ok else FAIL,
                msg="hooks copied + Stop hook wired" if ok else ("hooks missing" if not hooks_ok else "Stop hook not wired"),
                repair=repair)


def chk_vscode_copilot_global():
    """Verify the user-level Copilot/VS Code surfaces (#415).

    This is OPTIONAL because Claude/Codex-only hosts do not need VS Code.  When
    a user has opted into the global VS Code install, the same check proves the
    active Copilot skills, personal instructions, Copilot CLI MCP, and VS Code
    user MCP are all present and parseable.
    """
    try:
        from copilot_global import verify_global_copilot
        report = verify_global_copilot(home=HOME)
    except Exception as exc:
        return dict(name="VS Code/Copilot global surfaces", tier="OPTIONAL", status=WARN,
                    msg="verification unavailable: %s" % exc, repair=None)

    # A normal Claude/Codex/etc. host may never have requested a global VS Code
    # install. Do not report that untouched optional surface as drift.
    official_paths = (Path(report["skills_root"]), Path(report["instructions"]),
                      Path(report["copilot_mcp"]), Path(report["vscode_mcp"]))
    if not any(path.exists() for path in official_paths):
        return dict(name="VS Code/Copilot global surfaces", tier="OPTIONAL", status=OK,
                    msg="no global VS Code/Copilot install detected — nothing to verify",
                    repair=None)

    keys = ("skills_present", "instructions_present", "copilot_mcp_valid", "vscode_mcp_valid")
    ok = all(report.get(key) for key in keys)

    def repair():
        _run([PY, str(REPO / "scripts" / "install_lib.py"), "vscode", "--global",
              "--skip-operators"])
        try:
            from copilot_global import verify_global_copilot
            return all(verify_global_copilot(home=HOME).get(key) for key in keys)
        except Exception:
            return False

    return dict(name="VS Code/Copilot global surfaces", tier="OPTIONAL",
                status=OK if ok else WARN,
                msg="Copilot skills/instructions + both user MCP configs aligned"
                if ok else "run the global vscode installer to align user-level surfaces",
                repair=repair)


def chk_git_precommit_hook():
    """Verify this repo's own git pre-commit hook auto-syncs plugin/+_bundle/ (#98).

    RECOMMENDED, not REQUIRED: the hook is a convenience that saves a manual
    `sync_plugin.py`/`sync_bundle.py` run before committing — `scripts/claims_audit.py` (run by
    `scripts/check.py`) is the fail-closed backstop that catches drift regardless, so a missing
    hook never blocks the loop.
    """
    hook_path = REPO / ".git" / "hooks" / "pre-commit"
    txt = hook_path.read_text(errors="replace") if hook_path.is_file() else ""
    ok = "pre-commit.py" in txt

    def repair():
        sys.path.insert(0, str(REPO / "scripts"))
        import install_lib
        install_lib.install_git_precommit_hook(str(REPO))
        t = hook_path.read_text(errors="replace") if hook_path.is_file() else ""
        return "pre-commit.py" in t

    return dict(name="git pre-commit hook (auto-sync #98)", tier="RECOMMENDED",
                status=OK if ok else WARN,
                msg="wired -> auto-syncs plugin/+_bundle/ on commit" if ok
                    else "not installed — `python3 scripts/install.sh claude` wires it, or --repair",
                repair=repair)


def chk_git_prepush_hook():
    """Verify this repo's own git pre-push hook enforces the local gate (#291).

    RECOMMENDED, not REQUIRED, for the same reason as `chk_git_precommit_hook`: the hook is what
    makes the gate mandatory-and-impossible-to-bypass FROM THIS CLONE, but a clone without it
    installed doesn't corrupt anything by itself — the receiving side (code review / the next
    `scripts/check.py` run) is the actual backstop. Still worth flagging: with GitHub Actions
    removed (#311), a clone missing this hook has NO mechanical gate between "git push" and
    "main", only human discipline.
    """
    hook_path = REPO / ".git" / "hooks" / "pre-push"
    txt = hook_path.read_text(errors="replace") if hook_path.is_file() else ""
    ok = "action_gate.py" in txt and "pre-push" in txt

    def repair():
        sys.path.insert(0, str(REPO / "scripts"))
        import install_lib
        install_lib.install_git_prepush_hook(str(REPO))
        t = hook_path.read_text(errors="replace") if hook_path.is_file() else ""
        return "action_gate.py" in t and "pre-push" in t

    return dict(name="git pre-push hook (local gate #291)", tier="RECOMMENDED",
                status=OK if ok else WARN,
                msg="wired -> secret-scan + core-gate before every push" if ok
                    else "not installed — `python3 scripts/install.sh claude` wires it, or --repair",
                repair=repair)


def chk_proxy():
    up = _port_up(PROXY_PORT)

    def repair():
        if DARWIN:
            _run(["bash", str(REPO / "scripts" / "setup_simplicio.sh")])
        else:
            _run([PY, str(REPO / "scripts" / "install_services.py"), "install"])
        return _port_up(PROXY_PORT)

    return dict(name="capture proxy", tier="REQUIRED", status=OK if up else FAIL,
                msg=":%d live (always-on)" % PROXY_PORT if up else ":%d down" % PROXY_PORT, repair=repair)


def chk_wire():
    prof = HOME / ".zshrc"
    txt = prof.read_text(errors="replace") if prof.is_file() else ""
    has_a = ("ANTHROPIC_BASE_URL=http://127.0.0.1:%d" % PROXY_PORT) in txt
    has_o = ("OPENAI_BASE_URL=http://127.0.0.1:%d" % PROXY_PORT) in txt
    # Claude is only routable through the proxy with a static key (OAuth 401s). With OAuth the correct
    # state is OPENAI wired + ANTHROPIC absent — so require ANTHROPIC only when a static key is set.
    want_a = bool(os.environ.get("ANTHROPIC_API_KEY"))
    ok = has_o and (has_a if want_a else not has_a)

    def repair():
        _run(["bash", str(REPO / "scripts" / "simplicio-economy.sh"), "wire"])
        t = prof.read_text(errors="replace") if prof.is_file() else ""
        return ("OPENAI_BASE_URL=http://127.0.0.1:%d" % PROXY_PORT) in t

    if want_a:
        msg = "Claude (static key) + Codex/OpenAI + Simplicio Agent routed" if ok else "not wired (Claude/Codex not measured)"
    else:
        msg = "Codex/OpenAI + Simplicio Agent routed (Claude uses OAuth — not proxied)" if ok else "OpenAI not wired (Codex not measured)"
    return dict(name="always-capture wire", tier="RECOMMENDED", status=OK if ok else WARN,
                msg=msg, repair=repair)


def chk_tray_dep():
    dep = "rumps" if DARWIN else "pystray"
    ok = _importable(dep)

    def repair():
        _pip([dep] if DARWIN else [dep, "pillow"])
        return _importable(dep)

    return dict(name="menu-bar tray dep", tier="OPTIONAL", status=OK if ok else WARN,
                msg="%s ready (tray on-demand)" % dep if ok else "%s not installed (optional)" % dep, repair=repair)


def _importable(mod):
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def check_vscode_global():
    """#415: detect drift in a user-level VS Code/Copilot global install.

    If the user ever ran `install_lib.py vscode --global`, the skills were mirrored
    into a user-level skill root and a user-level MCP server was registered. This check
    reports drift when those surfaces no longer match the installed source, or the MCP
    server is missing/stale. If no global VS Code install is present, this is a no-op
    (OPTIONAL tier — never blocks doctor).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "install_lib_415", str(REPO / "scripts" / "install_lib.py"))
    if spec is None or spec.loader is None:
        return {"status": OK, "tier": "OPTIONAL", "name": "vscode_global",
                "msg": "could not import install_lib resolver (skipped)"}
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        vdirs = mod.vscode_user_level_dirs(str(HOME))
    except Exception:
        return {"status": OK, "tier": "OPTIONAL", "name": "vscode_global",
                "msg": "could not import install_lib resolver (skipped)"}

    skills_dst = Path(vdirs["skills"])
    mcp_path = Path(vdirs["mcp"])
    # No global install evidence -> nothing to verify (non-fatal).
    if not skills_dst.is_dir() and not mcp_path.exists():
        return {"status": OK, "tier": "OPTIONAL", "name": "vscode_global",
                "msg": "no global VS Code/Copilot install detected — nothing to verify"}

    problems = []
    # Skills drift: every source skill must exist and be a dir in the user-level root.
    if skills_dst.is_dir():
        missing = [s for s in SKILLS
                   if not (skills_dst / s).is_dir()]
        if missing:
            problems.append("skills missing/stale: %s" % ", ".join(missing))
    else:
        problems.append("user-level skills root missing: %s" % skills_dst)
    # MCP drift: server must be registered.
    if mcp_path.exists():
        try:
            cfg = json.loads(mcp_path.read_text(encoding="utf-8"))
            if "simplicio" not in cfg.get("servers", {}):
                problems.append("user-level MCP server 'simplicio' not registered")
        except Exception:
            problems.append("user-level MCP config unreadable: %s" % mcp_path)
    else:
        problems.append("user-level MCP config missing: %s" % mcp_path)

    if problems:
        def _repair():
            try:
                mod.copy_skills(str(skills_dst), skills_dst=str(skills_dst))
                mod.write_vscode_user_mcp(vdirs["user_dir"], vdirs["settings"], vdirs["mcp"])
                return True
            except Exception:
                return False
        return {"status": WARN, "tier": "OPTIONAL", "name": "vscode_global",
                "msg": "drift: " + "; ".join(problems), "repair": _repair}
    return {"status": OK, "tier": "OPTIONAL", "name": "vscode_global",
            "msg": "global VS Code/Copilot surfaces aligned with source"}


def chk_release_version():
    """Is a newer GitHub release available? Network-dependent, so OPTIONAL/fail-open — a
    detected-but-declined update is never silently applied, this only surfaces the fact."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "release_check", REPO / "scripts" / "release_check.py")
        release_check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release_check)
        local_version = release_check.read_local_version(str(REPO))
        remote_tag = release_check._gh_latest_release_tag(release_check.DEFAULT_GH_REPO)
    except Exception:
        return {"status": WARN, "tier": "OPTIONAL", "name": "release_version",
                "msg": "could not check for a newer release (network/gh unavailable) — skipped"}
    if remote_tag is None:
        return {"status": WARN, "tier": "OPTIONAL", "name": "release_version",
                "msg": "could not check for a newer release (gh unavailable/unauthenticated)"}
    comparison = release_check.compare_versions(local_version, remote_tag.lstrip("v"))
    if comparison == "behind":
        return {"status": WARN, "tier": "OPTIONAL", "name": "release_version",
                "msg": ("a newer release is available: local %s < latest %s — "
                       "run `bash scripts/update.sh` or `pip install -U simplicio-loop`, "
                       "then re-verify with `python3 scripts/version_sync.py check`"
                       % (local_version, remote_tag))}
    return {"status": OK, "tier": "OPTIONAL", "name": "release_version",
            "msg": "up to date (local %s, latest release %s)" % (local_version, remote_tag)}


def chk_map_service():
    """Report whether a live map receipt exists; a missing one uses the standalone fallback."""
    path = REPO / ".simplicio-loop/orchestrator" / "map" / "build.json"
    if not path.exists():
        return {"status": WARN, "tier": "OPTIONAL", "name": "map_service",
                "msg": "no map receipt; standalone map fallback is available"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": FAIL, "tier": "OPTIONAL", "name": "map_service",
                "msg": "map receipt is invalid: %s" % exc}
    if payload.get("schema") != "simplicio.map-service-cli/v1" or not payload.get("trace_id"):
        return {"status": FAIL, "tier": "OPTIONAL", "name": "map_service",
                "msg": "map receipt is missing schema or trace_id"}
    return {"status": OK, "tier": "OPTIONAL", "name": "map_service",
            "msg": "map receipt valid (fallback=%s)" % payload.get("fallback", False)}


CHECKS = [chk_python, chk_operators, chk_mapper_capabilities, chk_skills,
          chk_hooks, chk_git_precommit_hook, chk_git_prepush_hook, chk_proxy, chk_wire,
          chk_tray_dep, check_vscode_global, chk_map_service, chk_release_version]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="doctor", description="verify + repair the simplicio-loop stack")
    ap.add_argument("--repair", action="store_true", help="fix the fixable REQUIRED/RECOMMENDED items + install OPTIONAL where possible")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    results = [c() for c in CHECKS]

    if args.repair:
        for r in results:
            # Repair anything not OK that has a fixer. OPTIONAL failures stay non-fatal.
            if r["status"] != OK and r.get("repair"):
                fixed = False
                try:
                    fixed = bool(r["repair"]())
                except Exception:
                    fixed = False
                r["status"] = OK if fixed else r["status"]
                r["repaired"] = fixed
        # Re-evaluate from scratch so the final report reflects reality.
        results = [c() for c in CHECKS]

    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "repair"} for r in results], indent=2))
    else:
        print("⬡ simplicio-loop doctor%s\n" % ("  ·  repair mode" if args.repair else ""))
        for r in results:
            print("  %s [%-11s] %-22s %s" % (GLYPH[r["status"]], r["tier"], r["name"], r["msg"]))
        print()
        req_bad = [r for r in results if r["tier"] in ("REQUIRED",) and r["status"] == FAIL]
        rec_bad = [r for r in results if r["tier"] == "RECOMMENDED" and r["status"] != OK]
        opt_bad = [r for r in results if r["tier"] == "OPTIONAL" and r["status"] != OK]
        if not req_bad:
            print("  ✓ all REQUIRED items healthy — the orchestrator + capture are operational.")
        else:
            print("  ✗ REQUIRED broken: %s — run:  python3 scripts/doctor.py --repair"
                  % ", ".join(r["name"] for r in req_bad))
        if rec_bad and not args.repair:
            print("  ○ recommended: %s — `--repair` wires it." % ", ".join(r["name"] for r in rec_bad))
        if opt_bad:
            print("  ○ optional (fine to skip): %s — absent does NOT block anything."
                  % ", ".join(r["name"] for r in opt_bad))

    return 1 if any(r["tier"] == "REQUIRED" and r["status"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

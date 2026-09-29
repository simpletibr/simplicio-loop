#!/usr/bin/env python3
"""simplicio-loop — adapter install-contract verifier (per-runtime e2e).

Runs the universal installer into a throwaway target for each runtime and asserts the adapter's
contract actually lands: the 7 skills are copied, the runtime's entry/instructions file exists and
carries the idempotent marker block, hooks are present where the adapter promises them, (for
Claude) the loop hooks are wired into settings.json, AND (#303 AC5) `scripts/loop_progress.py
selftest` actually runs GREEN from inside the installed target — a dedicated, per-runtime
assertion, not an implicit one inferred from the sweep merely exiting 0. This is the runnable half
of issue #11 — it proves the installer + thin adapters end-to-end on THIS machine, in isolation,
with zero risk to the user's real config (always `--target <tmpdir>`, never `--global`).

What it does NOT cover: launching the actual runtime binary (antigravity / kiro / opencode /
aider) and running `/simplicio-loop` inside it. That manual smoke step is listed per-runtime in
adapters/MATRIX.md and the per-adapter READMEs; this harness gates everything up to that point.

Usage:
    python3 scripts/verify_adapters.py [runtime ...]   # default: every installer runtime
    python3 scripts/verify_adapters.py antigravity kiro opencode aider   # the #11 TODO set
Exit code 0 = all verified, 1 = at least one runtime failed its contract.
"""
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import install_lib  # single source of truth for SKILLS + RUNTIMES + marker  # noqa: E402

REPO = os.path.dirname(HERE)


def _install(runtime, target):
    """Invoke the real installer CLI (true e2e), isolated to `target`.

    Always passes `--skip-operators --minimal`: the installer otherwise performs real
    system-wide dependency/model/monitor setup regardless of `--target` (the target scopes
    files, not the host's Python/services). Running that in a verifier would mutate the real
    environment and can block on package/model/network work, contradicting this script's
    throwaway contract. This harness verifies the skills/entry/hooks contract, not
    operator/dependency installation.
    """
    return subprocess.run(
        [sys.executable, os.path.join(HERE, "install_lib.py"), runtime,
         "--target", target, "--skip-operators", "--minimal"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _check(runtime, target):
    """Return a list of failure strings ([] = contract satisfied)."""
    fails = []
    cfg = install_lib.RUNTIMES[runtime]

    # 1) all 7 skills copied
    skills_root = os.path.join(target, ".claude", "skills")
    for s in install_lib.SKILLS:
        if not os.path.isdir(os.path.join(skills_root, s)):
            fails.append("missing skill: %s" % s)
    # a skill must carry its SKILL.md (not just an empty dir)
    st = os.path.join(skills_root, "simplicio-tasks", "SKILL.md")
    if not os.path.isfile(st):
        fails.append("simplicio-tasks/SKILL.md not copied")

    # 2) entry file exists and carries the idempotent marker block
    if cfg["entry"]:
        entry = os.path.join(target, cfg["entry"])
        if not os.path.isfile(entry):
            fails.append("entry file missing: %s" % cfg["entry"])
        else:
            with open(entry, encoding="utf-8") as f:
                body = f.read()
            if install_lib.MARK_A not in body or install_lib.MARK_B not in body:
                fails.append("entry file lacks marker block: %s" % cfg["entry"])

    # 3) hooks present (project install copies hooks/ unless target IS the source repo)
    if os.path.abspath(target) != os.path.abspath(REPO):
        hook = os.path.join(install_lib.hooks_dir(target, False), "loop_stop.py")
        if not os.path.isfile(hook):
            fails.append("hooks not copied (loop_stop.py absent)")

    # 4) Claude wires the loop into settings.json
    if cfg["hooks"] == "claude":
        settings = os.path.join(target, ".claude", "settings.json")
        if not os.path.isfile(settings):
            fails.append("claude settings.json not written")
        else:
            with open(settings, encoding="utf-8") as f:
                if "loop_stop.py" not in f.read():
                    fails.append("Stop hook (loop_stop.py) not wired into settings.json")

    # 5) skill-load surface carries the turn-header progress contract (#303 AC1) — this is the
    # N2 fallback EVERY runtime gets, hook or not: SKILL.md § Output requires `render
    # --turn-header` as the first line of every turn.
    loop_skill = os.path.join(skills_root, "simplicio-loop", "SKILL.md")
    if os.path.isfile(loop_skill):
        with open(loop_skill, encoding="utf-8", errors="replace") as f:
            if "render --turn-header" not in f.read():
                fails.append("simplicio-loop/SKILL.md missing the turn-header contract "
                            "(render --turn-header)")
    else:
        fails.append("simplicio-loop/SKILL.md not copied")

    # 6) hook-bound runtimes install the PROGRESS-INJECTING loop_stop.py (#303 AC1/AC6), not a
    # stale copy — the marker is the private helper `_progress_header_prefix` (#302).
    if cfg["hooks"] in ("claude", "cursor") and os.path.abspath(target) != os.path.abspath(REPO):
        hook_path = os.path.join(install_lib.hooks_dir(target, False), "loop_stop.py")
        if os.path.isfile(hook_path):
            with open(hook_path, encoding="utf-8", errors="replace") as f:
                if "_progress_header_prefix" not in f.read():
                    fails.append("loop_stop.py installed without progress injection "
                                "(_progress_header_prefix marker missing)")

    # 7) #303 AC5 — `loop_progress.py selftest` actually runs GREEN from inside the installed
    # target, for real, for every runtime. Previously this was only checked implicitly (via the
    # full sweep passing); this is the dedicated, per-runtime assertion the issue asked for.
    # Every runtime this harness installs (project-local, `--target <tmpdir>`) gets `scripts/`
    # copied alongside skills/hooks (`install_lib.copy_scripts`, #303 AC5 fix), so the worker is
    # invoked exactly as the loop itself would: `python3 scripts/loop_progress.py selftest` with
    # cwd == the installed target, not the source repo. Skipped only when target IS this source
    # checkout (nothing was copied over itself — the real scripts/ already lives there and is
    # covered by `tests/test_loop_progress_integration.py`).
    if os.path.abspath(target) != os.path.abspath(REPO):
        fails.extend(_check_loop_progress_selftest(target))
    return fails


def _check_loop_progress_selftest(target):
    """Run `python3 <target>/scripts/loop_progress.py selftest` for real; return failure strings.

    Faithful to how every adapter actually invokes it (SKILL.md/hooks call `python3
    scripts/loop_progress.py ...` relative to the runtime's own cwd) — this runs with
    `cwd=target`, not the source repo, so it fails loudly if `scripts/` wasn't actually copied
    into the installed layout rather than passing on the source repo's own copy by accident.
    """
    worker = os.path.join(install_lib.scripts_dir(target, False), "loop_progress.py")
    if not os.path.isfile(worker):
        return ["scripts not copied (loop_progress.py absent) — #303 AC5"]
    try:
        r = subprocess.run([sys.executable, worker, "selftest"], capture_output=True, text=True,
                           cwd=target, encoding="utf-8", errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        return ["loop_progress.py selftest timed out (>60s) from installed target"]
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "MEASURED|" not in out:
        tail = "\n".join(ln for ln in out.splitlines() if ln.strip())[-500:]
        return ["loop_progress.py selftest FAILED from installed target (exit %d): %s"
                % (r.returncode, tail)]
    return []


def verify(runtime):
    target = tempfile.mkdtemp(prefix="st-verify-%s-" % runtime)
    try:
        r = _install(runtime, target)
        if r.returncode != 0:
            return ["installer exited %d: %s" % (r.returncode, (r.stderr or r.stdout).strip()[:300])]
        return _check(runtime, target)
    finally:
        shutil.rmtree(target, ignore_errors=True)


def main():
    runtimes = sys.argv[1:] or list(install_lib.RUNTIMES)
    # Support "tier1" shortcut (#99): runtime Tier 1 = claude, codex, cursor
    tier1 = {"claude", "codex", "cursor"}
    if "tier1" in runtimes:
        runtimes.remove("tier1")
        for r in tier1:
            if r not in runtimes:
                runtimes.append(r)
    unknown = [r for r in runtimes if r not in install_lib.RUNTIMES]
    if unknown:
        print("unknown runtime(s): %s" % " ".join(unknown))
        sys.exit(2)
    print("adapter install-contract verification (%d runtime(s))" % len(runtimes))
    print("-" * 60)
    failed = 0
    for rt in runtimes:
        fails = verify(rt)
        if fails:
            failed += 1
            print("FAIL  %-12s" % rt)
            for f in fails:
                print("        - " + f)
        else:
            print("PASS  %-12s  skills+entry+hooks landed" % rt)
    print("-" * 60)
    print("%d passed, %d failed" % (len(runtimes) - failed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""simplicio-loop — converge/drain contract validator (`simplicio.loop-execution/v1`, #115).

Validates every fixture under `contracts/loop-execution/v1/fixtures/` against the REAL producers
this repo ships — not a re-description of them. Two harnesses:

  1. **Subprocess harness** (`converge-success`, `stop-path`, `evidence-gated-done/*`): copies the
     fixture's `.simplicio-loop/orchestrator/` tree into an isolated temp directory and runs the actual
     `hooks/loop_stop.py` there (cwd=temp dir) with the fixture's `stdin.json` on stdin. Asserts on
     the real exit code / stdout / resulting files — the same script Claude Code and Cursor invoke
     as the Stop hook, unmodified.
  2. **Pure-function harness** (`converge-stall-escalation`, `journal-append-only-minimal`): imports
     `scripts/loop_journal.py`'s side-effect-free `analyze()`/`fingerprint()` and calls them
     directly on the fixture's data — no subprocess needed, and no risk of touching this repo's own
     `.simplicio-loop/orchestrator/loop/journal.jsonl` (that module resolves its JOURNAL path relative to its own
     file location, not argv/cwd, so it must never be invoked as a CLI against fixture data).

`drain-empty-after-k-rounds` is the one exception: no script in this repo executes a drain
scheduler tick today (it is host-provided — cron / a durable scheduler), so this validator applies
a REFERENCE algorithm derived from the documented rule
(`.claude/skills/simplicio-loop/SKILL.md` § "Two loop modes") instead of calling existing code.
This is called out in that fixture's own `expected.json` and in `contracts/loop-execution/v1/
SCHEMA.md` so nobody mistakes it for an extraction of running code.

Every fixture also gets a light structural pass against `contracts/loop-execution/v1/schema.json`'s
required-field lists (scratchpad frontmatter, journal records, anchor, watcher challenge/state) —
independent of the fixture's own behavioral assertions, so the schema doc and the fixtures can never
silently drift apart from each other.

A missing fixture, a missing producer script, or a real behavioral mismatch is a FAILURE — this
validator never fakes a pass. Stdlib-only, no network, no third-party dependencies.

Usage:
    python3 scripts/check_loop_contract.py            # validate every fixture, exit 0/1
    python3 scripts/check_loop_contract.py selftest    # same (registered in claims_audit.py)
    python3 scripts/check_loop_contract.py --describe-cli
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONTRACT_DIR = os.path.join(REPO, "contracts", "loop-execution", "v1")
FIXTURES_DIR = os.path.join(CONTRACT_DIR, "fixtures")
SCHEMA_PATH = os.path.join(CONTRACT_DIR, "schema.json")
LOOP_STOP = os.path.join(REPO, "hooks", "loop_stop.py")

if HERE not in sys.path:
    sys.path.insert(0, HERE)


# ---------------------------------------------------------------------------
# schema.json structural checks — shared across every fixture
# ---------------------------------------------------------------------------

def _load_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _parse_frontmatter(text):
    """Minimal re-implementation of hooks/loop_stop.py:parse_frontmatter for read-only checks."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta


def _check_required(obj, required, label, errors):
    missing = [k for k in required if k not in obj]
    if missing:
        errors.append("%s: missing required field(s) %s" % (label, missing))


def schema_check_tree(fixture_dir, schema, errors):
    """Walk one fixture directory; structurally validate every recognized state file it contains."""
    artifacts = schema["artifacts"]
    for root, _dirs, names in os.walk(fixture_dir):
        for name in names:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, fixture_dir)
            label = "%s:%s" % (os.path.relpath(fixture_dir, FIXTURES_DIR), rel)
            if name == "scratchpad.md":
                with open(path, encoding="utf-8") as f:
                    meta = _parse_frontmatter(f.read())
                if meta is None:
                    errors.append("%s: not a valid frontmatter document" % label)
                else:
                    _check_required(meta, artifacts["scratchpad_frontmatter"]["required_fields"],
                                     label, errors)
                    mode = meta.get("mode")
                    if mode not in schema["modes"]:
                        errors.append("%s: mode=%r not in %s" % (label, mode, schema["modes"]))
            elif name == "journal.jsonl":
                with open(path, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError as e:
                            errors.append("%s: line %d not valid JSON (%s)" % (label, i, e))
                            continue
                        _check_required(rec, artifacts["journal_record"]["required_fields"],
                                         "%s:line %d" % (label, i), errors)
                        gate = rec.get("gate")
                        if gate not in ("pass", "fail", "blocked"):
                            errors.append("%s:line %d: gate=%r not in pass|fail|blocked" %
                                           (label, i, gate))
            elif name == "anchor.json":
                with open(path, encoding="utf-8") as f:
                    anchor = json.load(f)
                _check_required(anchor, artifacts["anchor"]["required_fields"], label, errors)
                for c in anchor.get("criteria") or []:
                    _check_required(c, artifacts["anchor"]["criterion_required_fields"],
                                     "%s: criterion %s" % (label, c.get("id", "?")), errors)
                    if c.get("status") not in ("pending", "partial", "done"):
                        errors.append("%s: criterion %s status=%r invalid" %
                                       (label, c.get("id", "?"), c.get("status")))
            elif name == "watcher_challenge.json":
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                _check_required(obj, artifacts["watcher_challenge"]["required_fields"], label, errors)
            elif name == "watcher_state.json":
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                _check_required(obj, artifacts["watcher_state"]["required_fields"], label, errors)
                if obj.get("status") not in ("MEASURED", "UNVERIFIED"):
                    errors.append("%s: status=%r not MEASURED|UNVERIFIED" % (label, obj.get("status")))
            elif name == "queue_state.json":
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                _check_required(obj, artifacts["drain_queue_state"]["required_fields"], label, errors)
                for r in obj.get("rounds") or []:
                    _check_required(r, artifacts["drain_queue_state"]["round_required_fields"],
                                     "%s: round %s" % (label, r.get("round", "?")), errors)


# ---------------------------------------------------------------------------
# Harness 1: subprocess against the real hooks/loop_stop.py
# ---------------------------------------------------------------------------

def _copy_orchestrator_tree(fixture_dir, tmp_dir):
    src = os.path.join(fixture_dir, ".simplicio-loop/orchestrator")
    if os.path.isdir(src):
        shutil.copytree(src, os.path.join(tmp_dir, ".simplicio-loop/orchestrator"))


def _read_scratchpad_iteration(tmp_dir):
    path = os.path.join(tmp_dir, ".simplicio-loop/orchestrator", "loop", "scratchpad.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^iteration:\s*(\d+)", text, re.M)
    return int(m.group(1)) if m else None


def run_hook_fixture(fixture_dir, expected, errors, name):
    if not os.path.exists(LOOP_STOP):
        errors.append("%s: hooks/loop_stop.py not found — cannot run the real hook" % name)
        return
    stdin_path = os.path.join(fixture_dir, "stdin.json")
    if not os.path.exists(stdin_path):
        errors.append("%s: missing stdin.json" % name)
        return
    with open(stdin_path, encoding="utf-8") as f:
        stdin_text = f.read()

    tmp_dir = tempfile.mkdtemp(prefix="loop-contract-")
    try:
        _copy_orchestrator_tree(fixture_dir, tmp_dir)
        try:
            r = subprocess.run(
                [sys.executable, LOOP_STOP], cwd=tmp_dir, input=stdin_text,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            )
        except subprocess.TimeoutExpired:
            errors.append("%s: hooks/loop_stop.py timed out" % name)
            return

        exp = expected.get("expected", {})
        if "returncode" in exp and r.returncode != exp["returncode"]:
            errors.append("%s: returncode=%d, want %d (stderr: %s)" %
                           (name, r.returncode, exp["returncode"], r.stderr[:300]))
        if "stdout" in exp and r.stdout != exp["stdout"]:
            errors.append("%s: stdout=%r, want %r" % (name, r.stdout[:200], exp["stdout"]))
        if exp.get("stdout_is_json"):
            try:
                payload = json.loads(r.stdout)
            except ValueError:
                errors.append("%s: stdout is not valid JSON: %r" % (name, r.stdout[:200]))
                payload = {}
            for k, v in (exp.get("stdout_json_contains") or {}).items():
                if payload.get(k) != v:
                    errors.append("%s: stdout JSON key %r = %r, want %r" %
                                   (name, k, payload.get(k), v))

        for rel, want in (exp.get("files_after") or {}).items():
            path = os.path.join(tmp_dir, rel)
            present = os.path.exists(path)
            if want == "present" and not present:
                errors.append("%s: expected %s to be present, but it is absent" % (name, rel))
            if want == "absent" and present:
                errors.append("%s: expected %s to be absent, but it is present" % (name, rel))

        if "scratchpad_iteration_after" in exp:
            got = _read_scratchpad_iteration(tmp_dir)
            want = exp["scratchpad_iteration_after"]
            if got != want:
                errors.append("%s: scratchpad iteration after=%r, want %r" % (name, got, want))

        handoff_needles = exp.get("handoff_contains") or []
        if handoff_needles:
            handoff_path = os.path.join(tmp_dir, ".simplicio-loop/orchestrator", "loop", "HANDOFF.md")
            handoff_text = ""
            if os.path.exists(handoff_path):
                with open(handoff_path, encoding="utf-8") as f:
                    handoff_text = f.read()
            for needle in handoff_needles:
                if needle not in handoff_text:
                    errors.append("%s: HANDOFF.md missing expected text %r" % (name, needle))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Harness 2: pure functions from scripts/loop_journal.py
# ---------------------------------------------------------------------------

def _import_loop_journal():
    import loop_journal  # noqa: local import — scripts/ is on sys.path (see top of file)
    return loop_journal


def run_stall_fixture(fixture_dir, expected, errors, name):
    lj = _import_loop_journal()
    journal_path = os.path.join(fixture_dir, "journal.jsonl")
    rows = []
    with open(journal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    k = expected.get("harness_invocation", {}).get("k", 3)
    verdict = lj.analyze(rows, k)
    exp = expected.get("expected", {})
    for key, want in exp.items():
        got = verdict.get(key)
        if got != want:
            errors.append("%s: analyze()[%r]=%r, want %r" % (name, key, got, want))


def run_journal_minimal_fixture(fixture_dir, expected, errors, name):
    lj = _import_loop_journal()
    exp = expected.get("expected", {})

    def _fp(rel):
        with open(os.path.join(fixture_dir, rel), encoding="utf-8") as f:
            return lj.fingerprint(f.read())

    got1 = _fp("gate_output_1.txt")
    got2 = _fp("gate_output_2.txt")
    if "fingerprint_gate_output_1" in exp and got1 != exp["fingerprint_gate_output_1"]:
        errors.append("%s: fingerprint(gate_output_1)=%r, want %r" %
                       (name, got1, exp["fingerprint_gate_output_1"]))
    if "fingerprint_gate_output_2" in exp and got2 != exp["fingerprint_gate_output_2"]:
        errors.append("%s: fingerprint(gate_output_2)=%r, want %r" %
                       (name, got2, exp["fingerprint_gate_output_2"]))
    if got1 != got2:
        errors.append("%s: the two recurring-bug texts fingerprint DIFFERENTLY (%r != %r) — "
                       "stability invariant broken" % (name, got1, got2))

    journal_path = os.path.join(fixture_dir, "journal.jsonl")
    rows = []
    with open(journal_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    want_fps = exp.get("journal_fingerprints")
    if want_fps is not None:
        got_fps = [r.get("fingerprint") for r in rows]
        if got_fps != want_fps:
            errors.append("%s: journal fingerprints=%r, want %r" % (name, got_fps, want_fps))
    # append-only order: iteration must never decrease line over line
    prev = None
    for i, r in enumerate(rows, 1):
        it = r.get("iteration")
        if prev is not None and it < prev:
            errors.append("%s: line %d iteration=%r decreased from %r (not append-only order)" %
                           (name, i, it, prev))
        prev = it


# ---------------------------------------------------------------------------
# Harness 3: drain reference algorithm (see SCHEMA.md — no existing code to call)
# ---------------------------------------------------------------------------

def analyze_drain(rounds, k=2):
    """Reference drain verdict: DRAINED iff the trailing streak of dry rounds (claimed == [] AND
    in_flight == [] for that round) is >= k. This is NOT extracted from existing code — no drain
    scheduler tick is implemented in this repo; it mirrors the documented rule in
    .claude/skills/simplicio-loop/SKILL.md § "Two loop modes" and
    references/standing-loop-247.md § 3 ("dry counter").
    """
    streak = 0
    for r in reversed(rounds):
        if not r.get("claimed") and not r.get("in_flight"):
            streak += 1
        else:
            break
    drained = streak >= k
    return {
        "verdict": "DRAINED" if drained else "ACTIVE",
        "dry_streak": streak,
        "recommend": "idle-cheaply-wake-on-new-item" if drained else "continue-claiming",
    }


def run_drain_fixture(fixture_dir, expected, errors, name):
    with open(os.path.join(fixture_dir, "queue_state.json"), encoding="utf-8") as f:
        state = json.load(f)
    k = expected.get("harness_invocation", {}).get("k", state.get("k", 2))
    verdict = analyze_drain(state["rounds"], k)
    exp = expected.get("expected", {})
    for key, want in exp.items():
        got = verdict.get(key)
        if got != want:
            errors.append("%s: analyze_drain()[%r]=%r, want %r" % (name, key, got, want))


# ---------------------------------------------------------------------------
# Fixture registry + driver
# ---------------------------------------------------------------------------

FIXTURES = {
    "converge-success": run_hook_fixture,
    "stop-path": run_hook_fixture,
    "evidence-gated-done/satisfied": run_hook_fixture,
    "evidence-gated-done/withheld": run_hook_fixture,
    "converge-stall-escalation": run_stall_fixture,
    "journal-append-only-minimal": run_journal_minimal_fixture,
    "drain-empty-after-k-rounds": run_drain_fixture,
}


def validate(_opts=None):
    errors = []
    if not os.path.isdir(FIXTURES_DIR):
        print("FAIL: %s not found" % FIXTURES_DIR)
        return False

    schema = _load_schema()

    for name, runner in FIXTURES.items():
        fixture_dir = os.path.join(FIXTURES_DIR, *name.split("/"))
        if not os.path.isdir(fixture_dir):
            errors.append("%s: fixture directory missing (%s)" % (name, fixture_dir))
            continue

        # structural pass — every state file in the fixture must match schema.json
        schema_check_tree(fixture_dir, schema, errors)

        # behavioral pass — the fixture's own expected.json
        expected_path = os.path.join(fixture_dir, "expected.json")
        if not os.path.exists(expected_path):
            errors.append("%s: missing expected.json" % name)
            continue
        with open(expected_path, encoding="utf-8") as f:
            expected = json.load(f)

        before = len(errors)
        runner(fixture_dir, expected, errors, name)
        ok = len(errors) == before
        print("  [%s] %s" % ("ok" if ok else "XX", name))

    ok = not errors
    if errors:
        print("\ncheck_loop_contract: FAIL (%d issue(s))" % len(errors))
        for e in errors:
            print("  - %s" % e)
    else:
        print("\ncheck_loop_contract: PASS (%d fixtures)" % len(FIXTURES))
    return ok


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--describe-cli":
        print(json.dumps({
            "verbs": ["validate", "selftest"],
            "flags": ["--describe-cli"],
        }))
        sys.exit(0)
    # both bare invocation and 'selftest' run the same fixture validation — the fixtures
    # themselves ARE the self-test, there is no separate no-file unit-test mode to fall back to.
    ok = validate()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

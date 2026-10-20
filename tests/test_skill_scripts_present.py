"""Regression test for runtime#3304 — SKILL.md must not promise a worker the shipped
plugin doesn't have.

`.claude/skills/simplicio-loop/SKILL.md` describes the mechanized protocol by shelling out to
`scripts/<name>.py` (and `hooks/<name>.py`) paths. `scripts/mirror_manifest.py`'s `LEAN_SCRIPTS`/
`LEAN_HOOKS` decide what `scripts/sync_plugin.py` copies into `plugin/scripts/`+`plugin/hooks/` —
the actual marketplace-plugin mirror an installed user gets. If a script SKILL.md references
drops out of that lean list, the shipped skill breaks with an `ImportError`/`FileNotFoundError`
the first time it tries to invoke that worker, even though the repo-root `scripts/` copy works
fine. This test parses the script references of SKILL.md and of every `references/*.md` and asserts
each one actually exists in `plugin/scripts/`+`plugin/hooks/` (or is listed as source-checkout-only),
so that regression fails loudly here instead of silently shipping.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "SKILL.md")
PLUGIN_SCRIPTS = os.path.join(REPO, "plugin", "scripts")
PLUGIN_HOOKS = os.path.join(REPO, "plugin", "hooks")

REFERENCES_DIR = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "references")

_SCRIPT_REF_RE = re.compile(r"scripts/([A-Za-z0-9_.-]+\.py)")
_HOOK_REF_RE = re.compile(r"hooks/([A-Za-z0-9_.-]+\.py)")

# Scripts the skill's docs name that the lean plugin deliberately does not ship: the repo dev gate, the
# source-checkout adapters, the PR patrol and the in-process preflight. A pip customer has no scripts/ tree,
# so these are source-checkout-only. The list is pinned both ways by test_source_checkout_only_list_is_exact.
SOURCE_CHECKOUT_ONLY = frozenset({
    "agentsview_adapter.py", "az_boards_adapter.py", "check.py", "flow_gen.py", "install_services.py",
    "planning_gate.py", "pr_patrol.py", "preflight.py", "repo_conventions.py",
})


def _skill_text():
    with open(SKILL_MD, "r", encoding="utf-8") as f:
        return f.read()


def _references_by_script():
    """Map each scripts/<name>.py that SKILL.md or any references/*.md names to the docs naming it."""
    docs = {SKILL_MD: _skill_text()}
    for name in sorted(os.listdir(REFERENCES_DIR)):
        if name.endswith(".md"):
            with open(os.path.join(REFERENCES_DIR, name), "r", encoding="utf-8") as f:
                docs[os.path.join(REFERENCES_DIR, name)] = f.read()
    named = {}
    for path, text in docs.items():
        for name in set(_SCRIPT_REF_RE.findall(text)):
            named.setdefault(name, []).append(os.path.relpath(path, REPO))
    return named


def test_skill_md_exists():
    assert os.path.isfile(SKILL_MD), "expected %s to exist" % SKILL_MD


def test_every_referenced_script_is_shipped_in_plugin():
    # SKILL.md and every references/*.md ship with the plugin and are the protocol a consumer follows,
    # so each scripts/<name>.py they name must be in plugin/scripts/ (or be listed as source-checkout-only).
    # The guard fires only when a doc names a script the lean mirror fails to ship.
    missing = {name: docs for name, docs in sorted(_references_by_script().items())
               if name not in SOURCE_CHECKOUT_ONLY
               and not os.path.isfile(os.path.join(PLUGIN_SCRIPTS, name))}
    assert not missing, (
        f"the skill docs name scripts the plugin/scripts/ mirror does not ship: {missing} — add to "
        "LEAN_SCRIPTS in scripts/mirror_manifest.py and rerun scripts/sync_plugin.py (runtime#3304), "
        "or list it in SOURCE_CHECKOUT_ONLY with a reason"
    )


def test_source_checkout_only_list_is_exact():
    named = _references_by_script()
    shipped = sorted(name for name in SOURCE_CHECKOUT_ONLY
                     if os.path.isfile(os.path.join(PLUGIN_SCRIPTS, name)))
    stale = sorted(name for name in SOURCE_CHECKOUT_ONLY if name not in named)
    assert not shipped, f"now shipped, remove from SOURCE_CHECKOUT_ONLY: {shipped}"
    assert not stale, f"no doc names these any more, remove from SOURCE_CHECKOUT_ONLY: {stale}"


def test_every_referenced_hook_is_shipped_in_plugin():
    # SKILL.md's protocol no longer names hook scripts inline (hook wiring is documented
    # in hooks/README.md and wired by the installer instead) -- an empty reference set is
    # a legitimate current state, not a broken fixture; this guard only needs to fire when
    # SKILL.md *does* name a hooks/*.py path that the lean plugin mirror fails to ship.
    text = _skill_text()
    referenced = sorted(set(_HOOK_REF_RE.findall(text)))
    missing = [name for name in referenced
               if not os.path.isfile(os.path.join(PLUGIN_HOOKS, name))]
    assert not missing, (
        "SKILL.md references hooks/%s but plugin/hooks/ does not ship them — "
        "add to LEAN_HOOKS in scripts/mirror_manifest.py and rerun scripts/sync_plugin.py "
        "(runtime#3304)" % missing
    )


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals())

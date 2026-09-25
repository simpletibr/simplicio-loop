"""Regression test for runtime#3304 — SKILL.md must not promise a worker the shipped
plugin doesn't have.

`.claude/skills/simplicio-loop/SKILL.md` describes the mechanized protocol by shelling out to
`scripts/<name>.py` (and `hooks/<name>.py`) paths. `scripts/mirror_manifest.py`'s `LEAN_SCRIPTS`/
`LEAN_HOOKS` decide what `scripts/sync_plugin.py` copies into `plugin/scripts/`+`plugin/hooks/` —
the actual marketplace-plugin mirror an installed user gets. If a script SKILL.md references
drops out of that lean list, the shipped skill breaks with an `ImportError`/`FileNotFoundError`
the first time it tries to invoke that worker, even though the repo-root `scripts/` copy works
fine. This test parses SKILL.md's own references and asserts every one of them actually exists in
`plugin/scripts/`+`plugin/hooks/`, so that regression fails loudly here instead of silently
shipping.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = os.path.join(REPO, ".claude", "skills", "simplicio-loop", "SKILL.md")
PLUGIN_SCRIPTS = os.path.join(REPO, "plugin", "scripts")
PLUGIN_HOOKS = os.path.join(REPO, "plugin", "hooks")

_SCRIPT_REF_RE = re.compile(r"scripts/([A-Za-z0-9_.-]+\.py)")
_HOOK_REF_RE = re.compile(r"hooks/([A-Za-z0-9_.-]+\.py)")


def _skill_text():
    with open(SKILL_MD, "r", encoding="utf-8") as f:
        return f.read()


def test_skill_md_exists():
    assert os.path.isfile(SKILL_MD), "expected %s to exist" % SKILL_MD


def test_every_referenced_script_is_shipped_in_plugin():
    # SKILL.md's protocol is now expressed as `simplicio-loop` CLI subcommands
    # (orient/prepare/wave/tick/verify) rather than inline scripts/*.py invocations --
    # an empty reference set is a legitimate current state, not a broken fixture; this
    # guard only needs to fire when SKILL.md *does* name a scripts/*.py path that the
    # lean plugin mirror fails to ship.
    text = _skill_text()
    referenced = sorted(set(_SCRIPT_REF_RE.findall(text)))
    missing = [name for name in referenced
               if not os.path.isfile(os.path.join(PLUGIN_SCRIPTS, name))]
    assert not missing, (
        "SKILL.md references scripts/%s but plugin/scripts/ does not ship them — "
        "add to LEAN_SCRIPTS in scripts/mirror_manifest.py and rerun scripts/sync_plugin.py "
        "(runtime#3304)" % missing
    )


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

"""#1836 — static smoke test of the marketplace install path.

A real `/plugin marketplace add` + `/plugin install` cannot run in CI sandboxes, so this test
resolves the same references the marketplace install would follow, from the files on disk:
  .claude-plugin/marketplace.json -> plugins[].source -> plugin/.claude-plugin/plugin.json
  -> its "skills" and "hooks" paths -> every ${CLAUDE_PLUGIN_ROOT}/... command in the hooks file.
UNVERIFIED: an end-to-end install into a real Claude Code host is not run here.
"""
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CORE_SKILLS = (
    "simplicio-loop", "simplicio-tasks", "simplicio-orient", "simplicio-review",
    "simplicio-compress", "simplicio-learn", "simplicio-autoresearch",
)


def _json(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def _json_abs(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_plugin_dir():
    marketplace = _json(".claude-plugin/marketplace.json")
    entries = [p for p in marketplace["plugins"] if p["name"] == "simplicio-loop"]
    assert len(entries) == 1, "marketplace must list exactly one simplicio-loop plugin"
    source = entries[0]["source"]
    assert source.startswith("./"), "marketplace source must be a relative path: %r" % source
    plugin_dir = os.path.normpath(os.path.join(REPO, source))
    assert os.path.isdir(plugin_dir), "marketplace source does not resolve to a directory: %s" % plugin_dir
    return plugin_dir


def test_marketplace_source_resolves_to_a_plugin_with_a_manifest():
    plugin_dir = _resolve_plugin_dir()
    manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
    assert os.path.isfile(manifest), "no plugin manifest at %s" % manifest


def test_plugin_directory_ships_the_seven_core_skills_with_a_skill_file():
    skills_dir = os.path.join(_resolve_plugin_dir(), "skills")
    assert os.path.isdir(skills_dir)
    missing = [s for s in CORE_SKILLS if not os.path.isfile(os.path.join(skills_dir, s, "SKILL.md"))]
    assert not missing, "core skills missing from the marketplace plugin: %s" % missing


def test_every_path_referenced_by_plugin_json_exists():
    plugin_dir = _resolve_plugin_dir()
    manifest = _json_abs(os.path.join(plugin_dir, ".claude-plugin", "plugin.json"))
    refs = {k: v for k, v in manifest.items() if isinstance(v, str) and v.startswith("./")}
    assert {"skills", "hooks"} <= set(refs), "plugin.json must reference skills and hooks"
    for key, rel in refs.items():
        target = os.path.normpath(os.path.join(plugin_dir, rel))
        assert os.path.exists(target), "plugin.json %s -> %s does not exist" % (key, rel)


def test_hooks_file_is_valid_and_every_plugin_root_command_exists():
    plugin_dir = _resolve_plugin_dir()
    manifest = _json_abs(os.path.join(plugin_dir, ".claude-plugin", "plugin.json"))
    hooks_rel = manifest["hooks"]
    hooks = _json_abs(os.path.normpath(os.path.join(plugin_dir, hooks_rel)))
    commands = []
    for groups in hooks["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                if hook.get("type") == "command":
                    commands.append(hook["command"])
    assert commands, "the hooks file wires no command hooks"
    pattern = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")
    checked = 0
    for command in commands:
        for rel in pattern.findall(command):
            checked += 1
            assert os.path.isfile(os.path.join(plugin_dir, rel)), "hook command points at a missing file: %s" % rel
    assert checked == len(commands), "every hook command must be rooted at ${CLAUDE_PLUGIN_ROOT}"

"""#1410: hooks installed into a consumer project must fail loud, never crash or fail open.

A consumer receives `hooks/` (copied from the wheel's `_bundle`) but no `adapters/` tree and no
`scripts/`. These tests hold the shipped hooks to that layout.
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "hooks"
BUNDLE = REPO / "simplicio_loop" / "_bundle"
ADAPTER_SRC = REPO / "adapters" / "claude"

_DELIVERY = {
    "schema": "simplicio.delivery-contract/v1",
    "open_pr": False,
    "push_branch": True,
    "allow_new_files_in_repo": False,
    "allow_comments_in_code": False,
    "commit_message_convention": "#<id> - fix: <desc>",
}


def _consumer_with_prompt_hook(tmp_path: Path) -> Path:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("user_prompt_submit.py", "_dashboard_emit.py"):
        shutil.copy2(HOOKS / name, hooks / name)
    return hooks / "user_prompt_submit.py"


def _run_prompt_hook(script: Path, cwd: Path, payload: dict, preamble: str = ""):
    runner = (
        "import runpy, sys\n%s"
        "sys.argv = [sys.argv[1]]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n" % preamble
    )
    return subprocess.run(
        [sys.executable, "-c", runner, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, cwd=str(cwd),
    )


def _load_hook(name: str, tmp_name: str):
    spec = importlib.util.spec_from_file_location(tmp_name, HOOKS / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _anchor(root: Path) -> None:
    state = root / ".simplicio-loop" / "orchestrator" / "loop"
    state.mkdir(parents=True)
    (state / "anchor.json").write_text(json.dumps({"delivery": _DELIVERY}), encoding="utf-8")


def test_bundle_ships_claude_adapter():
    sources = [p for p in ADAPTER_SRC.rglob("*")
               if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    assert sources
    for src in sources:
        shipped = BUNDLE / "adapters" / "claude" / src.relative_to(ADAPTER_SRC)
        assert shipped.is_file(), "adapters/claude/%s missing from _bundle" % src.name
        assert shipped.read_bytes() == src.read_bytes()


def test_prompt_hook_runs_in_consumer_layout_without_adapters_tree(tmp_path):
    script = _consumer_with_prompt_hook(tmp_path)
    assert not (tmp_path / "adapters").exists()
    result = _run_prompt_hook(script, tmp_path, {"prompt": "hello"})
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert json.loads(result.stdout)["decision"] == "continue"


def test_prompt_hook_degrades_explicitly_when_adapter_import_fails(tmp_path):
    script = _consumer_with_prompt_hook(tmp_path)
    result = _run_prompt_hook(
        script, tmp_path, {"prompt": "hello"}, preamble="sys.modules['adapters'] = None\n"
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "UserPromptSubmit" in result.stderr
    assert "degraded" in result.stderr.lower()


def test_action_gate_treats_missing_delivery_module_as_contract_error(tmp_path, monkeypatch):
    gate = _load_hook("action_gate.py", "action_gate_import_error")
    _anchor(tmp_path)
    monkeypatch.setitem(sys.modules, "simplicio_loop.delivery_contract", None)
    contract, error = gate._delivery_contract(str(tmp_path))
    assert contract is None
    assert error and "delivery contract" in error
    assert gate._delivery_guard(str(tmp_path), "", False) == error


def test_loop_stop_treats_missing_delivery_module_as_contract_error(tmp_path, monkeypatch):
    hook = _load_hook("loop_stop.py", "loop_stop_import_error")
    _anchor(tmp_path)
    monkeypatch.setitem(sys.modules, "simplicio_loop.delivery_contract", None)
    reason = hook._delivery_stop_guard(str(tmp_path), 1)
    assert reason and "delivery contract" in reason


def test_hooks_readme_names_nothing_a_consumer_lacks():
    text = (HOOKS / "README.md").read_text(encoding="utf-8")
    for needle in ("GitHub Actions was removed", "mirror_manifest", "_bundle",
                   "plugin/", "docs/DASHBOARD_EVENTS.md", "install_lib"):
        assert needle not in text, needle
    assert "SIMPLICIO_PREPUSH_GATE" in text


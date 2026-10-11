"""The Stop hook warns the agent to hand off at the soft share of the input ceiling (#1608, part D)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HOOK = ROOT / "hooks" / "loop_stop.py"
CEILING = 98_000
SOFT = 88_200  # 90 % of CEILING
MIB = 1 << 20
TAIL_CAP = 8 * MIB


def load_hook():
    spec = importlib.util.spec_from_file_location("loop_stop_input_ceiling", HOOK)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ceiling(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SIMPLICIO_AGENT_INPUT_TOKEN_CEILING", str(CEILING))


def transcript(tmp_path, lines):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return str(path)


def assistant_usage(input_tokens):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}],
                                              "usage": {"input_tokens": input_tokens, "cache_read_input_tokens": 0,
                                                        "cache_creation_input_tokens": 0, "output_tokens": 5}}}


class MeteredFile:
    def __init__(self, handle, read):
        self._handle = handle
        self._read = read

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._handle.close()

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def read(self, size=-1):
        data = self._handle.read(size)
        self._read[0] += len(data)
        return data

    def __iter__(self):
        for line in self._handle:
            self._read[0] += len(line)
            yield line


def metered_open(read):
    def opener(*args, **kwargs):
        return MeteredFile(open(*args, **kwargs), read)
    return opener


def test_measured_input_at_the_soft_share_warns(tmp_path, ceiling):
    path = transcript(tmp_path, [assistant_usage(SOFT)])
    hint = load_hook().input_ceiling_hint({"transcript_path": path})
    assert "MEASURED" in hint
    assert "%d of %d tokens" % (SOFT, CEILING) in hint
    assert "at least 90% of the ceiling" in hint
    assert "simplicio-loop handoff write" in hint


def test_measured_input_below_the_soft_share_does_not_warn(tmp_path, ceiling):
    path = transcript(tmp_path, [assistant_usage(SOFT - 1)])
    assert load_hook().input_ceiling_hint({"transcript_path": path}) == ""


def test_a_host_without_measured_usage_warns_as_estimated(tmp_path, ceiling):
    long_turn = {"type": "user", "message": {"role": "user", "content": "hello " * 80_000}}
    path = transcript(tmp_path, [long_turn])
    hint = load_hook().input_ceiling_hint({"transcript_path": path})
    assert "ESTIMATED" in hint
    assert "no measured usage" in hint
    assert "MEASURED" not in hint
    assert "simplicio-loop handoff write" in hint


def test_a_measured_transcript_past_the_tail_cap_is_read_from_the_end_only(tmp_path, ceiling, monkeypatch):
    filler = {"type": "user", "message": {"role": "user", "content": "x" * 50_000}}
    path = transcript(tmp_path, [filler] * 200 + [assistant_usage(SOFT)])
    assert os.path.getsize(path) > TAIL_CAP
    module = load_hook()
    read = [0]
    monkeypatch.setattr(module, "open", metered_open(read), raising=False)
    hint = module.input_ceiling_hint({"transcript_path": path})
    assert "MEASURED" in hint
    assert "%d of %d tokens" % (SOFT, CEILING) in hint
    assert read[0] <= MIB


def test_an_estimate_past_the_tail_cap_reads_no_more_than_the_cap(tmp_path, ceiling, monkeypatch):
    filler = {"type": "user", "message": {"role": "user", "content": "x" * 50_000}}
    long_turn = {"type": "user", "message": {"role": "user", "content": "hello " * 80_000}}
    path = transcript(tmp_path, [filler] * 200 + [long_turn])
    assert os.path.getsize(path) > TAIL_CAP
    module = load_hook()
    read = [0]
    monkeypatch.setattr(module, "open", metered_open(read), raising=False)
    hint = module.input_ceiling_hint({"transcript_path": path})
    assert "ESTIMATED" in hint
    assert "no measured usage" in hint
    assert read[0] <= TAIL_CAP


def test_an_unreadable_default_branch_is_named_not_silently_dropped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIMPLICIO_AGENT_INPUT_TOKEN_CEILING", raising=False)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "https://example.invalid/repo.git"],
                   check=True)
    hint = load_hook().input_ceiling_hint({})
    assert "Input ceiling unreadable" in hint
    assert "origin/HEAD" in hint


def test_the_ceiling_module_imports_when_only_the_repo_root_holds_it(tmp_path):
    path = transcript(tmp_path, [assistant_usage(SOFT)])
    script = ("import importlib.util, sys\n"
              "spec = importlib.util.spec_from_file_location('loop_stop_root_only', sys.argv[1])\n"
              "module = importlib.util.module_from_spec(spec)\n"
              "spec.loader.exec_module(module)\n"
              "print(module.input_ceiling_hint({'transcript_path': sys.argv[2]}))\n")
    env = {**os.environ, "SIMPLICIO_AGENT_INPUT_TOKEN_CEILING": str(CEILING)}
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(HOOK), path], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=60)
    assert "MEASURED" in result.stdout, result.stderr

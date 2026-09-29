import importlib.util
import json
import os
import sys
import pathlib

import pytest

SCRIPT_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "supervisor_enforcement.py"
spec = importlib.util.spec_from_file_location("supervisor_enforcement", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = str(tmp_path / "supervisor_enforcement.json")
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_STATE_FILE", path)
    monkeypatch.delenv("SIMPLICIO_SUPERVISOR_I_UNDERSTAND", raising=False)
    return path


class Opts:
    pass


def test_default_state_is_disabled(state_file):
    state = mod.load_state(state_file)
    assert state["enabled"] is False
    assert state["rollout"]["mode"] == "shadow"


def test_status_reports_disabled_when_no_state_file(state_file, capsys):
    opts = Opts()
    opts.json = True
    rc = mod.cmd_status(opts)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["enabled"] is False


def test_enable_without_guard_is_refused(state_file):
    opts = Opts()
    opts.i_understand = False
    rc = mod.cmd_enable(opts)
    assert rc == 2
    assert mod.load_state(state_file)["enabled"] is False


def test_enable_with_guard_flag_succeeds(state_file):
    opts = Opts()
    opts.i_understand = True
    rc = mod.cmd_enable(opts)
    assert rc == 0
    assert mod.load_state(state_file)["enabled"] is True


def test_enable_with_env_guard_succeeds(state_file, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_I_UNDERSTAND", "1")
    opts = Opts()
    opts.i_understand = False
    rc = mod.cmd_enable(opts)
    assert rc == 0
    assert mod.load_state(state_file)["enabled"] is True


def test_disable_always_allowed(state_file):
    enable_opts = Opts()
    enable_opts.i_understand = True
    mod.cmd_enable(enable_opts)
    rc = mod.cmd_disable(Opts())
    assert rc == 0
    assert mod.load_state(state_file)["enabled"] is False


def test_detect_flags_unsupervised_simplicio_process():
    processes = [
        "simplicio-mapper --survey",
        "python3 unrelated_tool.py",
    ]
    flagged = mod.detect_unsupervised(processes)
    assert len(flagged) == 1
    assert flagged[0]["argv0"] == "simplicio-mapper --survey".split()[0]


def test_detect_ignores_supervised_process_by_env_marker():
    processes = [{"argv": ["mapper", "--survey"], "env": {"SIMPLICIO_SUPERVISED": "1"}}]
    assert mod.detect_unsupervised(processes) == []


def test_detect_ignores_supervised_process_by_marker_file(tmp_path):
    marker = tmp_path / "marker"
    marker.write_text("x")
    processes = [{"argv": ["mapper", "--survey"], "marker_file": str(marker)}]
    assert mod.detect_unsupervised(processes) == []


def test_detect_never_kills_anything(monkeypatch):
    killed = []
    monkeypatch.setattr(os, "kill", lambda *a, **k: killed.append(a))
    processes = ["simplicio-mapper --survey"]
    mod.detect_unsupervised(processes)
    assert killed == []


def test_rollout_rejects_unknown_mode(state_file):
    opts = Opts()
    opts.mode = "yolo"
    opts.percent = 0
    opts.allow = []
    rc = mod.cmd_rollout(opts)
    assert rc == 2


@pytest.mark.parametrize("mode", ["shadow", "canary", "full"])
def test_rollout_accepts_known_modes(state_file, mode):
    opts = Opts()
    opts.mode = mode
    opts.percent = 10
    opts.allow = []
    rc = mod.cmd_rollout(opts)
    assert rc == 0
    assert mod.load_state(state_file)["rollout"]["mode"] == mode


def test_rollout_persists_canary_percent_and_allowlist(state_file):
    opts = Opts()
    opts.mode = "canary"
    opts.percent = 30
    opts.allow = ["ws-a", "ws-b"]
    mod.cmd_rollout(opts)
    state = mod.load_state(state_file)
    assert state["rollout"]["canary_percent"] == 30
    assert state["rollout"]["canary_allowlist"] == ["ws-a", "ws-b"]


def test_missing_state_file_falls_back_to_disabled_safely(state_file):
    assert not os.path.exists(state_file)
    state = mod.load_state(state_file)
    assert state["enabled"] is False
    processes = ["simplicio-dev-cli --execute"]
    assert len(mod.detect_unsupervised(processes)) == 1


def test_corrupt_state_file_falls_back_to_disabled(state_file):
    with open(state_file, "w", encoding="utf-8") as handle:
        handle.write("not json{{{")
    state = mod.load_state(state_file)
    assert state["enabled"] is False


def test_selftest_passes():
    assert mod.cmd_selftest(Opts()) == 0


def test_scan_os_returns_none_when_psutil_absent(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert mod.scan_os_processes() is None


def test_detect_scan_os_graceful_skip_without_psutil(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    opts = Opts()
    opts.scan_os = True
    opts.input = None
    opts.json = False
    rc = mod.cmd_detect(opts)
    assert rc == 3


@pytest.mark.external_integration
def test_detect_scan_os_real_psutil_when_available():
    try:
        __import__("psutil")
    except ImportError:
        pytest.skip(
            "EXTERNAL_INTEGRATION_UNAVAILABLE[psutil]: "
            "install psutil to exercise the live operating-system process scan"
        )
    opts = Opts()
    opts.scan_os = True
    opts.input = None
    opts.json = True
    rc = mod.cmd_detect(opts)
    assert rc == 0


def test_rollout_emits_structured_event(state_file, tmp_path, monkeypatch):
    events_path = str(tmp_path / "events.jsonl")
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_EVENTS_FILE", events_path)
    opts = Opts()
    opts.mode = "canary"
    opts.percent = 15
    opts.allow = ["ws-x"]
    rc = mod.cmd_rollout(opts)
    assert rc == 0
    with open(events_path, "r", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle if line.strip()]
    assert len(lines) == 1
    assert lines[0]["schema"] == "simplicio.supervisor-enforcement-event/v1"
    assert lines[0]["mode"] == "canary"
    assert lines[0]["canary_percent"] == 15
    assert lines[0]["canary_allowlist"] == ["ws-x"]


def test_rollout_rejected_mode_does_not_emit_event(state_file, tmp_path, monkeypatch):
    events_path = str(tmp_path / "events.jsonl")
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_EVENTS_FILE", events_path)
    opts = Opts()
    opts.mode = "bogus"
    opts.percent = 0
    opts.allow = []
    rc = mod.cmd_rollout(opts)
    assert rc == 2
    assert not os.path.exists(events_path)


def test_rollout_rejects_percent_out_of_bounds(state_file):
    opts = Opts()
    opts.mode = "canary"
    opts.percent = 101
    opts.allow = []
    rc = mod.cmd_rollout(opts)
    assert rc == 2
    opts.percent = -1
    rc = mod.cmd_rollout(opts)
    assert rc == 2


def test_is_supervised_by_argv_flag_on_dict_entry():
    entry = {"argv": ["mapper", "--survey", "--supervised-by=hub"], "env": {}}
    assert mod.is_supervised(entry) is True
    assert mod.detect_unsupervised([entry]) == []


def test_is_supervised_returns_false_for_non_str_non_dict_entry():
    assert mod.is_supervised(12345) is False
    assert mod.is_supervised(None) is False


def test_argv0_falls_back_to_argv0_key_when_argv_missing():
    entry = {"argv0": "simplicio-dev-cli"}
    assert mod._argv0(entry) == "simplicio-dev-cli"


def test_argv0_empty_for_unrecognized_entry_type():
    assert mod._argv0(12345) == ""
    assert mod._argv0(None) == ""


def test_detect_skips_entries_with_no_argv0():
    processes = [{"argv": []}, "simplicio-mapper --survey"]
    flagged = mod.detect_unsupervised(processes)
    assert len(flagged) == 1
    assert flagged[0]["argv0"] == "simplicio-mapper"


def test_cmd_detect_reads_input_file(tmp_path, state_file, capsys):
    input_path = tmp_path / "procs.json"
    input_path.write_text(json.dumps(["simplicio-mapper --survey", "python3 unrelated.py"]))
    opts = Opts()
    opts.input = str(input_path)
    opts.scan_os = False
    opts.json = True
    rc = mod.cmd_detect(opts)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["scanned"] == 2
    assert len(out["unsupervised"]) == 1


def test_cmd_detect_input_file_invalid_json(tmp_path, state_file):
    input_path = tmp_path / "procs.json"
    input_path.write_text("not json{{{")
    opts = Opts()
    opts.input = str(input_path)
    opts.scan_os = False
    opts.json = True
    rc = mod.cmd_detect(opts)
    assert rc == 2


def test_cmd_detect_input_file_not_a_list(tmp_path, state_file):
    input_path = tmp_path / "procs.json"
    input_path.write_text(json.dumps({"not": "a list"}))
    opts = Opts()
    opts.input = str(input_path)
    opts.scan_os = False
    opts.json = True
    rc = mod.cmd_detect(opts)
    assert rc == 2


def test_cmd_detect_reads_stdin_when_no_input_or_scan_os(monkeypatch, state_file, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["simplicio-mapper --survey"])))
    opts = Opts()
    opts.input = None
    opts.scan_os = False
    opts.json = False
    rc = mod.cmd_detect(opts)
    captured = capsys.readouterr().out
    assert rc == 0
    assert "unsupervised simplicio processes: 1" in captured
    assert "simplicio-mapper" in captured


def test_cmd_detect_stdin_invalid_json(monkeypatch, state_file):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json{{{"))
    opts = Opts()
    opts.input = None
    opts.scan_os = False
    opts.json = False
    rc = mod.cmd_detect(opts)
    assert rc == 2


def test_cmd_detect_stdin_not_a_list(monkeypatch, state_file):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"not": "a list"})))
    opts = Opts()
    opts.input = None
    opts.scan_os = False
    opts.json = False
    rc = mod.cmd_detect(opts)
    assert rc == 2


def test_cmd_status_text_output_canary(state_file, capsys):
    rollout_opts = Opts()
    rollout_opts.mode = "canary"
    rollout_opts.percent = 40
    rollout_opts.allow = ["ws-a"]
    mod.cmd_rollout(rollout_opts)

    opts = Opts()
    opts.json = False
    rc = mod.cmd_status(opts)
    out = capsys.readouterr().out
    assert rc == 0
    assert "rollout: canary" in out
    assert "canary_percent: 40" in out
    assert "governor" not in out


def test_metrics_reports_zero_transitions_when_no_events_file(state_file, tmp_path, capsys):
    opts = Opts()
    opts.json = True
    opts.events_file = str(tmp_path / "nope.jsonl")
    rc = mod.cmd_metrics(opts)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["total_transitions"] == 0
    assert out["transitions_by_mode"] == {"shadow": 0, "canary": 0, "full": 0}
    assert out["last_transition"] is None


def test_metrics_aggregates_real_rollout_events(state_file, tmp_path, monkeypatch):
    events_path = str(tmp_path / "events.jsonl")
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_EVENTS_FILE", events_path)

    for mode, percent in [("shadow", 0), ("canary", 10), ("canary", 25), ("full", 100)]:
        opts = Opts()
        opts.mode = mode
        opts.percent = percent
        opts.allow = []
        assert mod.cmd_rollout(opts) == 0

    metrics_opts = Opts()
    metrics_opts.json = True
    metrics_opts.events_file = events_path
    rc = mod.cmd_metrics(metrics_opts)
    events = mod.load_rollout_events(events_path)
    summary = mod.summarize_rollout_events(events)
    assert rc == 0
    assert summary["total_transitions"] == 4
    assert summary["transitions_by_mode"] == {"shadow": 1, "canary": 2, "full": 1}
    assert summary["last_transition"]["mode"] == "full"
    assert summary["last_transition"]["canary_percent"] == 100


def test_load_rollout_events_skips_corrupt_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"schema": "simplicio.supervisor-enforcement-event/v1", "mode": "canary", "ts": 1.0, "canary_percent": 5}\n'
        "not json{{{\n"
        "\n"
    )
    events = mod.load_rollout_events(str(path))
    assert len(events) == 1
    assert events[0]["mode"] == "canary"


def test_metrics_text_output(state_file, tmp_path, monkeypatch, capsys):
    events_path = str(tmp_path / "events.jsonl")
    monkeypatch.setenv("SIMPLICIO_SUPERVISOR_EVENTS_FILE", events_path)
    rollout_opts = Opts()
    rollout_opts.mode = "canary"
    rollout_opts.percent = 20
    rollout_opts.allow = []
    mod.cmd_rollout(rollout_opts)

    opts = Opts()
    opts.json = False
    opts.events_file = events_path
    rc = mod.cmd_metrics(opts)
    out = capsys.readouterr().out
    assert rc == 0
    assert "total rollout transitions: 1" in out
    assert "canary: 1" in out
    assert "last transition: mode=canary percent=20" in out


"""#1643: the plan request shows the window of the target, not the beginning of the file."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from simplicio_loop import input_ceiling, turbo, turbo_window

N = turbo_window.CONTEXT_LINES


def _py(count: int, target_at: int | None = None, name: str = "test_target_in_flight") -> str:
    """A python file of ``count`` filler functions; ``name`` is a 6-line test placed after filler ``target_at``."""
    out = ["import os", "", ""]
    for i in range(count):
        if i == target_at:
            out += [f"def {name}(tmp):", "    a = 1", "    b = a + 1", "    assert b == 2", "    return b", "", ""]
        out += [f"def helper_{i}(x):", f"    value = x + {i}", "    return value * 2", "", ""]
    return "\n".join(out) + "\n"


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return path


def _task(text: str, target: str, context=()) -> dict:
    return {"index": 1, "text": text, "target": target, "context": list(context)}


def _lines(body: str) -> list[str]:
    return re.findall(r"[^\n]*\n|[^\n]+", body)


def test_a_small_file_is_the_exact_string(tmp_path):
    _write(tmp_path, "a.py", "x = 1\ny = 2\n")
    files = turbo_window.build_files(tmp_path, [_task("Edit a.py", "a.py")])
    assert files == {"a.py": "x = 1\ny = 2\n"}


def test_a_small_crlf_file_keeps_its_line_endings_so_find_matches(tmp_path):
    _write(tmp_path, "a.py", "x = 1\r\ny = 2\r\n")
    assert turbo_window.build_files(tmp_path, [_task("Edit a.py", "a.py")])["a.py"] == "x = 1\r\ny = 2\r\n"


def test_a_big_file_with_the_symbol_at_the_end_shows_the_whole_body_and_the_line_range(tmp_path):
    body = _py(900, target_at=890)
    assert len(body) > turbo_window.FILE_CHARS_MAX
    _write(tmp_path, "tests/test_big.py", body)
    task = _task("test_target_in_flight is flaky in tests/test_big.py", "tests/test_big.py")
    entry = turbo_window.build_files(tmp_path, [task])["tests/test_big.py"]
    assert isinstance(entry, dict) and entry["total_lines"] == len(_lines(body))
    shown = "".join(w["text"] for w in entry["windows"])
    assert "def test_target_in_flight(tmp):\n    a = 1\n    b = a + 1\n    assert b == 2\n    return b\n" in shown
    window = next(w for w in entry["windows"] if "def test_target_in_flight" in w["text"])
    first = body.index("def test_target_in_flight")
    start_line = body[:first].count("\n") + 1
    assert window["start"] <= start_line - N and window["end"] >= start_line + 4 + N - 1  # the body and N lines around
    assert entry["omitted"] and "more" in entry
    assert entry["windows"][0]["start"] == 1 and entry["windows"][0]["end"] == turbo_window.HEADER_LINES  # the header


def _with_function(body_lines: int) -> tuple[str, int]:
    """900 filler functions, then ``def long_target_fn`` with ``body_lines`` body lines; returns (text, def line)."""
    head = _py(900)
    at = head.count("\n") + 1
    body = "".join(f"    step_{i} = {i}\n" for i in range(body_lines))
    return head + "def long_target_fn(a):\n" + body + "    return a\n\n\ndef after_fn():\n    return 1\n", at


def test_a_long_function_is_shown_with_its_whole_body_and_not_beyond(tmp_path):
    text, at = _with_function(60)
    _write(tmp_path, "big.py", text)
    entry = turbo_window.build_files(tmp_path, [_task("change long_target_fn in big.py", "big.py")])["big.py"]
    window = next(w for w in entry["windows"] if "def long_target_fn" in w["text"])
    assert window["start"] == at - N and window["end"] == at + 61 + N and "    return a\n" in window["text"]
    assert "step_59 = 59\n" in window["text"]


def test_a_function_past_the_body_cap_gets_only_the_lines_around_its_def(tmp_path):
    text, at = _with_function(turbo_window.BODY_CAP_LINES + 50)
    _write(tmp_path, "big.py", text)
    entry = turbo_window.build_files(tmp_path, [_task("change long_target_fn in big.py", "big.py")])["big.py"]
    window = next(w for w in entry["windows"] if "def long_target_fn" in w["text"])
    assert (window["start"], window["end"]) == (at - N, at + N)


def test_a_decorated_or_multiline_signature_def_is_whole(tmp_path):
    text = _py(900) + "@decorator\ndef sig_target_fn(\n    a,\n    b,\n) -> int:\n" + "".join(
        f"    s{i} = {i}\n" for i in range(20)) + "    return a\n\n\nx = 1\n"
    _write(tmp_path, "big.py", text)
    entry = turbo_window.build_files(tmp_path, [_task("change sig_target_fn in big.py", "big.py")])["big.py"]
    shown = "".join(w["text"] for w in entry["windows"])
    assert "@decorator\ndef sig_target_fn(\n    a,\n    b,\n) -> int:\n" in shown and "    return a\n" in shown


def test_no_anchor_shows_the_beginning_and_the_rest_is_omitted(tmp_path):
    body = _py(900)
    _write(tmp_path, "big.py", body)
    entry = turbo_window.build_files(tmp_path, [_task("Edit big.py", "big.py")])["big.py"]
    assert entry["windows"][0]["start"] == 1 and entry["windows"][0]["text"].startswith("import os\n")
    last = entry["windows"][-1]["end"]
    assert entry["omitted"] == [{"start": last + 1, "end": entry["total_lines"]}]


def test_a_common_word_does_not_anchor(tmp_path):
    body = _py(900) + "\nvalue = 3\n"
    _write(tmp_path, "big.py", body)
    entry = turbo_window.build_files(tmp_path, [_task("change the value in big.py", "big.py")])["big.py"]
    assert entry["windows"][-1]["end"] < entry["total_lines"] - 100  # `value` is a plain word: no window at the end


def test_path_line_and_range_anchor(tmp_path):
    _write(tmp_path, "big.py", _py(900))
    one = turbo_window.build_files(tmp_path, [_task("look at big.py:2000", "big.py")])["big.py"]
    assert any(w["start"] <= 2000 - N and w["end"] >= 2000 + N for w in one["windows"])
    rng = turbo_window.build_files(tmp_path, [_task("look at big.py:2000-2010", "big.py")])["big.py"]
    assert any(w["start"] <= 2000 - N and w["end"] >= 2010 + N for w in rng["windows"])


def test_windows_merge_when_they_overlap_touch_or_are_one_line_apart(tmp_path):
    lines = [f"line_{i} = {i}\n" for i in range(1, 2001)]
    at = (500, 520, 538, 700, 1000, 1010, 1100, 1117)  # MAX_ANCHORS = 8
    for number in at:
        lines[number - 1] = f"def anchor_{number}():\n"
    _write(tmp_path, "m.py", "".join(lines))
    entry = turbo_window.build_files(tmp_path, [_task("touch " + " ".join(f"anchor_{n}" for n in at) + " in m.py", "m.py")])["m.py"]
    spans = [(w["start"], w["end"]) for w in entry["windows"] if w["start"] > 20]
    assert spans == [(492, 508),  # 500 alone
                     (512, 546),  # 520 and 538: one line apart (529) -> one window
                     (692, 708),  # 700 alone
                     (992, 1018),  # 1000 and 1010 overlap
                     (1092, 1125)]  # 1100 and 1117 touch


def test_windows_two_lines_apart_stay_two_windows(tmp_path):
    lines = [f"line_{i} = {i}\n" for i in range(1, 2001)]
    for number in (1300, 1319):
        lines[number - 1] = f"def anchor_{number}():\n"
    _write(tmp_path, "m.py", "".join(lines))
    entry = turbo_window.build_files(tmp_path, [_task("touch anchor_1300 anchor_1319 in m.py", "m.py")])["m.py"]
    assert [(w["start"], w["end"]) for w in entry["windows"] if w["start"] > 20] == [(1292, 1308), (1311, 1327)]


def test_the_explicit_window_adds_exactly_those_lines(tmp_path):
    body = _py(900)
    _write(tmp_path, "big.py", body)
    spec = turbo_window.parse_window_spec("big.py:3000-3004")
    assert spec == {"path": "big.py", "start": 3000, "end": 3004}
    entry = turbo_window.build_files(tmp_path, [_task("Edit big.py", "big.py")], [spec])["big.py"]
    window = next(w for w in entry["windows"] if w["start"] <= 3000 <= w["end"])
    assert window["start"] == 3000 and window["end"] == 3004
    assert window["text"] == "".join(_lines(body)[2999:3004])


def test_an_explicit_window_on_a_file_no_task_names_adds_that_file(tmp_path):
    _write(tmp_path, "a.py", "a = 1\n")
    _write(tmp_path, "other.py", "".join(f"v{i} = {i}\n" for i in range(5000)))
    spec = {"path": "other.py", "start": 10, "end": 12}
    files = turbo_window.build_files(tmp_path, [_task("Edit a.py", "a.py")], [spec])
    assert list(files) == ["a.py", "other.py"]
    assert any(w["text"] == "v9 = 9\nv10 = 10\nv11 = 11\n" for w in files["other.py"]["windows"])


@pytest.mark.parametrize("bad", ["x.py", "x.py:0-3", "x.py:9-3", "x.py:a-b", ":3-4", "../x.py:1-2", ".git/config:1-2"])
def test_bad_window_specs_are_refused(bad):
    with pytest.raises(ValueError):
        turbo_window.parse_window_spec(bad)


def test_parse_need(tmp_path):
    assert turbo_window.parse_need(None) == []
    assert turbo_window.parse_need([{"path": "a.py", "start": 3, "end": 9}]) == [{"path": "a.py", "start": 3, "end": 9}]
    for bad in ("x", [{"path": "a.py", "start": 3}], [{"path": "a.py", "start": 5, "end": 2}], [{"path": "/etc/passwd", "start": 1, "end": 2}]):
        with pytest.raises(ValueError):
            turbo_window.parse_need(bad)


def test_the_whole_files_object_never_passes_the_budget(tmp_path):
    names = []
    for i in range(6):
        names.append(f"pkg/m{i}.py")
        _write(tmp_path, names[-1], _py(3000, target_at=2990, name=f"target_{i}_thing"))
    tasks = [_task(" ".join(f"target_{i}_thing" for i in range(6)) + " in " + " ".join(names), names[0], names[1:])]
    files = turbo_window.build_files(tmp_path, tasks)
    ceiling = input_ceiling.resolve_ceiling(tmp_path)
    used = input_ceiling.estimate_tokens(json.dumps(files, ensure_ascii=False))
    assert used <= ceiling * turbo_window.BUDGET_PERCENT // 100
    assert set(files) == set(names) and all(isinstance(v, dict) for v in files.values())
    assert all("def target_%d_thing" % i in "".join(w["text"] for w in files[n]["windows"]) for i, n in enumerate(names))


def test_a_smaller_ceiling_makes_a_smaller_request(tmp_path, monkeypatch):
    _write(tmp_path, "big.py", _py(3000))
    task = _task("Edit big.py", "big.py")
    wide = len(json.dumps(turbo_window.build_files(tmp_path, [task])))
    monkeypatch.setenv(input_ceiling.ENV_NAME, "6000")
    small = turbo_window.build_files(tmp_path, [task])
    assert input_ceiling.estimate_tokens(json.dumps(small)) <= 6000 * turbo_window.BUDGET_PERCENT // 100
    assert len(json.dumps(small)) < wide


def test_many_files_beyond_the_budget_become_header_only_in_task_order(tmp_path, monkeypatch):
    monkeypatch.setenv(input_ceiling.ENV_NAME, "2000")
    names = []
    for i in range(40):
        names.append(f"f{i}.py")
        _write(tmp_path, names[-1], _py(400))
    files = turbo_window.build_files(tmp_path, [_task("Edit " + " ".join(names), names[0], names[1:])])
    assert input_ceiling.estimate_tokens(json.dumps(files)) <= 800
    assert list(files) == names and files[names[0]]["windows"]


def test_truncated_lists_files_with_omitted_lines(tmp_path):
    _write(tmp_path, "small.py", "a = 1\n")
    _write(tmp_path, "big.py", _py(900))
    files = turbo_window.build_files(tmp_path, [_task("Edit big.py small.py", "big.py", ["small.py"])])
    assert turbo_window.truncated(files) == ["big.py"]


def test_the_provider_message_carries_the_same_window(tmp_path):
    body = _py(900, target_at=890)
    _write(tmp_path, "big.py", body)
    task = _task("test_target_in_flight in big.py", "big.py")
    content = turbo.task_message([task], tmp_path)["content"]
    assert "def test_target_in_flight(tmp):" in content and "[truncated" not in content
    for chunk in re.findall(r"\[lines \d+-\d+\]\n(.*?)(?=\n\[lines |\n\[not shown|\Z)", content, re.S):
        assert chunk in body


# --- property tests: seeded, no hypothesis in the repo ------------------------------------------------------

def _random_file(rng: random.Random) -> tuple[str, int, str]:
    eol = rng.choice(["\n", "\r\n"])
    pieces = ["x = 1", "def f(a):", "    return a", "# ção ñ ü — 日本語", "é" * rng.randint(1, 40), "", "    " * 3 + "pass"]
    count = rng.randint(600, 1800)
    lines = []
    for _ in range(count):
        line = rng.choice(pieces)
        if rng.random() < 0.01:
            line = "L" * rng.randint(500, 3000)  # a very long line
        lines.append(line)
    at = rng.randint(1, count - 8)
    name = f"zz_target_{rng.randint(0, 10**6)}"
    lines[at - 1: at + 3] = [f"def {name}(q):", "    r = q", "    return r", ""]
    body = eol.join(lines) + (eol if rng.random() < 0.5 else "")
    return body, at, name


def test_property_windows_are_exact_ordered_and_cover_the_file(tmp_path):
    rng = random.Random(1643)
    checked = 0
    for case in range(220):
        body, at, name = _random_file(rng)
        path = tmp_path / f"c{case}.py"
        path.write_bytes(body.encode("utf-8"))
        files = turbo_window.build_files(tmp_path, [_task(f"fix {name} in c{case}.py", f"c{case}.py")])
        entry = files[f"c{case}.py"]
        lines = _lines(body)
        if isinstance(entry, str):
            assert entry == body
            continue
        checked += 1
        windows, omitted = entry["windows"], entry["omitted"]
        # P1: the target (def line and its three-line body) appears, with the context lines around it that fit
        shown = {n for w in windows for n in range(w["start"], w["end"] + 1)}
        assert set(range(at, at + 3)) <= shown, (case, at)
        # P2: any sub-piece of a window text is in the original file; the whole text of a window is, byte for byte
        for w in windows:
            assert w["text"] in body
            sub_from = rng.randint(0, len(w["text"]) // 2)
            assert w["text"][sub_from: sub_from + 80] in body
        # P3: ordered, disjoint, coherent with the text
        previous = 0
        for w in windows:
            assert w["start"] > previous and w["end"] >= w["start"]
            assert w["text"] == "".join(lines[w["start"] - 1: w["end"]])
            previous = w["end"]
        # P4: windows + omitted cover 1..total_lines with no gap and no overlap
        spans = sorted([(w["start"], w["end"]) for w in windows] + [(o["start"], o["end"]) for o in omitted])
        assert spans[0][0] == 1 and spans[-1][1] == entry["total_lines"] == len(lines)
        assert all(b[0] == a[1] + 1 for a, b in zip(spans, spans[1:]))
        assert entry["total_chars"] == len(body)
    assert checked >= 150


# --- the CLI: --window, need, turbo_context_truncated -----------------------------------------------------------

import io
import sys

from simplicio_loop.cli_impl import main as cli_main


@pytest.fixture
def repo(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    monkeypatch.delenv(input_ceiling.ENV_NAME, raising=False)
    _write(tmp_path, "big.py", _py(900, target_at=5))
    _write(tmp_path, "small.py", "a = 1\n")
    return tmp_path


def _cli(capsys, *argv):
    rc = cli_main(["turbo", *argv])
    return rc, json.loads(capsys.readouterr().out)


def _stdin(monkeypatch, text: str):
    class In:
        buffer = io.BytesIO(text.encode("utf-8"))
        def isatty(self):
            return False
    monkeypatch.setattr(sys, "stdin", In())


def test_the_window_flag_adds_those_lines_to_the_request(repo, capsys):
    rc, out = _cli(capsys, "--repo", str(repo), "--task", "Edit big.py", "--window", "big.py:3000-3004")
    entry = out["files"]["big.py"]
    assert rc == 0 and any((w["start"], w["end"]) == (3000, 3004) for w in entry["windows"])
    assert "need" in out["rules"]


def test_a_bad_window_is_blocked(repo, capsys):
    rc, out = _cli(capsys, "--repo", str(repo), "--task", "Edit big.py", "--window", "big.py:9-3")
    assert rc == 2 and out["status"] == "blocked" and out["reason_code"] == "turbo_window_invalid"


def test_a_need_plan_applies_nothing_and_prints_the_request_again_for_the_same_run(repo, capsys, monkeypatch):
    rc, first = _cli(capsys, "--repo", str(repo), "--task", "Edit big.py", "--verify", "true")
    before = (repo / "big.py").read_bytes()
    _stdin(monkeypatch, json.dumps({"operations": [], "need": [{"path": "big.py", "start": 3000, "end": 3004}]}))
    rc, again = _cli(capsys, "--repo", str(repo), "--apply", "-", "--run-id", first["run_id"])
    assert rc == 0 and again["status"] == "needs_plan" and again["run_id"] == first["run_id"]
    assert any((w["start"], w["end"]) == (3000, 3004) for w in again["files"]["big.py"]["windows"])
    assert "--verify true" in again["apply"] and (repo / "big.py").read_bytes() == before
    _stdin(monkeypatch, json.dumps({"operations": [], "need": [{"path": "big.py", "start": 4000, "end": 4002}]}))
    rc, third = _cli(capsys, "--repo", str(repo), "--apply", "-", "--run-id", first["run_id"])
    spans = [(w["start"], w["end"]) for w in third["files"]["big.py"]["windows"]]
    assert (3000, 3004) in spans and (4000, 4002) in spans  # the asks add up


def test_an_empty_plan_over_a_cut_request_is_turbo_context_truncated(repo, capsys, monkeypatch):
    rc, first = _cli(capsys, "--repo", str(repo), "--task", "Edit big.py")
    _stdin(monkeypatch, json.dumps({"operations": []}))
    rc, out = _cli(capsys, "--repo", str(repo), "--apply", "-", "--run-id", first["run_id"])
    assert rc == 1 and out["status"] == "failed" and out["reason_code"] == "turbo_context_truncated"
    assert "big.py" in out["detail"]


def test_an_empty_plan_over_a_whole_request_stays_malformed(repo, capsys, monkeypatch):
    rc, first = _cli(capsys, "--repo", str(repo), "--task", "Edit small.py")
    _stdin(monkeypatch, json.dumps({"operations": []}))
    rc, out = _cli(capsys, "--repo", str(repo), "--apply", "-", "--run-id", first["run_id"])
    assert rc == 1 and out["reason_code"] == "turbo_plan_malformed"


def test_a_need_for_a_path_outside_the_repo_is_malformed(repo, capsys, monkeypatch):
    rc, first = _cli(capsys, "--repo", str(repo), "--task", "Edit big.py")
    _stdin(monkeypatch, json.dumps({"operations": [], "need": [{"path": "../x.py", "start": 1, "end": 2}]}))
    rc, out = _cli(capsys, "--repo", str(repo), "--apply", "-", "--run-id", first["run_id"])
    assert rc == 1 and out["reason_code"] == "turbo_plan_malformed"


def test_the_whole_request_stays_under_the_ceiling_with_several_huge_files(repo, capsys):
    names = []
    for i in range(6):
        names.append(f"huge{i}.py")
        _write(repo, names[-1], _py(4000, target_at=3990, name=f"hugefn_{i}_x"))
    rc, out = _cli(capsys, "--repo", str(repo), "--task", "Edit " + " ".join(names) + " hugefn_0_x hugefn_5_x")
    assert rc == 0
    assert input_ceiling.estimate_tokens(json.dumps(out, ensure_ascii=False)) < input_ceiling.DEFAULT_CEILING
    assert "def hugefn_5_x" in "".join(w["text"] for w in out["files"]["huge5.py"]["windows"])

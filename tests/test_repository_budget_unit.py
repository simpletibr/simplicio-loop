"""Repository size budget guard (#294) — proves the guard reports tracked-tree size and FAILS on
a regression, while grandfathering pre-existing oversized files instead of retroactively failing
on history it did not create.

Scope note: this guard measures/gates the CURRENT tracked working tree only. It never touches git
history and never runs `git filter-repo` -- the #294 issue explicitly requires a separate,
maintainer-approved decision (backup, dry-run, communicated window) before any history rewrite.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(REPO, "scripts", "repository_budget.py")
BASELINE = os.path.join(REPO, "scripts", "repository_budget_baseline.json")


def _run(args, cwd=None):
    return subprocess.run([sys.executable, GUARD] + args, capture_output=True, text=True,
                          cwd=cwd or REPO, stdin=subprocess.DEVNULL)


def _init_scratch_repo(root):
    """Copy repository_budget.py into a fresh throwaway git repo and return its scripts/ dir."""
    scripts_dir = os.path.join(str(root), "scripts")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(GUARD, "rb") as src, open(os.path.join(scripts_dir, "repository_budget.py"), "wb") as dst:
        dst.write(src.read())
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(root), check=True)
    return scripts_dir


def _git_add_all(root):
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)


def test_baseline_is_committed_and_readable():
    assert os.path.exists(BASELINE), "scripts/repository_budget_baseline.json must be committed"
    with open(BASELINE, encoding="utf-8") as f:
        data = json.load(f)
    assert "total_bytes" in data and data["total_bytes"] > 0
    assert "tracked_file_count" in data
    assert "known_oversized_files" in data


def test_report_passes_against_committed_baseline():
    r = _run([])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "repository-budget: PASS" in r.stdout
    assert "largest tracked files" in r.stdout


def test_check_mode_is_quiet_on_pass():
    r = _run(["--check"])
    assert r.returncode == 0
    assert r.stdout.strip() == "", "quiet --check mode should print nothing on a passing run"


def test_scratch_repo_new_baseline_grandfathers_current_oversized_file(tmp_path):
    scripts_dir = _init_scratch_repo(tmp_path)
    # A pre-existing oversized file, present before the baseline is ever written.
    # Use a non-media extension so this test isolates baseline grandfathering.
    # Raw media/archive paths are rejected by an independent governance rule
    # even when their size was already known.
    big = tmp_path / "legacy-asset.txt"
    big.write_bytes(b"x" * (3 * 1024 * 1024))
    _git_add_all(tmp_path)

    r = subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                        "--update-baseline"], capture_output=True, text=True, cwd=str(tmp_path),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr

    with open(os.path.join(scripts_dir, "repository_budget_baseline.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    assert "legacy-asset.txt" in baseline["known_oversized_files"]

    # Now a plain check must PASS -- the file is grandfathered, not newly flagged.
    r2 = subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                        "--check"], capture_output=True, text=True, cwd=str(tmp_path),
                       stdin=subprocess.DEVNULL)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_scratch_repo_new_oversized_file_fails(tmp_path):
    scripts_dir = _init_scratch_repo(tmp_path)
    small = tmp_path / "readme.txt"
    small.write_text("hello\n", encoding="utf-8")
    _git_add_all(tmp_path)
    subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                    "--update-baseline"], cwd=str(tmp_path), check=True, capture_output=True)

    # Add a brand-new file over the per-file cap AFTER the baseline was written.
    big = tmp_path / "new-video.bin"
    big.write_bytes(b"x" * (3 * 1024 * 1024))
    _git_add_all(tmp_path)

    r = subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py")],
                       capture_output=True, text=True, cwd=str(tmp_path), stdin=subprocess.DEVNULL)
    assert r.returncode == 1, "a brand-new oversized tracked file must fail the gate: " + r.stdout
    assert "FAIL" in r.stdout
    assert "new-video.bin" in r.stdout


def test_scratch_repo_total_growth_past_threshold_fails(tmp_path):
    scripts_dir = _init_scratch_repo(tmp_path)
    f1 = tmp_path / "data.bin"
    f1.write_bytes(b"x" * (100 * 1024))
    _git_add_all(tmp_path)
    subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                    "--update-baseline"], cwd=str(tmp_path), check=True, capture_output=True)

    # Grow the total tracked tree well past the 25% threshold, without any single file crossing
    # the per-file cap, to isolate the total-size regression path.
    f2 = tmp_path / "data2.bin"
    f2.write_bytes(b"x" * (200 * 1024))
    _git_add_all(tmp_path)

    r = subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py")],
                       capture_output=True, text=True, cwd=str(tmp_path), stdin=subprocess.DEVNULL)
    assert r.returncode == 1, "total tree growth past threshold must fail the gate: " + r.stdout
    assert "FAIL" in r.stdout


def _load_guard_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("repository_budget_under_test", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_guard(cwd, args=(), script_dir=None):
    script = os.path.join(script_dir or os.path.join(str(cwd), "scripts"), "repository_budget.py")
    return subprocess.run([sys.executable, script] + list(args), capture_output=True, text=True,
                          cwd=str(cwd), stdin=subprocess.DEVNULL)


def _scratch_with_base_file(tmp_path):
    # The 400 KB single-line pad keeps the baseline total large enough that adding a 9000-line
    # file stays under the total-growth threshold, so only the line rule can decide these tests.
    scripts_dir = _init_scratch_repo(tmp_path)
    (tmp_path / "small.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "pad.txt").write_text("a" * 400_000, encoding="utf-8")
    _git_add_all(tmp_path)
    subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                    "--update-baseline"], cwd=str(tmp_path), check=True, capture_output=True)
    return scripts_dir


def test_committed_baseline_records_the_line_cap_and_long_files():
    with open(BASELINE, encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("max_lines") == 9000
    assert isinstance(data.get("known_long_files"), dict)
    assert "simplicio_loop/runner.py" in data["known_long_files"]
    assert "packages/mapper/simplicio_mapper/store/neural/assets/seeds.sql" not in data["known_long_files"]


def test_scratch_new_text_file_over_the_line_cap_fails(tmp_path):
    scripts_dir = _scratch_with_base_file(tmp_path)
    (tmp_path / "huge.py").write_text("x = 1\n" * 9001, encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "huge.py" in r.stdout
    assert "repository-budget: FAIL" in r.stdout


def test_scratch_text_file_at_exactly_the_line_cap_passes(tmp_path):
    scripts_dir = _scratch_with_base_file(tmp_path)
    (tmp_path / "edge.py").write_text("x = 1\n" * 9000, encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 0, r.stdout + r.stderr


def test_scratch_unterminated_last_line_counts_as_a_line(tmp_path):
    # 9000 newline-terminated lines + one unterminated line = 9001 lines: must fail.
    scripts_dir = _scratch_with_base_file(tmp_path)
    (tmp_path / "tail.py").write_text("x = 1\n" * 9000 + "y = 2", encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tail.py" in r.stdout


def test_scratch_binary_file_is_not_counted_as_lines(tmp_path):
    scripts_dir = _scratch_with_base_file(tmp_path)
    (tmp_path / "blob.dat").write_bytes(b"\xff\xfe\x00\x81" + b"\n" * 20000)  # not UTF-8
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 0, r.stdout + r.stderr


def test_scratch_stray_nul_does_not_exempt_a_text_file_from_the_line_cap(tmp_path):
    scripts_dir = _scratch_with_base_file(tmp_path)
    (tmp_path / "sneaky.py").write_bytes(b"\0" + b"x = 1\n" * 9001)  # NUL is valid UTF-8 text
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "sneaky.py" in r.stdout


def _long_file_scratch(tmp_path, lines):
    scripts_dir = _init_scratch_repo(tmp_path)
    (tmp_path / "long.py").write_text("x = 1\n" * lines, encoding="utf-8")
    _git_add_all(tmp_path)
    subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                    "--update-baseline"], cwd=str(tmp_path), check=True, capture_output=True)
    with open(os.path.join(scripts_dir, "repository_budget_baseline.json"), encoding="utf-8") as f:
        assert json.load(f)["known_long_files"] == {"long.py": lines}
    return scripts_dir


def test_scratch_baselined_long_file_at_same_size_passes(tmp_path):
    scripts_dir = _long_file_scratch(tmp_path, 9500)
    r = _run_guard(tmp_path, ["--check"], script_dir=scripts_dir)
    assert r.returncode == 0, r.stdout + r.stderr


def test_scratch_baselined_long_file_that_grows_fails(tmp_path):
    scripts_dir = _long_file_scratch(tmp_path, 9500)
    (tmp_path / "long.py").write_text("x = 1\n" * 9501, encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "long.py" in r.stdout and "grew" in r.stdout


def test_scratch_baselined_long_file_that_shrinks_must_lock_in_the_baseline(tmp_path):
    scripts_dir = _long_file_scratch(tmp_path, 9500)
    (tmp_path / "long.py").write_text("x = 1\n" * 9200, encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, "a shrink must fail until the baseline records it: " + r.stdout
    assert "shrank" in r.stdout
    subprocess.run([sys.executable, os.path.join(scripts_dir, "repository_budget.py"),
                    "--update-baseline"], cwd=str(tmp_path), check=True, capture_output=True)
    r2 = _run_guard(tmp_path, ["--check"], script_dir=scripts_dir)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_scratch_shrink_then_regrow_to_old_size_still_fails(tmp_path):
    # The baseline stays at 9500 until someone locks the shrink in, so regrowing is caught.
    scripts_dir = _long_file_scratch(tmp_path, 9500)
    (tmp_path / "long.py").write_text("x = 1\n" * 9200, encoding="utf-8")
    _git_add_all(tmp_path)
    (tmp_path / "long.py").write_text("x = 1\n" * 9500, encoding="utf-8")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 0  # back at the recorded size: not growth past the baseline
    (tmp_path / "long.py").write_text("x = 1\n" * 9501, encoding="utf-8")
    _git_add_all(tmp_path)
    r2 = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r2.returncode == 1 and "grew" in r2.stdout


def test_scratch_baselined_long_file_that_is_deleted_fails(tmp_path):
    scripts_dir = _long_file_scratch(tmp_path, 9500)
    os.remove(tmp_path / "long.py")
    _git_add_all(tmp_path)
    r = _run_guard(tmp_path, script_dir=scripts_dir)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "long.py" in r.stdout


def test_count_lines_bytes_matches_wc_semantics():
    module = _load_guard_module()
    assert module._count_lines_bytes(b"") == 0
    assert module._count_lines_bytes(b"a") == 1
    assert module._count_lines_bytes(b"a\n") == 1
    assert module._count_lines_bytes(b"a\nb") == 2
    assert module._count_lines_bytes(b"\n\n") == 2


def test_looks_text_is_utf8_decodability():
    module = _load_guard_module()
    assert module._looks_text("plain text\n".encode("utf-8")) is True
    assert module._looks_text("pt-BR: ação\n".encode("utf-8")) is True
    assert module._looks_text(b"ab\0cd") is True  # a stray NUL inside text stays text
    assert module._looks_text(b"\xff\xfe\x81") is False  # not UTF-8 -> binary


def test_line_budget_violations_boundaries_and_kinds():
    module = _load_guard_module()
    cap = module.MAX_LINES
    assert cap == 9000
    assert module._line_budget_violations({"a": cap}, {}) == []
    assert module._line_budget_violations({"a": cap + 1}, {}) == [("a", cap + 1, None, "new")]
    assert module._line_budget_violations({"a": 9500}, {"a": 9500}) == []
    assert module._line_budget_violations({"a": 9501}, {"a": 9500}) == [("a", 9501, 9500, "grew")]
    assert module._line_budget_violations({"a": 9200}, {"a": 9500}) == [("a", 9200, 9500, "shrank")]
    assert module._line_budget_violations({}, {"a": 9500}) == [("a", 0, 9500, "missing")]


def test_selftest_passes():
    r = _run(["selftest"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "repository_budget selftest: PASS" in r.stdout


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_repository_budget")

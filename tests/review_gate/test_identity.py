"""Level, roles and independence of the approval (Parte de #1649)."""
import pytest

from simplicio_loop.review_gate import diffs, identity
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, Level

WORKER = identity.Agent("worker-3", "worker", "haiku-5.5", "ccr")
COORD = identity.Agent("squad-q-coordinator", "coordinator", "sonnet-5.5", "ccr")
AUTO = identity.AUTO_REVIEWER
OTHER = identity.Agent("rev-9", "independent-reviewer", "opus-5.5", "local")


def _c(path, status="M", added=(1,)):
    return diffs.FileChange(path, status, tuple(added))


@pytest.mark.parametrize("path", [
    "simplicio_loop/sandbox.py", "simplicio_loop/daemon/run.py", "simplicio_loop/auth_token.py", "scripts/uninstall.sh",
    "packages/mapper/simplicio_mapper/x.py", "simplicio_loop/login_check.py", "simplicio_loop/secret_scan.py"])
def test_security_paths_are_t2(path):
    assert identity.classify_level([_c(path)]) is Level.T2


@pytest.mark.parametrize("path", [
    # the audit's list (M1, #1649): what plan_paths.protected_refusal names ...
    "simplicio_loop/watcher247/squad_flow.py", "hooks/action_gate.py", ".github/workflows/ci.yml", "CODEOWNERS", "scripts/check.py",
    ".claude/settings.json", "simplicio_loop/plan_paths.py", "simplicio_loop/watcher247/points/judge.py",
    # ... and the gate and the host rules themselves
    "simplicio_loop/review_gate/gate.py", "simplicio_loop/review_gate/isolation.py", "simplicio_loop/squads.py",
    "simplicio_loop/watcher247/squad_review.py", "tests/conftest.py", "skills/x/SKILL.md", "docs/host-rules/claude.md"])
def test_the_protected_and_the_gate_paths_are_t2_whatever_the_kind(path):
    assert identity.classify_level([_c(path)]) is Level.T2
    assert identity.classify_level([_c("src/app.py"), _c(path, "D")]) is Level.T2  # deleting them is as sensitive
    assert identity.paths_level(["src/app.py", path]) == 2


@pytest.mark.parametrize("path", [
    # a conftest.py at any depth, in any case and any spelling a forgiving file system reads the same
    "conftest.py", "tests/conftest.py", "tests/sub/conftest.py", "tests/a/b/c/d/conftest.py", "pkg/conftest.py", "./tests//sub/./conftest.py",
    "tests/Sub/CONFTEST.PY", "tests/sub/Conftest.py", "tests/sub/conftest.py.", "tests/sub/conftest.py ", "tests/sub/ｃonftest.py",
    "tests\\sub\\conftest.py",
    # the pytest configuration, wherever it is
    "pytest.ini", "tests/pytest.ini", ".pytest.ini", "PYTEST.INI", "tox.ini", "Tox.ini", "sub/tox.ini", "setup.cfg", "pyproject.toml",
    "packages/dev-cli/pyproject.toml", "PyProject.toml",
    # plugin modules
    "plugins.py", "tests/plugins.py", "tests/pytest_plugins.py", "tests/plugins/fake.py", "tests/Plugins/fake.py", "tests/pytest_plugins/x/y.py",
    "tests/PLUGINS.PY"])
def test_any_conftest_pytest_config_or_plugin_module_is_t2_wherever_it_is(path):
    assert identity.sensitive_path(path)
    for status in ("A", "M", "D"):
        assert identity.classify_level([_c("src/app.py"), _c(path, status)]) is Level.T2
    assert identity.classify_level([_c(path, "A")]) is Level.T2  # alone as well: not even a T0
    assert identity.paths_level(["src/app.py", path]) == 2


@pytest.mark.parametrize("path", [
    # pytest 9 reads these two like a pytest.ini
    "pytest.toml", ".pytest.toml", "tests/pytest.toml", "PYTEST.TOML", "sub/.pytest.toml",
    # Python runs these at start-up, before pytest
    "sitecustomize.py", "usercustomize.py", "tests/sitecustomize.py", "src/SiteCustomize.py", "pkg/usercustomize.py.",
    "evil.pth", "tests/evil.pth", "EVIL.PTH",
    # an installed distribution declares plugins in entry_points.txt ([pytest11])
    "pkg.egg-info/entry_points.txt", "tests/x/pkg.egg-info/entry_points.txt", "pkg-1.0.dist-info/entry_points.txt",
    "pkg-1.0.DIST-INFO/METADATA", "a/b.egg-info/top_level.txt"])
def test_start_up_hooks_pytest_toml_and_installed_metadata_are_t2_wherever_they_are(path):
    assert identity.sensitive_path(path)
    for status in ("A", "M", "D"):
        assert identity.classify_level([_c("src/app.py"), _c(path, status)]) is Level.T2
    assert identity.classify_level([_c(path, "A")]) is Level.T2
    assert identity.paths_level(["src/app.py", path]) == 2


@pytest.mark.parametrize("path", ["tests/test_sitecustomize.py", "src/my_sitecustomize.py", "src/sitecustomizer.py", "docs/pth.md",
                                  "src/path.py", "tests/egg-info.txt", "src/dist_info.py", "src/pytest_toml.py", "docs/pytest.toml.md"])
def test_names_that_only_look_like_the_start_up_hooks_are_not_t2(path):
    assert not identity.sensitive_path(path)
    assert identity.classify_level([_c("src/app.py"), _c(path, "A")]) is Level.T1


def test_pytest_toml_names_are_pytest_config_for_the_neutralizer_as_well():
    assert diffs.PYTEST_CONFIG_NAMES.index("pytest.toml") < diffs.PYTEST_CONFIG_NAMES.index("pyproject.toml")
    assert diffs.PYTEST_CONFIG_NAMES.index(".pytest.toml") < diffs.PYTEST_CONFIG_NAMES.index("pyproject.toml")
    assert diffs.is_pytest_infra("pytest.toml") and diffs.is_pytest_infra("tests/.pytest.toml")


PLUGIN_SHAPES = {
    "plain": "pytest_plugins = ['evil']\n\n\ndef test_a():\n    assert True\n",
    "string": "pytest_plugins = 'evil'\n",
    "tuple": "pytest_plugins = ('evil',)\n",
    "annotated": "pytest_plugins: list = ['evil']\n",
    "augmented": "from base import pytest_plugins\npytest_plugins += ['evil']\n",
    "annotated_only_value": "from base import x\npytest_plugins: list = x\n",
    "chained": "x = pytest_plugins = ['evil']\n",
    "unpacked": "pytest_plugins, other = ['evil'], 1\n",
    "unpacked_list": "[other, pytest_plugins] = 1, ['evil']\n",
    "starred": "*pytest_plugins, other = ['evil', 1]\n",
    "in_if": "import sys\nif sys.platform:\n    pytest_plugins = ['evil']\n",
    "in_else": "import sys\nif sys.platform:\n    pass\nelse:\n    pytest_plugins = ['evil']\n",
    "in_try": "try:\n    import evil\n    pytest_plugins = ['evil']\nexcept ImportError:\n    pass\n",
    "in_except": "try:\n    import evil\nexcept ImportError:\n    pytest_plugins = ['evil']\n",
    "in_try_else": "try:\n    import evil\nexcept ImportError:\n    pass\nelse:\n    pytest_plugins = ['evil']\n",
    "in_finally": "try:\n    pass\nfinally:\n    pytest_plugins = ['evil']\n",
    "in_with": "import contextlib\nwith contextlib.nullcontext():\n    pytest_plugins = ['evil']\n",
    "in_for": "for _ in range(1):\n    pytest_plugins = ['evil']\n",
    "in_while": "while True:\n    pytest_plugins = ['evil']\n    break\n",
    "in_match": "import sys\nmatch sys.platform:\n    case _:\n        pytest_plugins = ['evil']\n",
    "after_a_def_and_a_class": "def f():\n    pass\n\n\nclass C:\n    pass\n\n\npytest_plugins = ['evil']\n",
}


@pytest.mark.parametrize("shape", sorted(PLUGIN_SHAPES))
@pytest.mark.parametrize("status", ["A", "M"])
def test_a_test_module_that_sets_pytest_plugins_is_t2(shape, status):
    texts = {"tests/test_x.py": PLUGIN_SHAPES[shape]}
    changes = [_c("src/app.py"), _c("tests/test_x.py", status)]
    assert identity.classify_level(changes, read=texts.get) is Level.T2
    assert identity.classify_level([_c("tests/test_x.py", status)], read=texts.get) is Level.T2  # alone: not even a T0


@pytest.mark.parametrize("text", [
    "def test_a():\n    pytest_plugins = ['x']\n    assert pytest_plugins\n",  # a local variable
    "class TestA:\n    pytest_plugins = ['x']\n",  # a class attribute
    "import mod\nvalue = mod.pytest_plugins\n",  # a read
    "plugins = ['evil']\n# pytest_plugins = ['evil']\n",  # a comment
    "x = 'pytest_plugins = 1'\n",  # a string
    "mod.pytest_plugins = ['x']\n",  # an attribute of something else
    "def broken(:\n",  # not Python: it never collects
    ""])
def test_a_test_module_that_only_looks_like_it_sets_pytest_plugins_is_not_t2(text):
    changes = [_c("src/app.py"), _c("tests/test_x.py", "A")]
    assert identity.classify_level(changes, read=lambda path: text) is Level.T1


def test_pytest_plugins_is_read_only_from_a_changed_test_module_that_still_exists():
    texts = {"tests/test_x.py": PLUGIN_SHAPES["plain"], "src/app.py": PLUGIN_SHAPES["plain"]}
    assert identity.classify_level([_c("src/app.py"), _c("tests/test_x.py", "D")], read=texts.get) is Level.T1  # deleted: nothing runs
    assert identity.classify_level([_c("src/app.py")], read=texts.get) is Level.T1  # production code is not a test module
    assert identity.classify_level([_c("src/app.py"), _c("tests/test_y.py", "A")], read=texts.get) is Level.T1  # no text: no claim
    assert identity.classify_level([_c("src/app.py"), _c("tests/test_x.py", "A")]) is Level.T1  # no reader: the paths only


def test_run_gate_gives_the_level_a_reader_of_the_head(tmp_path, monkeypatch):
    from simplicio_loop.review_gate import gate
    from tests.review_gate import scenario

    class Stop(Exception):
        pass

    seen = {}

    def fake_classify(changes, read=None):
        seen["read"] = read
        raise Stop

    repo = tmp_path / "repo"
    repo.mkdir()
    scenario.git(repo, "init", "-q", "-b", "main")
    (repo / "mod.py").write_text("y = 1\n")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    base = scenario.git(repo, "rev-parse", "HEAD")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(PLUGIN_SHAPES["plain"])
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "head")
    head = scenario.git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(gate.identity, "classify_level", fake_classify)
    with pytest.raises(Stop):
        gate.run_gate(gate.GateInput(repo=repo, pr=1, issue=None, issue_body="", pr_body="", base=base, head=head, author=WORKER))
    assert seen["read"]("tests/test_x.py") == PLUGIN_SHAPES["plain"]


def test_the_gate_reads_the_test_modules_of_the_head_from_git(tmp_path):
    from simplicio_loop.review_gate import gate
    from tests.review_gate import scenario

    repo = tmp_path / "repo"
    repo.mkdir()
    scenario.git(repo, "init", "-q", "-b", "main")
    (repo / "mod.py").write_text("y = 1\n")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(PLUGIN_SHAPES["plain"])
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "head")
    head = scenario.git(repo, "rev-parse", "HEAD")
    read = gate.head_reader(repo, head)
    assert read("tests/test_x.py") == PLUGIN_SHAPES["plain"]
    assert read("tests/missing.py") is None


@pytest.mark.parametrize("path", ["tests/test_conftest.py", "tests/conftest_helpers.py", "tests/my_conftest.py", "tests/conftest/helper.py",
                                  "tests/pytest.ini.md", "docs/tox.md", "src/plugins_list.py", "src/plugin.py", "tests/test_plugins.py"])
def test_names_that_only_look_like_them_are_not_t2(path):
    assert not identity.sensitive_path(path)
    assert identity.classify_level([_c("src/app.py"), _c(path, "A")]) is Level.T1


def test_a_symlinked_conftest_is_t2_as_the_diff_names_it(tmp_path):
    """git records a symlink under its own path: `tests/sub/conftest.py -> ../elsewhere.py` is the path `tests/sub/conftest.py`."""
    from tests.review_gate import scenario

    repo = tmp_path / "repo"
    repo.mkdir()
    scenario.git(repo, "init", "-q", "-b", "main")
    (repo / "elsewhere.py").write_text("x = 1\n")
    (repo / "mod.py").write_text("y = 1\n")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    base = scenario.git(repo, "rev-parse", "HEAD")
    (repo / "tests" / "sub").mkdir(parents=True)
    (repo / "tests" / "sub" / "conftest.py").symlink_to("../../elsewhere.py")
    (repo / "mod.py").write_text("y = 2\n")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "head")
    changes = diffs.changed_files(repo, base, scenario.git(repo, "rev-parse", "HEAD"))
    assert "tests/sub/conftest.py" in [c.path for c in changes]
    assert identity.classify_level(changes) is Level.T2


def test_the_pytest_infra_rule_is_one_function_shared_by_the_level_and_the_gate():
    assert diffs.is_pytest_infra("tests/sub/conftest.py") and not diffs.is_pytest_infra("tests/sub/test_x.py")
    assert not diffs.is_pytest_infra("") and not diffs.is_pytest_infra("src/mod.py")


def test_an_ordinary_diff_is_not_t2_by_the_path_rules():
    assert identity.classify_level([_c("src/app.py"), _c("tests/test_app.py", "A")]) is Level.T1
    assert identity.paths_level(["src/app.py", "tests/test_app.py", "README.md"]) == 0


def test_a_security_test_beside_production_code_is_t2():
    """#1640: the uninstall hardening changed install/planner.py, and only the test file said `uninstall`."""
    changes = [_c("simplicio_loop/install/planner.py"), _c("tests/install/test_uninstall_receipt_hardening.py", "A")]
    assert identity.classify_level(changes) is Level.T2
    assert identity.classify_level([_c("simplicio_loop/install/planner.py"), _c("tests/install/test_plan.py", "A")]) is Level.T1
    assert identity.classify_level([_c("simplicio_loop/install/planner.py"), _c("tests/test_uninstall.py", "D")]) is Level.T1


def test_tests_of_security_modules_are_not_t2_and_names_match_by_word():
    assert identity.classify_level([_c("tests/test_sandbox.py"), _c("docs/SANDBOX.md")]) is Level.T0
    assert identity.classify_level([_c("simplicio_loop/tokenizer_cache.py")]) is Level.T1  # "tokenizer" is not "token"


def test_levels_t0_small_docs_and_tests_t1_code_or_big():
    assert identity.classify_level([_c("docs/A.md"), _c("tests/test_a.py")]) is Level.T0
    assert identity.classify_level([_c("docs/A.md", added=range(300))]) is Level.T1
    assert identity.classify_level([_c("simplicio_loop/util.py")]) is Level.T1


def test_self_approval_by_agent_or_by_role_is_rejected():
    same = identity.check_identity(WORKER, WORKER, Level.T1, None)
    assert same.status == FAIL and "auto-aprovacao" in same.reasons[0]
    same_role = identity.check_identity(WORKER, identity.Agent("worker-4", "worker", "haiku-5.5", "ccr"), Level.T1, None)
    assert same_role.status == FAIL and "papel" in same_role.reasons[0]
    assert identity.check_identity(WORKER, COORD, Level.T1, None).status == PASS
    assert identity.check_identity(WORKER, AUTO, Level.T1, None).status == PASS


def test_unknown_author_is_an_error_not_a_pass():
    result = identity.check_identity(identity.Agent("", "", "", ""), AUTO, Level.T1, None)
    assert result.status == ERROR and "autor" in result.reasons[0]


def test_t2_needs_an_independent_reviewer_of_another_role():
    assert identity.check_identity(WORKER, AUTO, Level.T2, None).status == FAIL
    assert "revisor independente" in identity.check_identity(WORKER, AUTO, Level.T2, None).reasons[0]
    assert identity.check_identity(WORKER, AUTO, Level.T2, AUTO).status == FAIL  # the gate alone is not independent
    assert identity.check_identity(WORKER, AUTO, Level.T2, WORKER).status == FAIL
    assert identity.check_identity(WORKER, AUTO, Level.T2, identity.Agent("w9", "worker", "x", "y")).status == FAIL
    ok = identity.check_identity(WORKER, AUTO, Level.T2, OTHER)
    assert ok.status == PASS and ok.measured["independent"] == "rev-9"


FULL = "abcdef1234" + "5" * 30
MARK = "REVISÃO INDEPENDENTE: APROVADA\nrevisor: rev-9\npapel: independent-reviewer\nmodelo: opus-5.5\nhost: local\nhead: " + FULL


def test_marker_binds_to_the_head_and_ignores_quotes():
    comments = [{"body": "> " + MARK.replace("\n", "\n> ")}, {"body": "ok\n" + MARK}]
    assert identity.parse_independent_marker(comments, FULL) == OTHER
    assert identity.parse_independent_marker(comments, "0" * 40) is None  # approval of another head
    assert identity.parse_independent_marker([{"body": "> " + MARK}], FULL) is None


def test_marker_needs_the_full_sha_compared_exactly_never_a_prefix_m2():
    """The audit's mutant 5 (`len(marked) >= 1`) lived because any prefix of the head was accepted."""
    for marked in ("a", "abcdef1", FULL[:12], FULL[:39], FULL.upper(), FULL + "0"):
        body = MARK.replace(FULL, marked)
        assert identity.parse_independent_marker([{"body": body}], FULL) is None, marked
    assert identity.parse_independent_marker([{"body": MARK.replace(FULL, FULL[:7])}], FULL[:7]) is None  # nor a head that is itself short

"""The gate starts pytest without the editable-install finders, so a module only the PR adds is missing on main."""
import subprocess
import sys

from simplicio_loop.review_gate import pytest_cmd

FINDER = '''import importlib.util, sys
class _EditableFinder:  # what setuptools puts on sys.meta_path for `pip install -e`
    @classmethod
    def find_spec(cls, name, path=None, target=None):
        return importlib.util.spec_from_file_location(name, {leak!r}) if name == "leaky_mod" else None
sys.meta_path.append(_EditableFinder)
'''


def _run(tmp_path, command):
    site = tmp_path / "site"
    site.mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "leaky_mod.py").write_text("VALUE = 1\n")  # the other checkout: not on sys.path
    (site / "sitecustomize.py").write_text(FINDER.format(leak=str(tmp_path / "other" / "leaky_mod.py")))
    (tmp_path / "test_leak.py").write_text("import pytest\n\n\ndef test_a_module_missing_from_the_tree_is_missing():\n"
                                           "    with pytest.raises(ImportError):\n        import leaky_mod\n")
    return subprocess.run(command, cwd=tmp_path, env={"PYTHONPATH": str(site), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, check=False)


def test_the_editable_finder_is_gone_before_pytest_imports_anything(tmp_path):
    done = _run(tmp_path, pytest_cmd.command(sys.executable, "-q", "-p", "no:cacheprovider", "-o", "addopts=", "test_leak.py"))
    assert done.returncode == 0, done.stdout[-300:]


def test_without_the_command_the_finder_serves_the_missing_module(tmp_path):
    """The control: plain `python -m pytest` imports the module from the other checkout."""
    done = _run(tmp_path, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", "test_leak.py"])
    assert done.returncode == 1


def test_arguments_reach_pytest_in_order():
    argv = pytest_cmd.command("/py", "-q", "a.py::t")
    assert argv[0] == "/py" and argv[1] == "-c" and argv[3:] == ["-q", "a.py::t"]

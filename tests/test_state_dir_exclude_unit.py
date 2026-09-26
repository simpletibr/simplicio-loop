import subprocess

from simplicio_loop.state_dir import ensure_state_dir


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_ensure_state_dir_appends_exclude_line_once(tmp_path):
    _init_git_repo(tmp_path)

    ensure_state_dir(tmp_path)
    ensure_state_dir(tmp_path)

    exclude_path = tmp_path / ".git" / "info" / "exclude"
    lines = exclude_path.read_text(encoding="utf-8").splitlines()
    assert lines.count(".simplicio-loop/") == 1


def test_ensure_state_dir_creates_the_directory(tmp_path):
    _init_git_repo(tmp_path)

    state_dir = ensure_state_dir(tmp_path)

    assert state_dir.is_dir()
    assert state_dir == tmp_path / ".simplicio-loop"


def test_ensure_state_dir_non_git_dir_does_not_error(tmp_path):
    # tmp_path is not a git repo: no .git directory present.
    state_dir = ensure_state_dir(tmp_path)

    assert state_dir.is_dir()
    assert not (tmp_path / ".git").exists()


def test_ensure_state_dir_preserves_existing_exclude_content(tmp_path):
    _init_git_repo(tmp_path)
    exclude_path = tmp_path / ".git" / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    exclude_path.write_text("*.log\n", encoding="utf-8")

    ensure_state_dir(tmp_path)

    lines = exclude_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["*.log", ".simplicio-loop/"]

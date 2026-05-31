from pathlib import Path

from simplicio.runtime_env import wrap_project_command


def test_wrap_project_command_uses_project_nvmrc(tmp_path, monkeypatch):
    nvm_dir = tmp_path / "nvm"
    nvm_dir.mkdir()
    (nvm_dir / "nvm.sh").write_text("# fake nvm\n", encoding="utf-8")
    (tmp_path / ".nvmrc").write_text("22.12.0\n", encoding="utf-8")
    monkeypatch.setenv("NVM_DIR", str(nvm_dir))

    wrapped = wrap_project_command(tmp_path, "npm run build")

    assert str(nvm_dir / "nvm.sh") in wrapped
    assert "nvm use" in wrapped
    assert wrapped.endswith("&& npm run build")


def test_wrap_project_command_skips_non_node_commands(tmp_path, monkeypatch):
    nvm_dir = tmp_path / "nvm"
    nvm_dir.mkdir()
    (nvm_dir / "nvm.sh").write_text("# fake nvm\n", encoding="utf-8")
    (tmp_path / ".nvmrc").write_text("22.12.0\n", encoding="utf-8")
    monkeypatch.setenv("NVM_DIR", str(nvm_dir))

    assert wrap_project_command(tmp_path, "pytest -q") == "pytest -q"


def test_wrap_project_command_skips_when_nvm_already_selected(tmp_path):
    command = ". ~/.nvm/nvm.sh && nvm use && npm test"

    assert wrap_project_command(Path(tmp_path), command) == command

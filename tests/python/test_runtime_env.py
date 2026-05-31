from pathlib import Path

import pytest

from simplicio.runtime_env import parse_env_file, shell_export_lines, wrap_project_command


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


def test_parse_env_file_preserves_semicolon_connection_string(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "# local database",
                "Database__ConnectionString=Host=localhost;Port=5432;Database=maturity_matrix;",
                "Jwt__Key='secret;with;semicolons'",
            ]
        ),
        encoding="utf-8",
    )

    values = parse_env_file(env_file)

    assert values["Database__ConnectionString"] == (
        "Host=localhost;Port=5432;Database=maturity_matrix;"
    )
    assert values["Jwt__Key"] == "secret;with;semicolons"


def test_shell_export_lines_quote_values(tmp_path):
    values = {"Database__ConnectionString": "Host=localhost;Port=5432;"}

    assert shell_export_lines(values) == [
        "export Database__ConnectionString='Host=localhost;Port=5432;'"
    ]


def test_parse_env_file_rejects_invalid_lines(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("not-a-valid-line\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing '='"):
        parse_env_file(env_file)

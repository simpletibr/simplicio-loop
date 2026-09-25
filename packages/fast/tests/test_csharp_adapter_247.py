from pathlib import Path

from simplicio_fast.adapters import (
    csharp_workspace_fingerprint,
    discover_csharp_projects,
    parse_path,
)


def test_csharp_adapter_covers_declared_constructs(tmp_path: Path) -> None:
    source = tmp_path / "Service.cs"
    source.write_text(
        """[Obsolete]\nnamespace Demo;\npublic partial record User<T> {\n    public string Name { get; set; }\n    public event EventHandler Changed;\n    public User() {}\n    public async Task SaveAsync() { }\n}\npublic interface IStore {}\npublic delegate void Handler();\npublic enum State { Ready }\n""",
        encoding="utf-8",
    )
    kinds = {(symbol.name, symbol.kind) for symbol in parse_path(source, "Service.cs")}
    assert ("Obsolete", "attribute") in kinds
    assert ("User", "record") in kinds
    assert ("Name", "property") in kinds
    assert ("Changed", "event") in kinds
    assert ("User", "constructor") in kinds
    assert ("SaveAsync", "function") in kinds
    assert ("IStore", "interface") in kinds
    assert ("Handler", "delegate") in kinds
    assert ("State", "enum") in kinds


def test_csharp_project_discovery_excludes_build_output(tmp_path: Path) -> None:
    (tmp_path / "App.csproj").write_text("<Project />", encoding="utf-8")
    (tmp_path / "Directory.Build.props").write_text("<Project />", encoding="utf-8")
    output = tmp_path / "bin"
    output.mkdir()
    (output / "Generated.csproj").write_text("<Project />", encoding="utf-8")
    assert [path.name for path in discover_csharp_projects(tmp_path)] == [
        "App.csproj",
        "Directory.Build.props",
    ]


def test_csharp_workspace_fingerprint_changes_with_project_inputs(tmp_path: Path) -> None:
    project = tmp_path / "App.csproj"
    project.write_text("<Project />", encoding="utf-8")
    first = csharp_workspace_fingerprint(tmp_path)
    project.write_text("<Project><PropertyGroup /></Project>", encoding="utf-8")
    second = csharp_workspace_fingerprint(tmp_path)
    assert first != second


def test_csharp_workspace_fingerprint_binds_sdk_and_restore_inputs(tmp_path: Path) -> None:
    (tmp_path / "App.csproj").write_text("<Project />", encoding="utf-8")
    (tmp_path / "global.json").write_text('{"sdk":{"version":"8.0.0"}}', encoding="utf-8")
    (tmp_path / "NuGet.config").write_text("<configuration />", encoding="utf-8")
    (tmp_path / "packages.lock.json").write_text('{"version":1}', encoding="utf-8")
    assert {path.name for path in discover_csharp_projects(tmp_path)} == {
        "App.csproj",
        "NuGet.config",
        "global.json",
        "packages.lock.json",
    }
    baseline = csharp_workspace_fingerprint(tmp_path)
    (tmp_path / "global.json").write_text('{"sdk":{"version":"9.0.0"}}', encoding="utf-8")
    assert csharp_workspace_fingerprint(tmp_path) != baseline


def test_csharp_multi_project_solution_preserves_partial_and_test_sources(
    tmp_path: Path,
) -> None:
    (tmp_path / "Demo.sln").write_text("Microsoft Visual Studio Solution File\n", encoding="utf-8")
    (tmp_path / "Directory.Build.props").write_text("<Project />", encoding="utf-8")
    (tmp_path / "Directory.Packages.props").write_text("<Project />", encoding="utf-8")
    for project in ("Core", "Web.Tests"):
        project_root = tmp_path / "src" / project
        project_root.mkdir(parents=True)
        (project_root / f"{project}.csproj").write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup>"
            "<TargetFramework>net8.0</TargetFramework></PropertyGroup></Project>",
            encoding="utf-8",
        )
    source = tmp_path / "src" / "Core" / "User.cs"
    source.write_text(
        "namespace Demo;\n"
        "public partial class User {\n"
        "    public string Name { get; set; }\n"
        "    public void Save() {}\n"
        "}\n",
        encoding="utf-8",
    )
    test_source = tmp_path / "src" / "Web.Tests" / "UserTests.cs"
    test_source.write_text(
        "using Demo;\n"
        "public class UserTests {\n"
        "    [Fact]\n"
        "    public void Saves() {}\n"
        "}\n",
        encoding="utf-8",
    )

    discovered = [path.relative_to(tmp_path).as_posix() for path in discover_csharp_projects(tmp_path)]
    assert discovered == [
        "Demo.sln",
        "Directory.Build.props",
        "Directory.Packages.props",
        "src/Core/Core.csproj",
        "src/Web.Tests/Web.Tests.csproj",
    ]
    symbols = parse_path(source, "src/Core/User.cs")
    test_symbols = parse_path(test_source, "src/Web.Tests/UserTests.cs")
    assert {symbol.name for symbol in symbols} >= {"Demo", "User", "Name", "Save"}
    assert {symbol.name for symbol in test_symbols} >= {"Demo", "UserTests", "Saves"}

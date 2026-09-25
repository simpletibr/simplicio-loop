from pathlib import Path

from simplicio_fast.adapters import (
    discover_typescript_projects,
    parse_path,
    typescript_workspace_fingerprint,
)


def test_typescript_adapter_covers_modules_types_and_tests(tmp_path: Path) -> None:
    source = tmp_path / "component.tsx"
    source.write_text(
        """import { useState } from 'react';\nexport type UserId = string;\nexport enum State { Ready }\nexport interface User { id: UserId; }\nexport class Store {\n  value: string;\n  async load<T>(): Promise<T> { return null as T; }\n}\ntest('loads users', () => {});\n""",
        encoding="utf-8",
    )
    kinds = {
        (symbol.name, symbol.kind) for symbol in parse_path(source, "component.tsx")
    }
    assert ("react", "import") in kinds
    assert ("UserId", "type") in kinds
    assert ("State", "enum") in kinds
    assert ("User", "interface") in kinds
    assert ("Store", "class") in kinds
    assert ("value", "property") in kinds
    assert ("load", "function") in kinds
    assert ("loads users", "test") in kinds


def test_typescript_project_discovery_excludes_dependencies(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    for name in (
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        ".npmrc",
        ".yarnrc.yml",
        ".node-version",
        ".nvmrc",
    ):
        (tmp_path / name).write_text("", encoding="utf-8")
    dependencies = tmp_path / "node_modules"
    dependencies.mkdir()
    (dependencies / "tsconfig.json").write_text("{}", encoding="utf-8")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "tsconfig.json").write_text("{}", encoding="utf-8")
    assert {path.name for path in discover_typescript_projects(tmp_path)} == {
        ".node-version",
        ".npmrc",
        ".nvmrc",
        ".yarnrc.yml",
        "bun.lock",
        "npm-shrinkwrap.json",
        "package.json",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "yarn.lock",
    }


def test_typescript_workspace_fingerprint_changes_with_config(tmp_path: Path) -> None:
    config = tmp_path / "tsconfig.json"
    config.write_text("{}", encoding="utf-8")
    first = typescript_workspace_fingerprint(tmp_path)
    config.write_text('{"compilerOptions":{"strict":true}}', encoding="utf-8")
    second = typescript_workspace_fingerprint(tmp_path)
    assert first != second


def test_typescript_monorepo_discovers_project_configs_and_tsx_symbols(
    tmp_path: Path,
) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"references":[{"path":"packages/ui"},{"path":"packages/app"}]}',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"private":true}', encoding="utf-8")
    for package in ("ui", "app"):
        package_root = tmp_path / "packages" / package
        package_root.mkdir(parents=True)
        (package_root / "tsconfig.json").write_text(
            '{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}',
            encoding="utf-8",
        )
        (package_root / "package.json").write_text(
            f'{{"name":"@demo/{package}"}}', encoding="utf-8"
        )
    source = tmp_path / "packages" / "ui" / "src" / "Button.tsx"
    source.parent.mkdir()
    source.write_text(
        "import { User } from '@/model';\n"
        "export interface ButtonProps { label: string; }\n"
        "export function Button(props: ButtonProps) { return <button>{props.label}</button>; }\n",
        encoding="utf-8",
    )

    discovered = [path.relative_to(tmp_path).as_posix() for path in discover_typescript_projects(tmp_path)]
    assert discovered == [
        "package.json",
        "packages/app/package.json",
        "packages/app/tsconfig.json",
        "packages/ui/package.json",
        "packages/ui/tsconfig.json",
        "tsconfig.json",
    ]
    symbols = parse_path(source, "packages/ui/src/Button.tsx")
    assert {symbol.name for symbol in symbols} >= {"@/model", "ButtonProps", "Button"}

from pathlib import Path

from simplicio_fast.adapters import (
    capability_report,
    language_for_path,
    negotiate,
    parse_path,
)


def test_capability_negotiation_and_unknown_paths() -> None:
    assert negotiate("c#").language == "csharp"
    assert negotiate("ts").language == "typescript"
    assert negotiate("python").status == "available"
    assert negotiate("kotlin").status == "unavailable"
    assert {item.language for item in capability_report()} == {
        "python",
        "typescript",
        "rust",
        "csharp",
    }
    assert language_for_path(Path("README.md")) is None


def test_python_parser_handles_nested_and_async_symbols(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        "class Service:\n"
        "    async def load(self):\n"
        "        return True\n"
        "def helper():\n"
        "    return False\n",
        encoding="utf-8",
    )
    symbols = parse_path(source, "service.py")
    assert {(item.qualified_name, item.kind) for item in symbols} == {
        ("Service", "class"),
        ("Service.load", "async_function"),
        ("helper", "function"),
    }
    assert parse_path(tmp_path / "unknown.txt") == []


def test_typescript_lexical_patterns_cover_workspace_declarations(tmp_path: Path) -> None:
    source = tmp_path / "all.ts"
    source.write_text(
        "import 'side-effect';\n"
        "import type { X } from 'types';\n"
        "export type Alias = string;\n"
        "export enum Mode { A }\n"
        "export declare namespace Ns {}\n"
        "export interface Contract {}\n"
        "export abstract class Base {}\n"
        "export async function run() {}\n"
        "export const make = () => 1;\n"
        "public load<T>(): T { return null as T; }\n"
        "readonly value?: string;\n"
        "describe('suite', () => {});\n",
        encoding="utf-8",
    )
    kinds = {(item.name, item.kind) for item in parse_path(source, "all.ts")}
    assert ("side-effect", "import") in kinds
    assert ("types", "import") in kinds
    assert {"Alias", "Mode", "Ns", "Contract", "Base", "run", "make", "load", "value", "suite"} <= {
        name for name, _ in kinds
    }


def test_rust_lexical_patterns_cover_impl_and_modifiers(tmp_path: Path) -> None:
    source = tmp_path / "all.rs"
    source.write_text(
        "pub use crate::Thing;\n"
        "pub unsafe mod inner {}\n"
        "pub packed struct Thing {}\n"
        "pub unsafe trait Trait {}\n"
        "pub enum Mode { A }\n"
        "pub type Alias = u8;\n"
        "pub const LIMIT: usize = 1;\n"
        "pub static mut CACHE: usize = 0;\n"
        "macro_rules! build { () => {} }\n"
        "impl<T> Trait for Thing<T> {}\n"
        "pub const async unsafe fn run() {}\n",
        encoding="utf-8",
    )
    symbols = parse_path(source, "all.rs")
    assert {item.kind for item in symbols} >= {
        "import",
        "namespace",
        "struct",
        "trait",
        "enum",
        "function",
    }

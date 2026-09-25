from pathlib import Path

import pytest

from simplicio_fast.adapters import (
    discover_rust_projects,
    parse_path,
    rust_workspace_fingerprint,
)
from simplicio_fast.parser_adapter import build_payload


def test_rust_adapter_covers_workspace_constructs(tmp_path: Path) -> None:
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        """use std::fmt::Display;
pub mod model;
pub struct Item<T> { value: T }
pub enum State { Ready, Done }
pub trait Render { fn render(&self); }
impl<T> Render for Item<T> { fn render(&self) {} }
pub type Id = u64;
pub const LIMIT: usize = 4;
pub static mut CACHE: usize = 0;
macro_rules! make_item { () => {} }
pub async fn load() {}
""",
        encoding="utf-8",
    )

    symbols = parse_path(source, "src/lib.rs")
    names_by_kind = {(symbol.name, symbol.kind) for symbol in symbols}

    assert ("std::fmt::Display", "import") in names_by_kind
    assert {
        "model",
        "Item",
        "State",
        "Render",
        "Item",
        "Id",
        "LIMIT",
        "CACHE",
        "make_item",
        "load",
    } <= {symbol.name for symbol in symbols}
    assert {"namespace", "struct", "enum", "trait", "function", "import"} <= {
        symbol.kind for symbol in symbols
    }


def test_rust_workspace_discovery_excludes_generated_and_vendor(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[workspace]\nmembers=[]\n", encoding="utf-8")
    (tmp_path / "crates" / "core").mkdir(parents=True)
    (tmp_path / "crates" / "core" / "Cargo.toml").write_text(
        "[package]\nname='core'\nversion='0.1.0'\n", encoding="utf-8"
    )
    for directory in (tmp_path / "target", tmp_path / "vendor" / "dep"):
        directory.mkdir(parents=True)
        (directory / "Cargo.toml").write_text("[package]\n", encoding="utf-8")

    assert [
        path.relative_to(tmp_path).as_posix()
        for path in discover_rust_projects(tmp_path)
    ] == [
        "Cargo.toml",
        "crates/core/Cargo.toml",
    ]


def test_rust_workspace_fingerprint_changes_with_cargo_inputs(tmp_path: Path) -> None:
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[workspace]\nmembers=[]\n", encoding="utf-8")
    first = rust_workspace_fingerprint(tmp_path)
    manifest.write_text("[workspace]\nmembers=['crate']\n", encoding="utf-8")
    second = rust_workspace_fingerprint(tmp_path)
    assert first != second


def test_rust_workspace_fingerprint_binds_toolchain_and_cargo_config(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "Cargo.toml"
    manifest.write_text("[package]\nname='app'\nversion='0.1.0'\n", encoding="utf-8")
    toolchain = tmp_path / "rust-toolchain.toml"
    toolchain.write_text('[toolchain]\nchannel="stable"\n', encoding="utf-8")
    cargo_config = tmp_path / ".cargo" / "config.toml"
    cargo_config.parent.mkdir()
    cargo_config.write_text("[build]\nrustflags=[]\n", encoding="utf-8")

    baseline = rust_workspace_fingerprint(tmp_path)
    toolchain.write_text('[toolchain]\nchannel="1.85.0"\n', encoding="utf-8")
    changed_toolchain = rust_workspace_fingerprint(tmp_path)
    assert changed_toolchain != baseline

    cargo_config.write_text("[build]\nrustflags=[\"-Ctarget-cpu=native\"]\n", encoding="utf-8")
    changed_config = rust_workspace_fingerprint(tmp_path)
    assert changed_config != changed_toolchain


def test_rust_workspace_fingerprint_binds_selected_cargo_features(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[package]\nname='app'\nversion='0.1.0'\n[features]\nserde=[]\n",
        encoding="utf-8",
    )
    baseline = rust_workspace_fingerprint(tmp_path, features=("default", "serde"))
    reordered = rust_workspace_fingerprint(tmp_path, features=("serde", "default"))
    changed = rust_workspace_fingerprint(tmp_path, features=("default",))
    assert reordered == baseline
    assert changed != baseline
    with pytest.raises(ValueError, match="rust_features_invalid"):
        rust_workspace_fingerprint(tmp_path, features="serde")  # type: ignore[arg-type]


def test_parser_payload_propagates_selected_rust_features_into_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[package]\nname='app'\nversion='0.1.0'\n", encoding="utf-8"
    )
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("pub fn run() {}\n", encoding="utf-8")
    serde = build_payload(tmp_path, rust_features=("serde",))
    tokio = build_payload(tmp_path, rust_features=("tokio",))
    assert serde["workspace_fingerprints"]["rust"] != tokio["workspace_fingerprints"]["rust"]


def test_rust_multi_crate_workspace_discovers_and_parses_each_member(
    tmp_path: Path,
) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[workspace]\nmembers=['crates/core','crates/app']\n",
        encoding="utf-8",
    )
    core = tmp_path / "crates" / "core"
    app = tmp_path / "crates" / "app"
    for crate in (core, app):
        (crate / "src").mkdir(parents=True)
        (crate / "Cargo.toml").write_text(
            f"[package]\nname='{crate.name}'\nversion='0.1.0'\n",
            encoding="utf-8",
        )
    (core / "src" / "lib.rs").write_text(
        "pub trait Render { fn render(&self); }\n"
        "pub struct Item;\n"
        "impl Render for Item {\n"
        "    fn render(&self) {}\n"
        "}\n",
        encoding="utf-8",
    )
    (app / "src" / "main.rs").write_text(
        "use core::Item;\n"
        "fn main() { let _item = Item; }\n",
        encoding="utf-8",
    )

    manifests = [path.relative_to(tmp_path).as_posix() for path in discover_rust_projects(tmp_path)]
    assert manifests == ["Cargo.toml", "crates/app/Cargo.toml", "crates/core/Cargo.toml"]
    core_symbols = parse_path(core / "src" / "lib.rs", "crates/core/src/lib.rs")
    app_symbols = parse_path(app / "src" / "main.rs", "crates/app/src/main.rs")
    assert {symbol.name for symbol in core_symbols} >= {"Render", "Item", "render"}
    assert {symbol.name for symbol in app_symbols} >= {"core::Item", "main"}


def test_rust_macro_and_cfg_limitations_are_explicit_diagnostics(
    tmp_path: Path,
) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[package]\nname='app'\nversion='0.1.0'\n",
        encoding="utf-8",
    )
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text(
        '#[cfg(feature = "serde")]\n'
        "macro_rules! make_item { () => {} }\n"
        "pub fn run() { make_item!(); }\n",
        encoding="utf-8",
    )

    payload = build_payload(tmp_path)
    assert payload == build_payload(tmp_path)
    assert payload["completeness"] == "partial"
    diagnostics = {
        item["code"]: item
        for item in payload["diagnostics"]
        if item["path"] == "src/lib.rs"
    }
    assert {
        "native_parser_unavailable",
        "rust_cfg_unresolved",
        "rust_macro_unexpanded",
    } <= diagnostics.keys()
    assert diagnostics["rust_cfg_unresolved"]["detail"] == (
        "cfg/cfg_attr branches are not evaluated by the bounded lexical adapter"
    )
    assert diagnostics["rust_cfg_unresolved"]["fallback"] == (
        "use Mapper-native or rust-analyzer parsing with selected Cargo features and toolchain"
    )
    assert diagnostics["rust_macro_unexpanded"]["detail"] == (
        "Rust macro definitions and invocations are not expanded by the bounded lexical adapter"
    )

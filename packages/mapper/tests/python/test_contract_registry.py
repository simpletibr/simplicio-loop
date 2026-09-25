import json

from simplicio_mapper.cli import main
from simplicio_mapper.contract_registry import (
    ContractRegistryError,
    _parse_roots,
    _read_json,
    canonical_hash,
    diff_contracts,
    impact_contract,
    inventory_contracts,
    load_registry,
    run_contracts_cli,
    validate_registry,
)


def _entry(contract_id="simplicio.example/v1", schema_path=None):
    return {
        "id": contract_id,
        "kind": "data",
        "owner": "mapper",
        "maintainers": ["mapper"],
        "producers": ["mapper"],
        "consumers": ["loop"],
        "writer_authority": "mapper",
        "versions": {"current": "v1", "minimum": "v1", "maximum": "v1", "deprecated": False},
        "canonical": {"schema_path": schema_path, "sha256": "auto", "fixture_paths": []},
        "compatibility": {"policy": "versioned"},
        "change_policy": {"breaking": "new-version", "additive": "compatible"},
    }


def test_canonical_hash_is_key_order_stable():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_inventory_detects_incompatible_duplicate_schema(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    (first / "schemas").mkdir(parents=True)
    (second / "schemas").mkdir(parents=True)
    (first / "schemas/a.schema.json").write_text(json.dumps({"$id": "simplicio.example/v1", "type": "object"}))
    (second / "schemas/b.schema.json").write_text(json.dumps({"$id": "simplicio.example/v1", "type": "array"}))
    report = inventory_contracts([("first", first), ("second", second)])
    assert report["duplicates"] == ["simplicio.example/v1"]
    assert report["contracts"][0]["duplicate_incompatible"] is True


def test_validate_registry_accepts_local_schema_and_reports_auto_hash(tmp_path):
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"$id": "simplicio.example/v1", "type": "object"}))
    report = validate_registry({"schema": "simplicio.contract-registry/v1", "contracts": [_entry(schema_path="schema.json")]}, root=tmp_path)
    assert report["valid"] is True
    assert report["warnings"] == [{"code": "CANONICAL_HASH_UNVERIFIED", "id": "simplicio.example/v1"}]


def test_diff_classifies_additive_breaking_ambiguous_and_unchanged():
    old = {"type": "object", "properties": {"a": {"type": "string"}}}
    additive = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
    breaking = {"type": "object", "properties": {"a": {"type": "integer"}}}
    assert diff_contracts(old, old)["classification"] == "unchanged"
    assert diff_contracts(old, additive)["classification"] == "additive"
    assert diff_contracts(old, breaking)["classification"] == "breaking"
    assert diff_contracts({"metadata": 1}, {"metadata": 2})["classification"] == "ambiguous"


def test_impact_exposes_owner_and_consumers():
    report = impact_contract({"contracts": [_entry()]}, "simplicio.example/v1")
    assert report["owner"] == "mapper"
    assert report["consumers"] == ["loop"]


def test_cli_routes_contract_inventory(capsys, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema": "simplicio.contract-registry/v1", "contracts": []}))
    assert main(["contracts", "inventory", "--root", f"test={tmp_path}", "--registry", str(registry), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "simplicio.contract-registry-inventory/v1"


def test_json_and_registry_input_errors(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json")
    scalar = tmp_path / "scalar.json"
    scalar.write_text("[]")
    for path in (invalid, scalar):
        try:
            _read_json(path)
        except ContractRegistryError:
            pass
        else:
            raise AssertionError("invalid JSON input was accepted")
    try:
        load_registry(invalid)
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("invalid registry was accepted")
    try:
        load_registry(tmp_path / "missing.json")
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("missing registry was accepted")


def test_inventory_scans_languages_and_ignores_invalid_schema_json(tmp_path):
    (tmp_path / "a.py").write_text("# simplicio.python/v1\n")
    (tmp_path / "b.rs").write_text("// simplicio.rust/v1\n")
    (tmp_path / "c.ts").write_text("// simplicio.typescript/v1\n")
    (tmp_path / "d.md").write_text("simplicio.docs/v1\n")
    (tmp_path / "broken.schema.json").write_text('{"$id":"simplicio.broken/v1"')
    report = inventory_contracts([("repo", tmp_path)], registry={"contracts": [{"id": "simplicio.python/v1"}]})
    by_id = {item["id"]: item for item in report["contracts"]}
    assert by_id["simplicio.python/v1"]["observations"][0]["language"] == "python"
    assert by_id["simplicio.rust/v1"]["observations"][0]["language"] == "rust"
    assert by_id["simplicio.typescript/v1"]["observations"][0]["language"] == "javascript-typescript"
    assert by_id["simplicio.docs/v1"]["observations"][0]["language"] == "data"
    assert by_id["simplicio.broken/v1"]["schema_files"] == []
    assert "simplicio.docs/v1" in report["unregistered"]
    try:
        inventory_contracts([("missing", tmp_path / "missing")])
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("missing root was accepted")


def test_validate_registry_reports_structural_failures(tmp_path):
    bad_schema = tmp_path / "bad.json"
    bad_schema.write_text("not-json")
    malformed = _entry(contract_id="invalid", schema_path="missing.json")
    malformed["owner"] = "loop"
    malformed["consumers"] = []
    malformed["versions"]["current"] = "latest"
    missing_fields = {"id": "simplicio.missing/v1"}
    duplicate = _entry()
    report = validate_registry({"schema": "simplicio.contract-registry/v1", "contracts": [malformed, missing_fields, duplicate, duplicate, {"id": "simplicio.bad/v1", "canonical": {"schema_path": "bad.json", "sha256": "abc", "fixture_paths": []}}]}, root=tmp_path)
    codes = {error["code"] for error in report["errors"]}
    assert {"CANONICAL_SCHEMA_MISSING", "OWNER_INVALID", "CONSUMERS_MISSING", "VERSION_INVALID", "DUPLICATE_IDENTIFIER", "ENTRY_FIELD_MISSING", "IDENTIFIER_INVALID"} <= codes
    bad_hash = _entry(schema_path="bad.json")
    bad_hash["canonical"]["sha256"] = "abc"
    assert any(error["code"] == "CANONICAL_SCHEMA_INVALID" for error in validate_registry({"schema": "simplicio.contract-registry/v1", "contracts": [bad_hash]}, root=tmp_path)["errors"])


def test_diff_accepts_json_strings_and_version_changes():
    old = {"versions": {"current": "v1"}, "canonical_schema": {"type": "object"}}
    new = {"versions": {"current": "v2"}, "canonical_schema": {"type": "object"}}
    assert diff_contracts(json.dumps(old), json.dumps(new))["classification"] == "breaking"
    try:
        diff_contracts("{", "{}")
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("invalid diff input was accepted")
    assert diff_contracts("[1]", "[2]")["classification"] == "ambiguous"
    try:
        impact_contract({"contracts": []}, "simplicio.unknown/v1")
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("unknown impact was accepted")


def test_cli_errors_and_ordered_impact_and_diff(capsys, tmp_path):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema": "simplicio.contract-registry/v1", "contracts": [_entry()]}))
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps({"type": "object"}))
    new.write_text(json.dumps({"type": "object", "properties": {"a": {"type": "string"}}}))
    assert run_contracts_cli(["impact", "simplicio.example/v1", "--registry", str(registry), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "simplicio.example/v1"
    assert run_contracts_cli(["diff", "--old", str(old), "--new", str(new), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["classification"] == "additive"
    assert run_contracts_cli(["impact", "--registry", str(registry), "--json"]) == 1
    assert "requires a contract id" in capsys.readouterr().out
    assert run_contracts_cli(["diff", "--json"]) == 1
    assert "requires --old and --new" in capsys.readouterr().out
    assert run_contracts_cli(["unknown"]) == 2
    assert _parse_roots([], tmp_path)[0][0] == "mapper"
    try:
        _parse_roots(["bad"], tmp_path)
    except ContractRegistryError:
        pass
    else:
        raise AssertionError("invalid root was accepted")

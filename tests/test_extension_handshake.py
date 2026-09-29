"""Unit, integration, system and regression coverage for issue #621."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from simplicio_loop import cli
from simplicio_loop.extension_handshake import (
    HANDSHAKE_SCHEMA, ExtensionHandshakeError, extension_handshake,
    runtime_fingerprint, verify_runtime_fingerprint,
)
from simplicio_loop.extension_registry import ExtensionRegistry

CAPABILITIES = ["process_supervision", "stage_composition",
                "receipt_invalidation", "run_outcome", "oracle_delegation"]

def manifest(**changes):
    value = {
        "schema": "simplicio.loop-extension/v1", "extension_id": "full_ext",
        "name": "Fully capable", "version": "1.2.3", "domain": "test",
        "requires_core": {"min_version": "3.0.0", "max_version": "4.0.0"},
        "capabilities": {"provides": list(CAPABILITIES)},
        "stage_overlays": [{"op": "refine", "hook": "quality",
                            "gates": {"extension_quality": "block"}}],
        "role_bindings": [{"role_id": "reviewer", "specializes": "quality"}],
        "effect_handlers": [{"effect_id": "publish", "idempotent": True,
                             "requires_fence_token": True, "requires_receipt": True}],
        "receipt_schemas": [{"schema_id": "example.receipt/v1", "version": "1.0.0"}],
    }
    value.update(changes)
    return value

class Runtime:
    manifest = manifest()
    bindings = {"reviewer": lambda: None, "publish": lambda: None}

def registry(runtime=Runtime()):
    value = ExtensionRegistry()
    value.register(runtime.manifest, runtime=runtime)
    return value

def test_fully_capable_provider_dry_run_is_operational_and_read_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = list(tmp_path.iterdir())
    result = extension_handshake("full_ext", "strict", registry=registry())
    assert result["schema"] == HANDSHAKE_SCHEMA
    assert result["status"] == "PASS"
    assert result["composition"]["dry_run"] is True
    assert result["composition"]["worker_execution"] is False
    assert result["authorities"] == {"completion_oracle": "simplicio-loop", "exclusive": True,
                                      "provider_may_complete": False}
    assert "hub" not in result["contracts"]
    assert result["contracts"]["process_spec"] == "simplicio.process-spec/v1"
    assert result["contracts"]["invalidation"] == "simplicio.receipt-invalidation/v1"
    assert result["contracts"]["run_outcome"] == "simplicio.run-outcome/v1"
    assert list(tmp_path.iterdir()) == before

def test_manifest_only_registration_is_rejected():
    value = ExtensionRegistry(); value.register(manifest())
    with pytest.raises(ExtensionHandshakeError, match="runtime bindings") as caught:
        extension_handshake("full_ext", "strict", registry=value)
    assert caught.value.reason_code == "PROVIDER_RUNTIME_MISSING"

def test_missing_provider_handler_role_schema_and_capability_are_explicit():
    empty = ExtensionRegistry()
    with pytest.raises(ExtensionHandshakeError) as caught:
        extension_handshake("missing", "strict", registry=empty)
    assert caught.value.reason_code == "PROVIDER_UNREGISTERED"
    cases = []
    bad = Runtime(); bad.manifest = manifest(); bad.bindings = {"reviewer": lambda: None}
    cases.append((bad, "HANDLER_MISSING"))
    bad = Runtime(); bad.manifest = manifest(role_bindings=[]); bad.bindings = {"publish": lambda: None}
    cases.append((bad, "ROLE_MISSING"))
    bad = Runtime(); bad.manifest = manifest(receipt_schemas=[])
    cases.append((bad, "RECEIPT_SCHEMA_MISSING"))
    bad = Runtime(); bad.manifest = manifest(capabilities={"provides": CAPABILITIES[:-1]})
    cases.append((bad, "CAPABILITY_MISSING"))
    for provider, reason in cases:
        with pytest.raises(ExtensionHandshakeError) as error:
            extension_handshake("full_ext", "strict", registry=registry(provider))
        assert error.value.reason_code == reason

@pytest.mark.parametrize("schema", ["simplicio.extension-handshake/v0", "simplicio.extension-handshake/v2", "future/v99"])
def test_unknown_versions_never_downgrade(schema):
    with pytest.raises(ExtensionHandshakeError) as caught:
        extension_handshake("full_ext", "strict", requested_schema=schema, registry=registry())
    assert caught.value.reason_code == "UNSUPPORTED_HANDSHAKE_SCHEMA"

def test_core_version_negotiation_matrix():
    for requires, passes in [
        ({"min_version": "3.0.0", "max_version": "4.0.0"}, True),
        ({"min_version": "99.0.0"}, False), ({"max_version": "1.0.0"}, False),
    ]:
        provider = Runtime(); provider.manifest = manifest(requires_core=requires)
        if passes:
            assert extension_handshake("full_ext", "p", registry=registry(provider))["status"] == "PASS"
        else:
            with pytest.raises(ExtensionHandshakeError) as caught:
                extension_handshake("full_ext", "p", registry=registry(provider))
            assert caught.value.reason_code == "CORE_VERSION_UNSUPPORTED"

def test_registry_loads_provider_runtime_through_production_entrypoint_path(monkeypatch):
    class EP:
        name = "full_ext"
        def load(self): return lambda: Runtime()
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kwargs: [EP()])
    value = ExtensionRegistry(); value.discover_entry_points()
    assert value.runtime("full_ext").manifest["version"] == "1.2.3"
    assert extension_handshake("full_ext", "strict", registry=value)["status"] == "PASS"

def test_runtime_replacement_and_two_binary_mismatch_are_rejected(tmp_path, monkeypatch):
    fingerprint = runtime_fingerprint()
    assert verify_runtime_fingerprint(fingerprint) == fingerprint
    with mock.patch("simplicio_loop.extension_handshake.runtime_fingerprint", return_value="sha256:" + "0" * 64):
        with pytest.raises(ExtensionHandshakeError) as caught:
            verify_runtime_fingerprint(fingerprint)
        assert caught.value.reason_code == "RUNTIME_SUBSTITUTED"
    fake = tmp_path / "python"; fake.write_bytes(b"different executable")
    monkeypatch.setattr("simplicio_loop.extension_handshake.sys.executable", str(fake))
    assert runtime_fingerprint() != fingerprint

def test_run_fingerprint_gate_rejects_before_worker_execution(monkeypatch, capsys):
    conduct = mock.Mock()
    monkeypatch.setattr(cli, "conduct_run", conduct)
    rc = cli.run(".", "task.md", "implemented", 1, "provider", "policy", "sha256:" + "0" * 64)
    assert rc == 2 and not conduct.called
    assert "RUNTIME_SUBSTITUTED" in capsys.readouterr().err

def test_cli_doctor_system_surface(monkeypatch, capsys):
    monkeypatch.setattr("simplicio_loop.extension_handshake.ExtensionRegistry", lambda: registry())
    rc = cli.main(["extensions", "doctor", "--provider", "full_ext", "--policy", "strict", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["schema"] == HANDSHAKE_SCHEMA and payload["status"] == "PASS"

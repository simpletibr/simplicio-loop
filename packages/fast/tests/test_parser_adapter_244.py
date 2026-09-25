import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from simplicio_fast.parser_adapter import (
    ParserAdapterError,
    _git_ignored,
    adapter_capability,
    build_payload,
    build_payload_from_mapper,
    validate_payload,
)
from simplicio_fast.mapper_ingest import MapperIngestError


def _mapper_fixture(root: Path) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    source = root / "service.rs"
    source.write_text("fn resolve() -> i32 { 1 }\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    docs: dict[str, dict[str, object]] = {
        "context_snapshot": {
            "schema": "simplicio.context-snapshot/v1",
            "graph": {
                "nodes": [
                    {
                        "id": "symbol:service.rs::resolve",
                        "source": {"file": "service.rs", "line": 1},
                    },
                    {"id": "file:service.rs", "source": {"file": "service.rs"}},
                ]
            },
        },
        "project_map": {
            "schema": "simplicio.project-map/v1",
            "files": [
                {"path": "service.rs", "language": "rust", "file_hash": digest}
            ],
            "dependencies": {},
        },
        "symbol_index": {
            "schema": "simplicio.symbol-index/v1",
            "symbols": [
                {
                    "name": "resolve",
                    "qualified_name": "service.rs::resolve",
                    "kind": "function",
                    "language": "rust",
                    "defined_in": "service.rs",
                    "line": 1,
                }
            ],
        },
        "call_graph": {
            "schema": "simplicio.call-graph/v1",
            "edges": [
                {
                    "type": "calls",
                    "source_file": "service.rs",
                    "source_symbol": "service.rs::resolve",
                    "target_symbol": "service.rs::resolve",
                    "confidence": 0.5,
                }
            ],
        },
    }
    path_names = {
        "context_snapshot": "context-snapshot.json",
        "project_map": "project-map.json",
        "symbol_index": "symbol-index.json",
        "call_graph": "call-graph.json",
    }
    artifact_dir = root / ".simplicio"
    artifact_dir.mkdir()
    artifacts: list[dict[str, str]] = []
    for name, document in docs.items():
        relative = f".simplicio/{path_names[name]}"
        (root / relative).write_text(json.dumps(document), encoding="utf-8")
        artifacts.append({"name": name, "path": relative})
    return {
        "commit": "a" * 40,
        "generation": "generation-1",
        "artifacts": artifacts,
        "changed_paths": [],
    }, docs


class ParserAdapter244Test(unittest.TestCase):
    def test_mapper_payload_file_metadata_and_git_ignore_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance, docs = _mapper_fixture(root)
            self.assertEqual(set(), _git_ignored(root, []))
            docs["project_map"]["files"] = [None]
            (root / ".simplicio/project-map.json").write_text(
                json.dumps(docs["project_map"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_files_invalid"):
                build_payload_from_mapper(root, {"ignored": True})
            docs["project_map"]["files"] = [{"path": "service.rs"}]
            (root / ".simplicio/project-map.json").write_text(
                json.dumps(docs["project_map"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_language_missing"):
                build_payload_from_mapper(root, {"ignored": True})
            docs["project_map"]["files"] = [
                {"path": "service.rs", "language": "text", "file_hash": "0" * 64}
            ]
            (root / ".simplicio/project-map.json").write_text(
                json.dumps(docs["project_map"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_symbols_invalid"):
                build_payload_from_mapper(root, {"ignored": True})

    def test_mapper_payload_rejects_decoder_envelope_relation_and_size_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance, docs = _mapper_fixture(root)

            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                side_effect=MapperIngestError("mapper_incomplete"),
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_incomplete"):
                build_payload_from_mapper(root, {"ignored": True})

            context_path = root / ".simplicio/context-snapshot.json"
            context_path.write_text("{not-json", encoding="utf-8")
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_artifact_invalid"):
                build_payload_from_mapper(root, {"ignored": True})
            context_path.write_text("[1, 2, 3]", encoding="utf-8")
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_artifact_invalid"):
                build_payload_from_mapper(root, {"ignored": True})
            context_path.write_text(json.dumps(docs["context_snapshot"]), encoding="utf-8")

            context_path.unlink()
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_artifact_missing"):
                build_payload_from_mapper(root, {"ignored": True})
            context_path.write_text(json.dumps(docs["context_snapshot"]), encoding="utf-8")

            docs["symbol_index"]["symbols"] = [None]
            (root / ".simplicio/symbol-index.json").write_text(
                json.dumps(docs["symbol_index"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_symbols_invalid"):
                build_payload_from_mapper(root, {"ignored": True})
            docs["symbol_index"]["symbols"] = [
                {
                    "name": "resolve",
                    "qualified_name": "service.rs::resolve",
                    "kind": "function",
                    "language": "rust",
                    "defined_in": "service.rs",
                    "line": 1,
                }
            ]
            (root / ".simplicio/symbol-index.json").write_text(
                json.dumps(docs["symbol_index"]), encoding="utf-8"
            )

            docs["call_graph"]["edges"] = [None]
            (root / ".simplicio/call-graph.json").write_text(
                json.dumps(docs["call_graph"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_relations_invalid"):
                build_payload_from_mapper(root, {"ignored": True})
            docs["call_graph"]["edges"] = [
                {
                    "type": "calls",
                    "source_file": "service.rs",
                    "source_symbol": "service.rs::resolve",
                    "target_symbol": "service.rs::resolve",
                    "confidence": 2,
                }
            ]
            (root / ".simplicio/call-graph.json").write_text(
                json.dumps(docs["call_graph"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_relation_confidence_invalid"):
                build_payload_from_mapper(root, {"ignored": True})

            docs["call_graph"]["edges"][0]["confidence"] = 0.5
            (root / ".simplicio/call-graph.json").write_text(
                json.dumps(docs["call_graph"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), self.assertRaisesRegex(ParserAdapterError, "payload_limit_exceeded"):
                build_payload_from_mapper(
                    root, {"ignored": True}, limits={"max_payload_bytes": 1}
                )

    def test_mapper_payload_rejects_source_encoding_and_bounds(self) -> None:
        cases = (
            ("source_missing", lambda root, docs: docs["project_map"]["files"].__setitem__(0, {
                "path": "missing.rs", "language": "rust", "file_hash": "0" * 64
            })),
            ("source_digest_mismatch", lambda root, docs: docs["project_map"]["files"][0].__setitem__("file_hash", "0" * 64)),
            ("encoding_invalid", lambda root, docs: (root / "service.rs").write_bytes(b"fn bad() { \xff }\n")),
            ("mapper_symbols_missing", lambda root, docs: docs["symbol_index"].__setitem__("symbols", None)),
            ("mapper_graph_missing", lambda root, docs: docs["context_snapshot"].__setitem__("graph", None)),
            ("mapper_relations_missing", lambda root, docs: docs["call_graph"].__setitem__("edges", None)),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                provenance, docs = _mapper_fixture(root)
                mutate(root, docs)
                for name, document in docs.items():
                    artifact = next(item for item in provenance["artifacts"] if item["name"] == name)
                    (root / artifact["path"]).write_text(json.dumps(document), encoding="utf-8")
                if expected == "encoding_invalid":
                    digest = hashlib.sha256((root / "service.rs").read_bytes()).hexdigest()
                    docs["project_map"]["files"][0]["file_hash"] = digest
                    (root / ".simplicio/project-map.json").write_text(
                        json.dumps(docs["project_map"]), encoding="utf-8"
                    )
                with patch(
                    "simplicio_fast.parser_adapter.validate_handoff",
                    return_value=provenance,
                ), self.assertRaisesRegex(ParserAdapterError, expected):
                    build_payload_from_mapper(root, {"ignored": True})

    def test_mapper_payload_enforces_file_symbol_and_relation_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance, docs = _mapper_fixture(root)
            second = root / "second.rs"
            second.write_text("fn second() -> i32 { 2 }\n", encoding="utf-8")
            docs["project_map"]["files"].append(
                {
                    "path": "second.rs",
                    "language": "rust",
                    "file_hash": hashlib.sha256(second.read_bytes()).hexdigest(),
                }
            )
            (root / ".simplicio/project-map.json").write_text(
                json.dumps(docs["project_map"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ):
                with self.assertRaisesRegex(ParserAdapterError, "file_limit_exceeded"):
                    build_payload_from_mapper(root, {"ignored": True}, limits={"max_files": 1})
            docs["project_map"]["files"].pop()
            docs["symbol_index"]["symbols"].append(
                {
                    "name": "second",
                    "qualified_name": "service.rs::second",
                    "kind": "function",
                    "language": "rust",
                    "defined_in": "service.rs",
                    "line": 1,
                }
            )
            docs["context_snapshot"]["graph"]["nodes"].append(
                {
                    "id": "symbol:service.rs::second",
                    "source": {"file": "service.rs", "line": 1},
                }
            )
            (root / ".simplicio/symbol-index.json").write_text(
                json.dumps(docs["symbol_index"]), encoding="utf-8"
            )
            (root / ".simplicio/context-snapshot.json").write_text(
                json.dumps(docs["context_snapshot"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ):
                with self.assertRaisesRegex(ParserAdapterError, "symbol_limit_exceeded"):
                    build_payload_from_mapper(root, {"ignored": True}, limits={"max_symbols": 1})
            docs["symbol_index"]["symbols"].pop()
            docs["call_graph"]["edges"].append(dict(docs["call_graph"]["edges"][0]))
            (root / ".simplicio/call-graph.json").write_text(
                json.dumps(docs["call_graph"]), encoding="utf-8"
            )
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ):
                with self.assertRaisesRegex(ParserAdapterError, "relation_limit_exceeded"):
                    build_payload_from_mapper(root, {"ignored": True}, limits={"max_relations": 1})

    def test_mapper_payload_rejects_schema_source_and_relation_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance, docs = _mapper_fixture(root)

            def build() -> dict[str, object]:
                with patch(
                    "simplicio_fast.parser_adapter.validate_handoff",
                    return_value=provenance,
                ):
                    return build_payload_from_mapper(root, {"ignored": True})

            broken_artifacts = {
                **provenance,
                "artifacts": [
                    item
                    for item in provenance["artifacts"]
                    if item["name"] != "call_graph"
                ],
            }
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=broken_artifacts,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_artifact_missing"):
                build_payload_from_mapper(root, {"ignored": True})

            malformed_artifacts = {**provenance, "artifacts": [1]}
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=malformed_artifacts,
            ), self.assertRaisesRegex(ParserAdapterError, "mapper_artifact_missing"):
                build_payload_from_mapper(root, {"ignored": True})

            for name, expected in (
                ("symbol_index", "mapper_schema_unsupported"),
                ("project_map", "mapper_schema_unsupported"),
                ("context_snapshot", "mapper_schema_unsupported"),
                ("call_graph", "mapper_schema_unsupported"),
            ):
                original = docs[name]["schema"]
                docs[name]["schema"] = "future.schema/v99"
                (root / provenance["artifacts"][[x["name"] for x in provenance["artifacts"]].index(name)]["path"]).write_text(
                    json.dumps(docs[name]), encoding="utf-8"
                )
                with self.assertRaisesRegex(ParserAdapterError, expected):
                    build()
                docs[name]["schema"] = original
                (root / provenance["artifacts"][[x["name"] for x in provenance["artifacts"]].index(name)]["path"]).write_text(
                    json.dumps(docs[name]), encoding="utf-8"
                )

            project = docs["project_map"]
            project["files"] = None
            (root / ".simplicio/project-map.json").write_text(json.dumps(project), encoding="utf-8")
            with self.assertRaisesRegex(ParserAdapterError, "mapper_files_missing"):
                build()

    def test_mapper_payload_reports_partial_relations_and_skips_ignored_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provenance, docs = _mapper_fixture(root)
            ignored = root / ".pytest-basetemp-case" / "ignored.py"
            ignored.parent.mkdir()
            ignored.write_text("def ignored():\n    return True\n", encoding="utf-8")
            project = docs["project_map"]
            project["files"].append(
                {
                    "path": ".pytest-basetemp-case/ignored.py",
                    "language": "python",
                    "file_hash": hashlib.sha256(ignored.read_bytes()).hexdigest(),
                }
            )
            (root / ".gitignore").write_text(".pytest-basetemp-*/\n", encoding="utf-8")
            (root / ".simplicio/project-map.json").write_text(json.dumps(project), encoding="utf-8")
            calls = docs["call_graph"]
            calls["edges"].append(
                {
                    "type": "calls",
                    "source_file": "service.rs",
                    "source_symbol": "service.rs::missing",
                    "target_symbol": "service.rs::resolve",
                    "confidence": 0.5,
                }
            )
            calls["edges"].append(
                {
                    "type": "imports",
                    "source_file": "service.rs",
                    "source_symbol": None,
                    "target_symbol": None,
                    "import": "std::fmt",
                    "confidence": 0.5,
                }
            )
            calls["edges"].append(
                {
                    "type": "future-edge",
                    "source_file": "service.rs",
                    "source_symbol": None,
                    "target_symbol": "service.rs::resolve",
                    "confidence": 0.5,
                }
            )
            (root / ".simplicio/call-graph.json").write_text(json.dumps(calls), encoding="utf-8")
            with patch(
                "simplicio_fast.parser_adapter.validate_handoff",
                return_value=provenance,
            ), patch(
                "simplicio_fast.parser_adapter._git_ignored",
                return_value={".pytest-basetemp-case/ignored.py"},
            ):
                payload = build_payload_from_mapper(root, {"ignored": True})
            self.assertEqual("partial", payload["completeness"])
            self.assertTrue(any(item["code"] == "mapper_relation_id_missing" for item in payload["diagnostics"]))
            self.assertTrue(any(item["code"] == "mapper_relation_kind_unsupported" for item in payload["diagnostics"]))
            self.assertIn("import", {item["kind"] for item in payload["relations"]})
            self.assertNotIn(
                ".pytest-basetemp-case/ignored.py",
                [item["path"] for item in payload["files"]],
            )
            self.assertEqual("valid", validate_payload(payload, root=root)["status"])
    def test_mapper_facts_preserve_context_ids_and_validate_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.rs").write_text(
                "fn resolve() -> i32 { 1 }\n", encoding="utf-8"
            )
            digest = hashlib.sha256((root / "service.rs").read_bytes()).hexdigest()
            artifact_names = {
                "context_snapshot": {
                    "schema": "simplicio.context-snapshot/v1",
                    "graph": {
                        "nodes": [
                            {
                                "id": "symbol:service.rs::resolve",
                                "source": {"file": "service.rs", "line": 1},
                            }
                        ]
                    },
                },
                "project_map": {
                    "schema": "simplicio.project-map/v1",
                    "files": [
                        {"path": "service.rs", "language": "rust", "file_hash": digest}
                    ],
                    "dependencies": {"features": ["default"]},
                },
                "symbol_index": {
                    "schema": "simplicio.symbol-index/v1",
                    "symbols": [
                        {
                            "name": "resolve",
                            "qualified_name": "service.rs::resolve",
                            "kind": "function",
                            "language": "rust",
                            "defined_in": "service.rs",
                            "line": 1,
                        }
                    ],
                },
                "call_graph": {
                    "schema": "simplicio.call-graph/v1",
                    "edges": [
                        {
                            "type": "calls",
                            "source_file": "service.rs",
                            "source_symbol": "service.rs::resolve",
                            "target_symbol": "service.rs::resolve",
                            "confidence": 0.5,
                        }
                    ],
                },
            }
            artifact_paths = []
            for name, value in artifact_names.items():
                path = root / ".simplicio" / {
                    "context_snapshot": "context-snapshot.json",
                    "project_map": "project-map.json",
                    "symbol_index": "symbol-index.json",
                    "call_graph": "call-graph.json",
                }[name]
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")
                artifact_paths.append({"name": name, "path": str(path.relative_to(root))})
            provenance = {
                "commit": "a" * 40,
                "generation": "generation-1",
                "artifacts": artifact_paths,
                "changed_paths": [],
            }
            with patch("simplicio_fast.parser_adapter.validate_handoff", return_value=provenance):
                payload = build_payload_from_mapper(root, {"ignored": True})
            self.assertEqual("symbol:service.rs::resolve", payload["symbols"][0]["id"])
            self.assertEqual("call", payload["relations"][0]["kind"])
            self.assertEqual("valid", validate_payload(payload, root=root)["status"])

    def test_mapper_facts_reject_missing_context_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.ts"
            source.write_text("export function run() {}\n", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            (root / ".simplicio").mkdir()
            docs = {
                "context_snapshot.json": {
                    "schema": "simplicio.context-snapshot/v1",
                    "graph": {"nodes": []},
                },
                "project-map.json": {
                    "schema": "simplicio.project-map/v1",
                    "files": [{"path": "service.ts", "language": "typescript", "file_hash": digest}],
                    "dependencies": {},
                },
                "symbol-index.json": {
                    "schema": "simplicio.symbol-index/v1",
                    "symbols": [{
                        "name": "run", "qualified_name": "service.ts::run", "kind": "function",
                        "language": "typescript", "defined_in": "service.ts", "line": 1,
                    }],
                },
                "call-graph.json": {"schema": "simplicio.call-graph/v1", "edges": []},
            }
            for name, value in docs.items():
                (root / ".simplicio" / name).write_text(json.dumps(value), encoding="utf-8")
            provenance = {
                "commit": "a" * 40,
                "generation": "generation-1",
                "artifacts": [
                    {"name": key.removesuffix(".json").replace("-", "_"), "path": f".simplicio/{key}"}
                    for key in docs
                ],
                "changed_paths": [],
            }
            with patch("simplicio_fast.parser_adapter.validate_handoff", return_value=provenance):
                with self.assertRaisesRegex(ParserAdapterError, "mapper_id_missing"):
                    build_payload_from_mapper(root, {"ignored": True})

    def test_capability_receipt_is_versioned_and_bounded(self) -> None:
        capability = adapter_capability()
        self.assertEqual("simplicio.fast.parser-adapter/v1", capability["schema"])
        self.assertEqual("ready", capability["health"])
        self.assertEqual("contract", capability["completeness"])
        self.assertEqual("1", capability["version"])
        self.assertEqual(64, len(capability["fingerprints"]["contract_sha256"]))
        self.assertIn("integrated", capability["modes"])

    def test_builder_rejects_invalid_mode_limits_and_previous_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text("def run():\n    return True\n", encoding="utf-8")
            with self.assertRaisesRegex(ParserAdapterError, "mode_invalid"):
                build_payload(root, mode="unknown")
            with self.assertRaisesRegex(ParserAdapterError, "limit_invalid"):
                build_payload(root, limits={"max_files": 0})
            with self.assertRaisesRegex(ParserAdapterError, "limit_invalid"):
                build_payload(root, limits={"max_files": True})
            previous = build_payload(root)
            with self.assertRaisesRegex(
                ParserAdapterError, "previous_payload_requires_changed_paths"
            ):
                build_payload(root, previous_payload=previous)

    def test_builder_reports_encoding_and_parse_failures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.py").write_bytes(b"def bad(:\n\xff")
            payload = build_payload(root)
            self.assertEqual("partial", payload["completeness"])
            self.assertEqual("encoding_invalid", payload["diagnostics"][0]["code"])
            (root / "bad.py").write_text("def bad(:\n    pass\n", encoding="utf-8")
            payload = build_payload(root)
            self.assertEqual("parse_failed", payload["diagnostics"][0]["code"])

    def test_validator_rejects_contract_metadata_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text("def run():\n    return True\n", encoding="utf-8")
            payload = build_payload(root)
            for field, value, reason in (
                ("schema", "future", "schema_unsupported"),
                ("mode", "future", "mode_invalid"),
                ("producer", "other", "producer_invalid"),
                ("adapter_version", "2", "adapter_version_unsupported"),
                ("commit", "short", "commit_invalid"),
                ("changed_paths", "bad", "changed_paths_invalid"),
                ("completeness", "unknown", "completeness_invalid"),
                ("diagnostics", "bad", "diagnostics_invalid"),
                ("invalidation", "bad", "invalidation_invalid"),
                ("workspace_fingerprints", "bad", "workspace_fingerprints_invalid"),
            ):
                broken = copy.deepcopy(payload)
                broken[field] = value
                with self.subTest(field=field):
                    with self.assertRaisesRegex(ParserAdapterError, reason):
                        validate_payload(broken)

    def test_validator_rejects_untyped_nested_records_and_non_mapping_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            payload = build_payload(root)
            with self.assertRaisesRegex(ParserAdapterError, "payload_shape_invalid"):
                validate_payload([])  # type: ignore[arg-type]

            broken = copy.deepcopy(payload)
            broken["diagnostics"] = [{"path": "service.py", "code": "bad", "detail": 1}]
            with self.assertRaisesRegex(ParserAdapterError, "diagnostics_invalid"):
                validate_payload(broken)

            broken = copy.deepcopy(payload)
            broken["files"][0]["sha256"] = "g" * 64
            with self.assertRaisesRegex(ParserAdapterError, "file_digest_invalid"):
                validate_payload(broken)

            broken = copy.deepcopy(payload)
            broken["files"][0]["id"] = 1
            with self.assertRaisesRegex(ParserAdapterError, "file_invalid"):
                validate_payload(broken)

    def test_integrated_mode_requires_mapper_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ParserAdapterError, "mapper_required"):
                build_payload(root, mode="integrated")
            payload = build_payload(
                root,
                mode="integrated",
                mapper_generation="mapper-g1",
                commit="a" * 40,
            )
            self.assertEqual("integrated", payload["mode"])

    def test_generated_directories_are_not_ingested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src.py").write_text(
                "def source():\n    return 1\n", encoding="utf-8"
            )
            generated = root / "target"
            generated.mkdir()
            (generated / "generated.rs").write_text(
                "fn generated() {}\n", encoding="utf-8"
            )
            payload = build_payload(root)
            self.assertEqual(["src.py"], [item["path"] for item in payload["files"]])

    def test_python_payload_is_deterministic_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "class Service:\n    def run(self):\n        return True\n",
                encoding="utf-8",
            )
            first = build_payload(root)
            second = build_payload(root)
            self.assertEqual(first, second)
            receipt = validate_payload(first)
            self.assertEqual("valid", receipt["status"])
            self.assertEqual(2, receipt["symbols"])
            self.assertGreaterEqual(receipt["relations"], 2)
            self.assertIn("definition", {item["kind"] for item in first["relations"]})
            self.assertEqual("1", first["adapter_version"])
            self.assertEqual({}, first["workspace_fingerprints"])

    def test_python_relations_preserve_calls_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def helper():\n    return True\n\ndef test_helper():\n    return helper()\n",
                encoding="utf-8",
            )
            payload = build_payload(root)
            kinds = {item["kind"] for item in payload["relations"]}
            self.assertTrue({"definition", "call", "test"} <= kinds)

    def test_lexical_language_adapters_emit_relations(self) -> None:
        fixtures = {
            "service.ts": 'import { helper } from "./helper";\nexport function testService() { return helper(); }\n',
            "service.rs": "use crate::helper;\nfn test_service() {}\n",
            "service.cs": "using System.Text;\npublic class Service {}\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in fixtures.items():
                (root / name).write_text(source, encoding="utf-8")
            payload = build_payload(root)
            by_language = {
                item["language"]: {
                    relation["kind"]
                    for relation in payload["relations"]
                    if relation["file"] == item["path"]
                }
                for item in payload["files"]
            }
            self.assertIn("import", by_language["typescript"])
            self.assertIn("definition", by_language["rust"])
            self.assertIn("import", by_language["csharp"])
            self.assertEqual(
                {"csharp", "rust", "typescript"},
                set(payload["workspace_fingerprints"]),
            )
            assert payload["completeness"] == "partial"
            assert {
                item["path"]
                for item in payload["diagnostics"]
                if item["code"] == "native_parser_unavailable"
            } == set(fixtures)

    def test_changed_paths_are_scoped_and_invalid_payloads_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            payload = build_payload(root, changed_paths=["one.py"])
            self.assertEqual(["one.py"], payload["changed_paths"])
            self.assertEqual(["one.py"], [item["path"] for item in payload["files"]])
            broken = copy.deepcopy(payload)
            broken["payload_sha256"] = "0" * 64
            with self.assertRaisesRegex(ParserAdapterError, "payload_digest_mismatch"):
                validate_payload(broken)
            with self.assertRaisesRegex(ParserAdapterError, "path_escape"):
                build_payload(root, changed_paths=["../outside.py"])
            for alias in ("one/./service.py", "one//service.py", "one\\..\\service.py"):
                with self.subTest(alias=alias), self.assertRaisesRegex(ParserAdapterError, "path_escape"):
                    build_payload(root, changed_paths=[alias])

    def test_previous_payload_reuses_unchanged_files_and_reports_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            previous = build_payload(root)
            (root / "one.py").write_text("def one():\n    return 3\n", encoding="utf-8")
            (root / "two.py").unlink()

            current = build_payload(
                root,
                changed_paths=["one.py", "two.py"],
                previous_payload=previous,
            )
            assert [item["path"] for item in current["files"]] == ["one.py"]
            assert current["invalidation"] == {
                "schema": "simplicio.fast.parser-invalidation/v1",
                "requested_paths": ["one.py", "two.py"],
                "parsed_paths": ["one.py"],
                "reused_paths": [],
                "deleted_paths": ["two.py"],
                "reason_codes": ["explicit_changed_paths", "previous_payload_reuse"],
            }

    def test_previous_payload_reuses_unmodified_file_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            previous = build_payload(root)
            (root / "one.py").write_text("def one():\n    return 3\n", encoding="utf-8")

            current = build_payload(
                root,
                changed_paths=["one.py"],
                previous_payload=previous,
            )
            assert {item["path"] for item in current["files"]} == {"one.py", "two.py"}
            assert current["invalidation"]["parsed_paths"] == ["one.py"]
            assert current["invalidation"]["reused_paths"] == ["two.py"]

    def test_previous_payload_rejects_stale_unmodified_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
            previous = build_payload(root)
            (root / "one.py").write_text("def one():\n    return 3\n", encoding="utf-8")
            (root / "two.py").write_text("def two():\n    return 4\n", encoding="utf-8")
            with self.assertRaisesRegex(ParserAdapterError, "source_digest_mismatch"):
                build_payload(
                    root,
                    changed_paths=["one.py"],
                    previous_payload=previous,
                )

    def test_adapter_limits_fail_closed_before_returning_partial_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text(
                "def one():\n    return 1\n", encoding="utf-8"
            )
            (root / "two.py").write_text(
                "def two():\n    return 2\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ParserAdapterError, "file_limit_exceeded"):
                build_payload(root, limits={"max_files": 1})
            with self.assertRaisesRegex(ParserAdapterError, "symbol_limit_exceeded"):
                build_payload(root, limits={"max_symbols": 1})

    def test_validator_rejects_oversized_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            payload = build_payload(root)
            payload["symbols"] = payload["symbols"] * 1_000_001
            with self.assertRaisesRegex(ParserAdapterError, "symbol_limit_exceeded"):
                validate_payload(payload)

    def test_validator_rejects_incomplete_integrated_identity_and_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def run():\n    return True\n", encoding="utf-8"
            )
            payload = build_payload(
                root,
                mode="integrated",
                mapper_generation="mapper-g1",
                commit="a" * 40,
            )
            payload["commit"] = "short"
            with self.assertRaisesRegex(ParserAdapterError, "mapper_identity_invalid"):
                validate_payload(payload)
            payload = build_payload(root)
            payload["symbols"][0]["end_line"] = 0
            with self.assertRaisesRegex(ParserAdapterError, "symbol_invalid"):
                validate_payload(payload)

    def test_validator_rejects_invalid_relation_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def helper():\n    return True\n\ndef test_helper():\n    return helper()\n",
                encoding="utf-8",
            )
            payload = build_payload(root)
            payload["relations"][0]["confidence"] = 2
            with self.assertRaisesRegex(ParserAdapterError, "relation_file_missing"):
                validate_payload(payload)


if __name__ == "__main__":
    unittest.main()

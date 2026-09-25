import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.processor import ProjectProcessor, build_snapshot, load_changeset


class ProjectProcessorTest(unittest.TestCase):
    @staticmethod
    def _changeset(source: Path, content: str) -> dict[str, object]:
        return {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": source.name,
                    "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "replacements": [
                        {"start_line": 1, "end_line": 1, "content": content}
                    ],
                }
            ],
        }

    def test_ingest_understand_plan_and_guarded_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "users.py"
            source.write_text(
                "class UserService:\n"
                "    def create_user(self, name: str) -> str:\n"
                "        return name\n"
            )
            processor = ProjectProcessor(root, root / ".simplicio/fast/project.sfast")

            ingest = processor.ingest()
            self.assertEqual("simplicio.fast.ingest/v2", ingest["schema"])
            understanding = processor.understand("change UserService")
            self.assertIn("users.py", understanding.files)

            plan = processor.plan("change UserService")
            self.assertEqual("simplicio.fast.plandag/v2", plan["schema"])
            self.assertEqual(
                ["orient", "modify", "validate", "refresh"],
                [node["id"] for node in plan["nodes"]],
            )

            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "users.py",
                        "expected_sha256": expected,
                        "replacements": [
                            {
                                "start_line": 3,
                                "end_line": 3,
                                "content": "        return name.strip()",
                            }
                        ],
                    }
                ],
            }
            dry_run = processor.apply_changeset(changeset, write=False)
            self.assertEqual("dry-run", dry_run["mode"])
            self.assertNotIn("strip", source.read_text())

            written = processor.apply_changeset(changeset, write=True)
            self.assertEqual("write", written["mode"])
            self.assertIn("return name.strip()", source.read_text())

    def test_plan_exposes_context_handles_without_internal_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "service.py").write_text(
                "def ping():\n    return True\n", encoding="utf-8"
            )
            processor = ProjectProcessor(root, root / "project.sfast")
            plan = processor.plan("validate ping")

            handles = plan["context_handles"]
            self.assertTrue(handles)
            self.assertEqual(handles, plan["understanding"]["context_handles"])
            self.assertNotIn("context", plan["understanding"])
            self.assertEqual(64, len(handles[0]["source_sha256"]))
            self.assertEqual(
                plan["understanding"]["selection"]["generation"],
                handles[0]["generation"],
            )
            self.assertEqual(handles[0]["generation"], handles[0]["base_generation"])
            self.assertIsNone(handles[0]["overlay_generation"])
            for node in plan["nodes"][:2]:
                self.assertEqual(handles, node["inputs"]["context_handles"])

    def test_rejects_stale_changeset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": "app.py",
                        "expected_sha256": "0" * 64,
                        "replacements": [
                            {"start_line": 1, "end_line": 1, "content": "value = 2"}
                        ],
                    }
                ],
            }
            with self.assertRaisesRegex(ValueError, "stale source hash"):
                processor.apply_changeset(changeset, write=True)

    def test_native_refusal_returns_receipt_and_writes_internal_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")
            native = {
                "adapter": "simplicio-dev-cli",
                "status": "executed",
                "result": {
                    "status": "refused",
                    "code": "file_hash_mismatch",
                    "expected": "native-hash",
                    "actual": "fast-hash",
                },
            }

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=native
            ):
                receipt = processor.apply_changeset(changeset, write=True)

            self.assertEqual("simplicio.fast.apply-receipt/v2", receipt["schema"])
            self.assertEqual("fallback", receipt["executor"]["status"])
            self.assertEqual("refused", receipt["native"]["status"])
            self.assertEqual("file_hash_mismatch", receipt["reason_code"])
            self.assertTrue(receipt["applied"])
            self.assertTrue(receipt["write_attempted"])
            self.assertTrue(receipt["native"]["no_write_proof"])
            self.assertFalse(receipt["no_write_proof"])
            self.assertEqual("value = 2\n", source.read_text())
            file_receipt = receipt["files"][0]
            self.assertEqual(
                file_receipt["before_sha256"], file_receipt["expected_sha256"]
            )
            self.assertEqual(
                file_receipt["after_sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )

    def test_native_refusal_is_rolled_back_and_dry_run_proves_no_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            original = b"value = 1\n"
            source.write_bytes(original)
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")

            def refusing_native(*args: object, **kwargs: object) -> dict[str, object]:
                source.write_bytes(b"partial native write\n")
                return {
                    "adapter": "simplicio-dev-cli",
                    "status": "executed",
                    "result": {"status": "refused", "code": "file_hash_mismatch"},
                }

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                side_effect=refusing_native,
            ):
                receipt = processor.apply_changeset(changeset, write=False)

            self.assertEqual(original, source.read_bytes())
            self.assertTrue(receipt["no_write_proof"])
            self.assertEqual("dry_run", receipt["outcome"])
            self.assertFalse(receipt["write_attempted"])
            self.assertTrue(receipt["native"]["no_write_proof"])
            self.assertEqual(["app.py"], receipt["native"]["rollback"]["restored"])
            self.assertEqual(
                receipt["files"][0]["before_sha256"],
                receipt["files"][0]["after_sha256"],
            )

    def test_native_success_receipt_contains_before_and_after_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")

            def successful_native(*args: object, **kwargs: object) -> dict[str, object]:
                source.write_text("value = 2\n")
                return {
                    "adapter": "simplicio-dev-cli",
                    "status": "executed",
                    "result": {"status": "ok", "files": [{"path": "app.py"}]},
                }

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                side_effect=successful_native,
            ):
                receipt = processor.apply_changeset(changeset, write=True)

            self.assertEqual("simplicio-dev-cli", receipt["executor"]["adapter"])
            self.assertEqual("ok", receipt["native"]["status"])
            self.assertEqual("applied", receipt["outcome"])
            self.assertNotEqual(
                receipt["files"][0]["before_sha256"],
                receipt["files"][0]["after_sha256"],
            )
            self.assertEqual(
                receipt["native"]["after_sha256"]["app.py"],
                receipt["files"][0]["after_sha256"],
            )

    def test_native_ok_with_errors_is_treated_as_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")
            native = {
                "adapter": "simplicio-dev-cli",
                "status": "executed",
                "result": {
                    "status": "ok",
                    "applied": False,
                    "errors": [{"code": "post_edit_phase_skipped"}],
                },
            }

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=native
            ):
                receipt = processor.apply_changeset(changeset, write=False)

            self.assertEqual("fallback", receipt["executor"]["status"])
            self.assertEqual("native_adapter_refused", receipt["reason_code"])
            self.assertTrue(receipt["no_write_proof"])
            self.assertEqual("value = 1\n", source.read_text())

    def test_fallback_rolls_back_previous_files_when_a_later_replace_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.py"
            second = root / "second.py"
            first.write_text("first = 1\n")
            second.write_text("second = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [
                    {
                        "path": first.name,
                        "expected_sha256": hashlib.sha256(
                            first.read_bytes()
                        ).hexdigest(),
                        "replacements": [
                            {"start_line": 1, "end_line": 1, "content": "first = 2"}
                        ],
                    },
                    {
                        "path": second.name,
                        "expected_sha256": hashlib.sha256(
                            second.read_bytes()
                        ).hexdigest(),
                        "replacements": [
                            {"start_line": 1, "end_line": 1, "content": "second = 2"}
                        ],
                    },
                ],
            }
            real_atomic_replace = ProjectProcessor._atomic_replace
            calls = 0

            def fail_second(path: Path, data: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated replace failure")
                real_atomic_replace(path, data)

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=None
            ):
                with patch.object(
                    ProjectProcessor, "_atomic_replace", side_effect=fail_second
                ):
                    with self.assertRaisesRegex(OSError, "simulated replace failure"):
                        processor.apply_changeset(changeset, write=True)

            self.assertEqual("first = 1\n", first.read_text())
            self.assertEqual("second = 1\n", second.read_text())
            self.assertEqual([], list(root.glob("*.simplicio-fast")))

    def test_changeset_validation_rejects_invalid_contracts_before_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\nvalue = 2\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            with self.assertRaisesRegex(ValueError, "unsupported changeset"):
                processor.apply_changeset({}, write=False)
            with self.assertRaisesRegex(ValueError, "at least one"):
                processor.apply_changeset(
                    {"schema": "simplicio.fast.changeset/v2", "changes": []},
                    write=False,
                )
            with self.assertRaisesRegex(ValueError, "path and expected"):
                processor.apply_changeset(
                    {"schema": "simplicio.fast.changeset/v2", "changes": [{}]},
                    write=False,
                )
            with self.assertRaisesRegex(ValueError, "escapes root"):
                processor.apply_changeset(
                    {
                        "schema": "simplicio.fast.changeset/v2",
                        "changes": [
                            {
                                "path": "../outside.py",
                                "expected_sha256": "0" * 64,
                                "replacements": [],
                            }
                        ],
                    },
                    write=False,
                )
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            base = {
                "schema": "simplicio.fast.changeset/v2",
                "changes": [{"path": source.name, "expected_sha256": expected}],
            }
            with self.assertRaisesRegex(ValueError, "requires replacements"):
                processor.apply_changeset(
                    {**base, "changes": [{**base["changes"][0], "replacements": []}]},
                    write=False,
                )
            with self.assertRaisesRegex(ValueError, "invalid line"):
                processor.apply_changeset(
                    {
                        **base,
                        "changes": [
                            {
                                **base["changes"][0],
                                "replacements": [
                                    {"start_line": 1, "end_line": 3, "content": "x"}
                                ],
                            }
                        ],
                    },
                    write=False,
                )
            with self.assertRaisesRegex(ValueError, "overlapping"):
                processor.apply_changeset(
                    {
                        **base,
                        "changes": [
                            {
                                **base["changes"][0],
                                "replacements": [
                                    {"start_line": 1, "end_line": 1, "content": "x"},
                                    {"start_line": 1, "end_line": 1, "content": "y"},
                                ],
                            }
                        ],
                    },
                    write=False,
                )

    def test_native_adapter_errors_and_invalid_receipts_use_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")
            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                side_effect=ValueError("native exploded"),
            ):
                receipt = processor.apply_changeset(changeset, write=False)
            self.assertEqual("native_adapter_error", receipt["reason_code"])
            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                side_effect=RuntimeError("native crashed"),
            ):
                receipt = processor.apply_changeset(changeset, write=False)
            self.assertEqual("native_adapter_error", receipt["reason_code"])
            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                return_value={"result": None},
            ):
                receipt = processor.apply_changeset(changeset, write=False)
            self.assertEqual("invalid_native_receipt", receipt["reason_code"])

    def test_native_dry_run_mutation_is_rolled_back_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            original = source.write_text("value = 1\n")
            processor = ProjectProcessor(root, root / "project.sfast")
            changeset = self._changeset(source, "value = 2")

            def mutating_success(*args: object, **kwargs: object) -> dict[str, object]:
                source.write_text("native mutation\n")
                return {"result": {"status": "ok"}}

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset",
                side_effect=mutating_success,
            ):
                receipt = processor.apply_changeset(changeset, write=False)
            self.assertEqual("native_output_hash_mismatch", receipt["reason_code"])
            self.assertEqual("dry_run", receipt["outcome"])
            self.assertTrue(receipt["rollback"]["attempted"])
            self.assertEqual("value = 1\n", source.read_text())
            self.assertEqual(10, original)

    def test_understand_bootstraps_missing_snapshot_and_uses_fallback_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users.py").write_text(
                "class User:\n    def save(self):\n        return True\n"
            )
            snapshot = root / "project.sfast"
            processor = ProjectProcessor(root, snapshot)
            with patch.object(
                processor, "ingest", side_effect=lambda **_kwargs: build_snapshot(root, snapshot)
            ):
                understanding = processor.understand("term-not-found", max_results=5)
            self.assertEqual("simplicio.fast.understanding/v2", understanding.schema)
            self.assertTrue(understanding.context)

    def test_validation_commands_and_changeset_loader_cover_contract_variants(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processor = ProjectProcessor(root, root / "project.sfast")
            self.assertEqual(
                [["python", "-m", "compileall", "-q", "."]],
                processor._validation_commands(),
            )
            (root / "pyproject.toml").write_text("")
            (root / "package.json").write_text("{}")
            (root / "Cargo.toml").write_text("")
            commands = processor._validation_commands()
            self.assertEqual(3, len(commands))
            payload = root / "changeset.json"
            payload.write_text('{"schema": "simplicio.fast.changeset/v2"}')
            self.assertEqual(
                "simplicio.fast.changeset/v2", load_changeset(payload)["schema"]
            )
            payload.write_text("[]")
            with self.assertRaisesRegex(ValueError, "root must be an object"):
                load_changeset(payload)

    def test_consecutive_crlf_changesets_use_physical_byte_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_bytes(b"value = 1\r\n")
            processor = ProjectProcessor(root, root / "project.sfast")

            def changeset(value: int) -> dict[str, object]:
                return {
                    "schema": "simplicio.fast.changeset/v2",
                    "changes": [
                        {
                            "path": "app.py",
                            "expected_sha256": hashlib.sha256(
                                source.read_bytes()
                            ).hexdigest(),
                            "replacements": [
                                {
                                    "start_line": 1,
                                    "end_line": 1,
                                    "content": f"value = {value}",
                                }
                            ],
                        }
                    ],
                }

            with patch(
                "simplicio_fast.processor.run_dev_cli_changeset", return_value=None
            ):
                first = processor.apply_changeset(changeset(2), write=True)
                second = processor.apply_changeset(changeset(3), write=True)

            self.assertEqual(b"value = 3\r\n", source.read_bytes())
            self.assertEqual(
                first["files"][0]["after_sha256"],
                second["files"][0]["before_sha256"],
            )
            self.assertEqual(
                "raw-file-bytes", second["files"][0]["byte_representation"]
            )
            self.assertEqual("crlf", second["files"][0]["newline"])

    def test_semantic_selection_prefers_specific_symbols_over_generic_verbs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "quantized.py"
            target.write_text(
                "class QuantizedI8DotProduct:\n"
                "    def validate_quantized_i8_dot_product(self, vector):\n"
                "        return vector\n",
                encoding="utf-8",
            )
            generic = root / "validators.py"
            generic.write_text(
                "def validate(value):\n    return bool(value)\n",
                encoding="utf-8",
            )
            snapshot = root / "project.sfast"
            processor = ProjectProcessor(root, snapshot)
            processor.ingest()
            task = (
                "Validate the quantized i8 dot-product path from Tesser builtins "
                "through Runtime FFI and benchmark AVX2 against the scalar Rust reference"
            )
            understanding = processor.understand(task)
            plan = processor.plan(task)
            self.assertIn("quantized.py", understanding.files)
            self.assertNotIn("validators.py", understanding.files)
            self.assertEqual(
                "structural-semantic", understanding.selection["selection_mode"]
            )
            self.assertTrue(understanding.selection["selected"])
            self.assertEqual(
                understanding.files,
                plan["nodes"][1]["inputs"]["allowed_files"],
            )
            self.assertEqual(
                "structural-semantic",
                plan["understanding"]["selection"]["selection_mode"],
            )
            self.assertEqual(
                understanding.selection["generation"],
                plan["understanding"]["selection"]["generation"],
            )
            self.assertEqual(
                understanding.selection["candidate_terms"],
                plan["understanding"]["selection"]["candidate_terms"],
            )


if __name__ == "__main__":
    unittest.main()

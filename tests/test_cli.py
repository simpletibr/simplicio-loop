import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simplicio_fast.cli import (
    DEFAULT_BUILD_TIMEOUT_SECONDS,
    DEFAULT_MAPPER_MODE,
    DEFAULT_SNAPSHOT,
    WRITE_ALLOW_ENV,
    build_parser,
    main,
    source_commit,
)
from simplicio_fast.snapshot import Snapshot, build_snapshot


class ContextProvenanceTest(unittest.TestCase):
    def test_default_snapshot_is_inside_simplicio_state_root(self) -> None:
        args = build_parser().parse_args(["build"])
        self.assertEqual(".simplicio/fast/project.sfast", DEFAULT_SNAPSHOT)
        self.assertEqual(DEFAULT_SNAPSHOT, args.output)

    def test_mapper_mode_defaults_to_integrated_everywhere(self) -> None:
        parser = build_parser()
        self.assertEqual("integrated", DEFAULT_MAPPER_MODE)
        for argv in (
            ["build"],
            ["refresh"],
            ["ingest"],
            ["understand", "task"],
            ["plan", "task"],
            ["delivery", "task"],
        ):
            args = parser.parse_args(argv)
            self.assertEqual("integrated", args.mapper_mode, argv)
            self.assertIsNone(args.mapper_handoff)

    def test_integrated_ingest_build_refresh_fail_closed_without_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(
                "def save():\n    return True\n", encoding="utf-8"
            )
            snapshot = root / "snapshot.sfast"
            for command in ("ingest", "build", "refresh"):
                code, payload = self.invoke(
                    command, str(root), "-o", str(snapshot)
                )
                self.assertEqual(2, code, command)
                self.assertEqual("simplicio.fast.error/v1", payload["schema"])
                self.assertEqual("mapper_missing", payload["reason_code"])
                self.assertIn("never silently bootstraps", payload["message"])
                self.assertFalse(snapshot.exists())

    def test_write_without_allow_env_fails_closed(self) -> None:
        with patch.dict("os.environ", {WRITE_ALLOW_ENV: ""}, clear=False):
            os.environ.pop(WRITE_ALLOW_ENV, None)
            for argv in (
                ("apply", "changeset.json", "--write"),
                (
                    "delivery",
                    "task",
                    "--changeset",
                    "changeset.json",
                    "--write",
                ),
                (
                    "changeset",
                    "materialize",
                    "changeset.sfc",
                    "--journal",
                    "journal",
                    "--write",
                ),
            ):
                code, payload = self.invoke(*argv)
                self.assertEqual(2, code, argv)
                self.assertEqual("write_disabled", payload["reason_code"])
                self.assertIn("simplicio-dev-cli", payload["message"])

    def test_apply_and_write_help_name_dev_cli_as_mutation_owner(self) -> None:
        import argparse

        parser = build_parser()
        action = next(
            item
            for item in parser._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        apply_parser = action.choices["apply"]
        delivery_parser = action.choices["delivery"]
        changeset_action = next(
            item
            for item in action.choices["changeset"]._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        materialize_parser = changeset_action.choices["materialize"]
        for subparser in (apply_parser, delivery_parser, materialize_parser):
            self.assertIn("simplicio-dev-cli", subparser.description or "")
            write_help = subparser._option_string_actions["--write"].help or ""
            self.assertIn("SIMPLICIO_FAST_ALLOW_WRITE", write_help)
            self.assertIn("simplicio-dev-cli", write_help)
        self.assertIn("simplicio-dev-cli", parser.epilog or "")
        self.assertIn("SIMPLICIO_FAST_ALLOW_WRITE", parser.epilog or "")

    def test_large_repository_timeout_default_is_explicit_and_safe(self) -> None:
        for command in ("build", "refresh", "ingest"):
            args = build_parser().parse_args([command])
            self.assertEqual(DEFAULT_BUILD_TIMEOUT_SECONDS, args.timeout)
        self.assertEqual(180.0, DEFAULT_BUILD_TIMEOUT_SECONDS)

    def invoke(self, *args: str) -> tuple[int, dict[str, object]]:
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["simplicio-fast", *args]),
            contextlib.redirect_stdout(output),
        ):
            try:
                main()
            except SystemExit as error:
                exit_code = int(error.code)
            else:
                exit_code = 0
        return exit_code, json.loads(output.getvalue())

    def make_git_repo(self, root: Path) -> str:
        def run_git(*arguments: str, read_stdout: bool = False) -> str:
            command = ["git", *arguments]
            if not read_stdout:
                subprocess.run(
                    command,
                    check=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                return ""
            with tempfile.TemporaryFile(mode="w+") as output:
                subprocess.run(
                    command,
                    check=True,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    close_fds=True,
                )
                output.seek(0)
                return output.read().strip()

        run_git("init", "-b", "main", str(root))
        run_git("-C", str(root), "config", "user.email", "tests@example.invalid")
        run_git("-C", str(root), "config", "user.name", "Simplicio Tests")
        run_git("-C", str(root), "add", "sample.py")
        run_git("-C", str(root), "commit", "-m", "fixture")
        return run_git("-C", str(root), "rev-parse", "HEAD", read_stdout=True)

    def test_git_receipt_is_deterministic_and_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(
                "class User:\n    def save(self):\n        return True\n",
                encoding="utf-8",
            )
            commit = self.make_git_repo(root)
            snapshot = root / "snapshot.sfast"
            build_snapshot(root, snapshot)
            command = (
                "context",
                "save",
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--max-tokens",
                "80",
            )

            first_code, first = self.invoke(*command)
            second_code, second = self.invoke(*command)
            self.assertEqual(0, first_code)
            self.assertEqual(0, second_code)
            receipt = first["provenance"]
            self.assertEqual(receipt, second["provenance"])
            self.assertEqual("simplicio.fast.provenance/v1", receipt["schema"])
            self.assertEqual(str(root.resolve()), receipt["repository_root"])
            self.assertEqual(commit, receipt["source_commit"])
            self.assertIsNone(receipt["source_commit_reason"])
            self.assertEqual(str(snapshot.resolve()), receipt["snapshot_path"])
            digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            self.assertEqual(digest, receipt["snapshot_sha256"])
            self.assertEqual(f"SFAST001:{digest}", receipt["snapshot_generation"])
            self.assertEqual(first["limits"], receipt["limits"])
            self.assertEqual(len(first["spans"]), receipt["span_count"])

            (root / "sample.py").write_text(
                "class User:\n    def save(self):\n        return False\n",
                encoding="utf-8",
            )
            build_snapshot(root, snapshot)
            changed_code, changed = self.invoke(*command)
            self.assertEqual(0, changed_code)
            self.assertNotEqual(
                receipt["snapshot_sha256"], changed["provenance"]["snapshot_sha256"]
            )
            self.assertNotEqual(
                receipt["snapshot_generation"],
                changed["provenance"]["snapshot_generation"],
            )

    def test_emit_is_safe_for_legacy_windows_console_encoding(self) -> None:
        from simplicio_fast.cli import emit

        encoded = io.BytesIO()
        console = io.TextIOWrapper(encoded, encoding="cp1252")
        with contextlib.redirect_stdout(console):
            emit({"symbol": "route → local"})
        console.flush()

        output = encoded.getvalue().decode("cp1252")
        self.assertIn("\\u2192", output)
        self.assertEqual({"symbol": "route → local"}, json.loads(output))

    def test_non_git_and_stale_source_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def save():\n    return True\n", encoding="utf-8")
            snapshot = root / "snapshot.sfast"
            build_snapshot(root, snapshot)
            code, payload = self.invoke(
                "context", "save", "--root", str(root), "--snapshot", str(snapshot)
            )
            self.assertEqual(0, code)
            self.assertIsNone(payload["provenance"]["source_commit"])
            self.assertEqual(
                "not_a_git_checkout", payload["provenance"]["source_commit_reason"]
            )

            source.write_text("def save():\n    return False\n", encoding="utf-8")
            code, payload = self.invoke(
                "context", "save", "--root", str(root), "--snapshot", str(snapshot)
            )
            self.assertEqual(2, code)
            self.assertEqual("simplicio.fast.error/v1", payload["schema"])
            self.assertEqual("StaleSnapshotError", payload["error"])

    def test_navigate_cli_exposes_bounded_next_executable_hop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text(
                "def target():\n    return True\n\ndef caller():\n    return target()\n",
                encoding="utf-8",
            )
            snapshot = root / "snapshot.sfast"
            build_snapshot(root, snapshot)
            with Snapshot(snapshot) as opened:
                caller = opened.find_exact("caller")[0]
            code, payload = self.invoke(
                "navigate",
                caller.symbol_id,
                "next_executable_hop",
                "outgoing",
                "--snapshot",
                str(snapshot),
                "--fast-engine",
                "python",
                "--max-nodes",
                "1",
            )
            self.assertEqual(0, code)
            self.assertEqual("simplicio.fast-navigation/v1", payload["schema"])
            self.assertEqual(
                ["target"], [item["qualified_name"] for item in payload["items"]]
            )
            self.assertEqual(caller.symbol_id, payload["provenance"]["handle"])

    def test_corrupt_snapshot_fails_closed_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def save():\n    return True\n", encoding="utf-8")
            snapshot = root / "snapshot.sfast"
            build_snapshot(root, snapshot)
            snapshot.write_bytes(snapshot.read_bytes()[:-1])
            code, payload = self.invoke(
                "context", "save", "--root", str(root), "--snapshot", str(snapshot)
            )
            self.assertEqual(2, code)
            self.assertEqual("simplicio.fast.error/v1", payload["schema"])
            self.assertNotIn("provenance", payload)

    def test_other_json_commands_and_git_unavailable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def save():\n    return True\n", encoding="utf-8")
            snapshot = root / "snapshot.sfast"
            code, payload = self.invoke(
                "build",
                str(root),
                "-o",
                str(snapshot),
                "--mapper-mode",
                "bootstrap",
            )
            self.assertEqual(0, code)
            self.assertEqual("simplicio.fast.build/v1", payload["schema"])
            for command in (
                ("query", "save"),
                ("search", "save"),
                ("impact", "save"),
                ("stats",),
            ):
                code, payload = self.invoke(*command, "--snapshot", str(snapshot))
                self.assertEqual(0, code, command)
                self.assertTrue(payload["schema"].startswith("simplicio.fast."))
            doctor_code, doctor = self.invoke("doctor", "--snapshot", str(snapshot))
            self.assertTrue(doctor["schema"].startswith("simplicio.fast."))
            self.assertIn(doctor_code, {0, 1})

            code, capabilities = self.invoke("capabilities")
            self.assertEqual(0, code)
            self.assertEqual("ready", capabilities["parser_adapter"]["health"])
            self.assertEqual("contract", capabilities["parser_adapter"]["completeness"])
            self.assertEqual(
                64, len(capabilities["parser_adapter"]["fingerprints"]["contract_sha256"])
            )
            self.assertEqual("simplicio.fast.sdk-capabilities/v1", capabilities["sdk"]["schema"])
            matrix = {item["surface"]: item for item in capabilities["sdk"]["support_matrix"]}
            self.assertEqual("supported", matrix["python"]["status"])
            self.assertEqual("reject", capabilities["sdk"]["compatibility"]["rules"]["future_major"])
            self.assertEqual("simplicio.fast.context-source-adapters/v1", capabilities["sdk"]["source_adapters"]["schema"])
            self.assertEqual("facts_only", capabilities["sdk"]["context_security"]["checks"]["authority"])

        with patch(
            "simplicio_fast.cli.subprocess.run", side_effect=OSError("git unavailable")
        ):
            self.assertEqual((None, "git_unavailable"), source_commit(Path(".")))

    def test_build_rejects_oversized_source_with_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.py"
            source.write_text("def save():\n    return True\n", encoding="utf-8")
            snapshot = root / "snapshot.sfast"
            code, payload = self.invoke(
                "build",
                str(root),
                "-o",
                str(snapshot),
                "--max-file-bytes",
                "4",
                "--mapper-mode",
                "bootstrap",
            )
            self.assertEqual(2, code)
            self.assertEqual("simplicio.fast.error/v1", payload["schema"])
            self.assertEqual("SourceFileTooLarge", payload["error"])
            self.assertFalse(snapshot.exists())

    def test_build_reports_typed_parse_error_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "valid.py").write_text(
                "def valid():\n    return True\n", encoding="utf-8"
            )
            (root / "broken.py").write_text(
                "def broken(:\n    pass\n", encoding="utf-8"
            )
            snapshot = root / "project.sfast"

            code, payload = self.invoke(
                "build", str(root), "-o", str(snapshot), "--mapper-mode", "bootstrap"
            )

            self.assertEqual(2, code)
            self.assertEqual("simplicio.fast.error/v1", payload["schema"])
            self.assertEqual("SourceParseError", payload["error"])
            self.assertEqual("source_parse_failed", payload["reason_code"])
            self.assertEqual("broken.py", payload["path"])
            self.assertEqual(1, payload["line"])
            self.assertIn("fix the source syntax", payload["recovery"])
            self.assertFalse(snapshot.exists())

    def test_doctor_reports_stable_recovery_and_refresh_repairs_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("def recovered():\n    return True\n")
            snapshot = root / "project.sfast"
            snapshot.write_bytes(b"truncated")

            code, doctor = self.invoke("doctor", "--snapshot", str(snapshot))
            self.assertEqual(1, code)
            integrity = next(
                item
                for item in doctor["checks"]
                if item["name"] == "snapshot_integrity"
            )
            self.assertEqual(
                "snapshot_corrupt_rebuild", integrity["detail"]["recovery_code"]
            )

            code, refreshed = self.invoke(
                "refresh",
                str(root),
                "--output",
                str(snapshot),
                "--timeout",
                "30",
                "--mapper-mode",
                "bootstrap",
            )
            self.assertEqual(0, code)
            self.assertEqual("simplicio.fast.build/v1", refreshed["schema"])
            code, query = self.invoke("query", "recovered", "--snapshot", str(snapshot))
            self.assertEqual(0, code)
            self.assertEqual(1, len(query["matches"]))

    def test_refresh_timeout_returns_structured_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.py").write_text("def one():\n    return True\n")
            (root / "two.py").write_text("def two():\n    return True\n")
            snapshot = root / "project.sfast"
            self.assertEqual(
                0,
                self.invoke(
                    "refresh",
                    str(root),
                    "-o",
                    str(snapshot),
                    "--mapper-mode",
                    "bootstrap",
                )[0],
            )
            before = snapshot.read_bytes()

            code, payload = self.invoke(
                "refresh",
                str(root),
                "-o",
                str(snapshot),
                "--timeout",
                "0",
                "--mapper-mode",
                "bootstrap",
            )

            self.assertEqual(2, code)
            self.assertEqual("SnapshotBuildTimeout", payload["error"])
            self.assertEqual("snapshot_build_timeout", payload["recovery_code"])
            self.assertEqual(2, payload["progress"]["files_total"])
            self.assertEqual(0, payload["progress"]["files_processed"])
            self.assertEqual(2, payload["progress"]["files_remaining"])
            self.assertTrue(payload["progress"]["previous_snapshot_preserved"])
            self.assertEqual(before, snapshot.read_bytes())


if __name__ == "__main__":
    unittest.main()

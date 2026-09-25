import concurrent.futures
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from benchmarks.changed_path_delta_230 import (
    run as run_delta_benchmark,
    workload_shape,
)
from simplicio_fast.delta import DELTA_SCHEMA, Delta, DeltaError
from simplicio_fast.snapshot import Snapshot, build_snapshot
from simplicio_fast.workspace import MANIFEST_SCHEMA, Manifest, WorkspaceStore


def test_symbol_target_respects_explicit_file_distribution() -> None:
    assert workload_shape(1_000_000, 2) == (2, 500_000)
    assert workload_shape(1_000_000) == (1_000, 1_000)
    with pytest.raises(ValueError):
        workload_shape(1_000_000, 1)


def test_delta_direct_constructor_rejects_invalid_contract_types() -> None:
    values = {
        "schema": DELTA_SCHEMA,
        "delta_generation": "a" * 64,
        "base_generation": "b" * 64,
        "base_commit": "commit",
        "base_config_fingerprint": "config",
        "base_schema": "manifest/v1",
        "base_snapshot_sha256": "c" * 64,
        "worktree_id": "worktree",
        "changed": {},
        "created_at": "2026-01-01T00:00:00Z",
        "delta_sha256": "d" * 64,
    }
    with pytest.raises(DeltaError, match="delta_field_invalid"):
        Delta(**{**values, "base_commit": None})
    with pytest.raises(DeltaError, match="delta_shape_invalid"):
        Delta(**{**values, "changed": []})


def test_delta_constructor_detaches_nested_changed_records() -> None:
    changed = {
        "one.py": {
            "sha256": "a" * 64,
            "tombstone": False,
            "symbols": [],
        }
    }
    values = {
        "schema": DELTA_SCHEMA,
        "delta_generation": "a" * 64,
        "base_generation": "b" * 64,
        "base_commit": "commit",
        "base_config_fingerprint": "config",
        "base_schema": MANIFEST_SCHEMA,
        "base_snapshot_sha256": "c" * 64,
        "worktree_id": "worktree",
        "changed": changed,
        "created_at": "2026-01-01T00:00:00Z",
        "delta_sha256": "d" * 64,
    }
    delta = Delta(**values)
    changed["one.py"]["symbols"].append({"name": "mutated"})
    assert delta.changed["one.py"]["symbols"] == []


def _shell_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _run_external(
    arguments: list[str],
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    environment: dict[str, str] | None = None,
) -> int:
    command = _shell_command(arguments)
    if stdout_path is not None:
        command += f" > {_shell_command([str(stdout_path)])}"
    if stderr_path is not None:
        command += f" 2> {_shell_command([str(stderr_path)])}"
    previous = {key: os.environ.get(key) for key in environment} if environment else {}
    try:
        if environment is not None:
            os.environ.update(environment)
        return os.system(command)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class ChangedPathDeltaHandoffTest(unittest.TestCase):
    def _store(self, directory: str) -> tuple[Path, WorkspaceStore]:
        root = Path(directory)
        (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
        (root / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
        return root, WorkspaceStore(root)

    def test_canonical_manifest_and_unchanged_delta_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base(config={"profile": "loop"})
            self.assertEqual(64, len(base.snapshot_sha256))
            self.assertEqual(64, len(base.source_tree_sha256))
            delta = store.create_delta(base.generation_id, "issue-230", ["one.py"])
            self.assertEqual({}, delta.changed)
            report = store.handoff(
                base.generation_id, "issue-230", delta_generation=delta.delta_generation
            )
            self.assertTrue(report["parity"])
            self.assertEqual(
                ["cold_ms", "incremental_ms", "warm_ms"], sorted(report["timings_ms"])
            )
            self.assertEqual(2, report["cache_reuse"])
            self.assertGreater(report["mapped_bytes"], 0)
            self.assertGreaterEqual(report["cpu_ms"], 0)
            self.assertEqual(
                {
                    "base_validation_and_open",
                    "delta_load_or_create",
                    "snapshot_structural_validation",
                    "compose_and_validate",
                    "source_verification_and_parity",
                },
                set(report["stage_timings_ms"]),
            )

    def test_explicit_changed_paths_do_not_scan_the_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one():\n    return 10\n", encoding="utf-8"
            )
            with patch(
                "simplicio_fast.delta.source_files",
                side_effect=AssertionError("explicit delta scanned the repository"),
            ):
                delta = store.create_delta(base.generation_id, "scoped", ["one.py"])
            self.assertEqual(["one.py"], sorted(delta.changed))

    def test_scoped_handoff_does_not_rescan_for_compose_or_parity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one():\n    return 10\n", encoding="utf-8"
            )
            delta = store.create_delta(base.generation_id, "scoped", ["one.py"])
            with patch(
                "simplicio_fast.delta.source_files",
                side_effect=AssertionError("scoped handoff scanned the repository"),
            ):
                report = store.handoff(
                    base.generation_id,
                    "scoped",
                    delta_generation=delta.delta_generation,
                    changed_paths=["one.py"],
                )
            self.assertTrue(report["parity"])
            self.assertEqual("explicit_changed_paths", report["parity_result"]["scope"])
            self.assertEqual(["one.py"], report["changed_paths"])

    def test_scoped_handoff_caches_structural_snapshot_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one():\n    return 10\n", encoding="utf-8"
            )
            delta = store.create_delta(base.generation_id, "cached", ["one.py"])
            reloaded = WorkspaceStore(root, storage=store.storage)
            with patch(
                "simplicio_fast.workspace.Snapshot", wraps=Snapshot
            ) as opened:
                first = reloaded.handoff(
                    base.generation_id,
                    "cached",
                    ["one.py"],
                    delta_generation=delta.delta_generation,
                )
                second = reloaded.handoff(
                    base.generation_id,
                    "cached",
                    ["one.py"],
                    delta_generation=delta.delta_generation,
                )
            self.assertTrue(first["parity"])
            self.assertTrue(second["parity"])
            self.assertEqual(1, opened.call_count)

    def test_repeated_identical_delta_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            first = store.create_delta(base.generation_id, "same", ["one.py"])
            path = store.delta_dir / "same" / f"{first.delta_generation}.json"
            first_bytes = path.read_bytes()
            second = store.create_delta(base.generation_id, "same", ["one.py"])
            self.assertEqual(first.delta_generation, second.delta_generation)
            self.assertEqual(first_bytes, path.read_bytes())

    def test_changed_path_composes_and_matches_full_snapshot_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one():\n    return 10\n\ndef added():\n    return 3\n",
                encoding="utf-8",
            )
            full = root / "full.sfast"
            build_snapshot(root, full)
            delta = store.create_delta(base.generation_id, "issue-230", ["one.py"])
            with store.compose_delta(
                base.generation_id, "issue-230", delta.delta_generation
            ) as view:
                self.assertEqual(1, len(view.find("added")))
                self.assertEqual(1, len(view.find("two")))
            report = store.handoff(
                base.generation_id,
                "issue-230",
                delta_generation=delta.delta_generation,
                parity_snapshot=full,
            )
            self.assertTrue(report["parity"])
            self.assertEqual(["one.py"], report["changed_paths"])
            self.assertEqual(
                report["parity_snapshot_hash"],
                hashlib.sha256(full.read_bytes()).hexdigest(),
            )

    def test_tombstone_rollback_keeps_source_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "two.py").unlink()
            full = root / "after-delete.sfast"
            build_snapshot(root, full)
            delta = store.create_delta(base.generation_id, "delete", ["two.py"])
            self.assertTrue(delta.changed["two.py"]["tombstone"])
            with store.compose_delta(
                base.generation_id, "delete", delta.delta_generation
            ) as view:
                self.assertEqual([], view.find("two"))
            report = store.handoff(
                base.generation_id,
                "delete",
                delta_generation=delta.delta_generation,
                parity_snapshot=full,
            )
            self.assertTrue(report["parity"])
            delta_path = store.delta_dir / "delete" / f"{delta.delta_generation}.json"
            delta_path.unlink()
            self.assertFalse((root / "two.py").exists())
            rebuilt = root / "rollback-rebuild.sfast"
            build_snapshot(root, rebuilt)
            self.assertTrue(rebuilt.is_file())

    def test_twenty_concurrent_readers_share_one_immutable_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()

            def read_base(_: int) -> tuple[int, str]:
                with store.open(base.generation_id) as view:
                    symbols = view.find("one")
                    return len(symbols), symbols[0].base_generation

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                results = list(pool.map(read_base, range(20)))
            self.assertEqual([(1, base.generation_id)] * 20, results)

    def test_worktree_delta_records_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one_a():\n    return 10\n", encoding="utf-8"
            )
            delta_a = store.create_delta(base.generation_id, "slot-a", ["one.py"])
            with store.compose_delta(
                base.generation_id, "slot-a", delta_a.delta_generation
            ) as view:
                self.assertEqual(1, len(view.find("one_a")))
            (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
            (root / "two.py").write_text(
                "def two_b():\n    return 20\n", encoding="utf-8"
            )
            delta_b = store.create_delta(base.generation_id, "slot-b", ["two.py"])
            self.assertEqual(["one.py"], sorted(delta_a.changed))
            self.assertEqual(["two.py"], sorted(delta_b.changed))
            self.assertNotEqual(delta_a.delta_generation, delta_b.delta_generation)
            self.assertTrue((store.delta_dir / "slot-a").is_dir())
            self.assertTrue((store.delta_dir / "slot-b").is_dir())
            self.assertEqual(
                ["one.py"],
                sorted(store.delta("slot-a", delta_a.delta_generation).changed),
            )

    def test_active_lease_protects_generation_from_gc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base(config={"profile": "one"})
            other = store.build_base(config={"profile": "two"})
            lease = store.pin(base.generation_id, "reader-20", ttl_seconds=60)
            dry = store.gc()
            self.assertIn(base.generation_id, dry["protected"])
            self.assertIn(other.generation_id, dry["candidates"])
            applied = store.gc(apply=True)
            self.assertNotIn(base.generation_id, applied["removed"])
            self.assertFalse(store._manifest_path(other.generation_id).exists())
            store.release_lease(lease.lease_id)
            released = store.gc(apply=True)
            self.assertIn(base.generation_id, released["removed"])
            self.assertTrue((root / "one.py").exists())

    def test_rejects_config_and_artifact_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            with self.assertRaises(DeltaError) as config_error:
                store.create_delta(
                    base.generation_id, "issue-230", config_fingerprint="0" * 64
                )
            self.assertEqual(
                "config_fingerprint_mismatch", config_error.exception.reason_code
            )
            snapshot = store.base_dir / base.generation_id / base.snapshot
            snapshot.write_bytes(snapshot.read_bytes() + b"tamper")
            with self.assertRaises(DeltaError) as digest_error:
                store.create_delta(base.generation_id, "issue-230")
            self.assertEqual(
                "base_artifact_digest_mismatch", digest_error.exception.reason_code
            )

    def test_rejects_stale_source_and_tampered_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one():\n    return 10\n", encoding="utf-8"
            )
            delta = store.create_delta(base.generation_id, "issue-230", ["one.py"])
            (root / "one.py").write_text(
                "def one():\n    return 11\n", encoding="utf-8"
            )
            with self.assertRaises(DeltaError) as stale_error:
                store.compose_delta(
                    base.generation_id, "issue-230", delta.delta_generation
                )
            self.assertEqual("delta_source_stale", stale_error.exception.reason_code)
            path = store.delta_dir / "issue-230" / f"{delta.delta_generation}.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["base_commit"] = "wrong"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DeltaError) as digest_error:
                store.delta("issue-230", delta.delta_generation)
            self.assertEqual(
                "delta_digest_mismatch", digest_error.exception.reason_code
            )

    def test_rejects_truncated_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            delta = store.create_delta(base.generation_id, "issue-230", ["one.py"])
            path = store.delta_dir / "issue-230" / f"{delta.delta_generation}.json"
            path.write_bytes(b"{")
            with self.assertRaises(DeltaError) as caught:
                store.delta("issue-230", delta.delta_generation)
            self.assertEqual("delta_missing", caught.exception.reason_code)

    def test_rejects_missing_digest_root_and_snapshot_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            manifest_path = store.base_dir / base.generation_id / "manifest.json"
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["snapshot_sha256"] = ""
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DeltaError) as missing:
                store.create_delta(base.generation_id, "issue-230")
            self.assertEqual(
                "base_artifact_digest_missing", missing.exception.reason_code
            )

        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            manifest_path = store.base_dir / base.generation_id / "manifest.json"
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["root"] = str(root / "other")
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DeltaError) as root_error:
                store.create_delta(base.generation_id, "issue-230")
            self.assertEqual("base_root_mismatch", root_error.exception.reason_code)

        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            manifest_path = store.base_dir / base.generation_id / "manifest.json"
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            value["snapshot"] = "../escape.sfast"
            manifest_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(DeltaError) as path_error:
                store.create_delta(base.generation_id, "issue-230")
            self.assertEqual(
                "base_snapshot_path_invalid", path_error.exception.reason_code
            )

    def test_cli_delta_and_handoff_are_real_system_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one_cli():\n    return 30\n", encoding="utf-8"
            )
            parity = root / "cli-parity.sfast"
            build_snapshot(root, parity)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

            def run_cli(command: list[str]) -> dict[str, object]:
                with tempfile.TemporaryDirectory(prefix="simplicio-fast-cli-") as logs:
                    stdout_path = Path(logs) / "stdout.json"
                    stderr_path = Path(logs) / "stderr.txt"
                    result = _run_external(
                        command, stdout_path, stderr_path, environment
                    )
                    self.assertEqual(0, result, stderr_path.read_text(encoding="utf-8"))
                    return json.loads(stdout_path.read_text(encoding="utf-8"))

            delta_command = [
                sys.executable,
                "-m",
                "simplicio_fast.cli",
                "delta",
                str(root),
                "--base-generation",
                base.generation_id,
                "--worktree-id",
                "cli",
                "--changed-path",
                "one.py",
            ]
            delta_payload = run_cli(delta_command)
            generation = delta_payload["delta"]["delta_generation"]
            report = run_cli(
                [
                    sys.executable,
                    "-m",
                    "simplicio_fast.cli",
                    "handoff",
                    str(root),
                    "--base-generation",
                    base.generation_id,
                    "--worktree-id",
                    "cli",
                    "--delta-generation",
                    generation,
                    "--parity-snapshot",
                    str(parity),
                ]
            )
            self.assertEqual("simplicio.fast.handoff/v1", report["schema"])
            self.assertEqual("pass", report["status"])
            self.assertEqual(1, report["files_parsed"])
            self.assertEqual(1, report["cache_reuse"])
            self.assertGreater(report["mapped_bytes"], 0)
            self.assertGreaterEqual(report["cpu_ms"], 0)

    def test_benchmark_receipt_has_required_matrix_and_metrics(self) -> None:
        receipt = run_delta_benchmark(files=4, repetitions=10)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(10, receipt["workload"]["repetitions"])
        self.assertEqual(
            ["cold", "warm", "unchanged", "one_file"], receipt["workload"]["categories"]
        )
        for category in receipt["workload"]["categories"]:
            summary = receipt["categories"][category]["summary"]
            self.assertEqual(10, summary["repetitions"])
            self.assertTrue(summary["parity"])
            for field in (
                "wall_ms_median",
                "wall_ms_p95",
                "wall_ms_p99",
                "cpu_ms_median",
                "cpu_ms_p95",
                "cpu_ms_p99",
                "rss_kib_median",
                "page_faults_median",
                "parsed_files_median",
                "reused_files_median",
                "parsed_bytes_median",
                "reused_bytes_median",
                "mapped_bytes_median",
                ):
                self.assertIn(field, summary)
            if category in {"unchanged", "one_file"}:
                for row in receipt["categories"][category]["raw"]:
                    self.assertIsInstance(row["stage_timings_ms"], dict)
                    self.assertIn(
                        "base_validation_and_open", row["stage_timings_ms"]
                    )
                    self.assertGreaterEqual(row["stage_coverage"], 0.95)
            if category == "one_file":
                rows = receipt["categories"][category]["raw"]
                self.assertEqual(
                    ["audited_revision", "hot_path_not_materialized"],
                    [row["background_parity_reason"] for row in rows[:2]],
                )
                self.assertEqual("audited_revision", rows[-1]["background_parity_reason"])
        self.assertEqual("complete", receipt["environment"]["metrics_status"])
        self.assertIn(receipt["performance_gates"]["status"], {"pass", "fail"})
        self.assertIn(
            "one_file_faster_than_cold",
            receipt["performance_gates"]["checks"],
        )
        self.assertIn(
            "one_file_within_half_cold",
            receipt["performance_gates"]["checks"],
        )
        self.assertIn(
            "unchanged_within_two_times_warm",
            receipt["performance_gates"]["checks"],
        )
        self.assertIn(
            "unchanged_under_reference_budget",
            receipt["performance_gates"]["checks"],
        )

    def test_scoped_handoff_does_not_materialize_composed_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            (root / "one.py").write_text(
                "def one_changed():\n    return 3\n", encoding="utf-8"
            )
            delta = store.create_delta(base.generation_id, "scoped", ["one.py"])
            with patch("simplicio_fast.delta.EffectiveSnapshot.symbols") as symbols:
                report = store.handoff(
                    base.generation_id,
                    "scoped",
                    ["one.py"],
                    delta_generation=delta.delta_generation,
                )
            symbols.assert_not_called()
            self.assertIsNone(report["parity_result"]["composed_symbol_count"])
            self.assertEqual(
                "scoped_query_not_materialized",
                report["parity_result"]["composed_symbol_count_reason"],
            )

    def test_handoff_validates_base_once_and_reuses_it_for_delta_and_compose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            with patch(
                "simplicio_fast.delta._base_snapshot",
                wraps=__import__("simplicio_fast.delta", fromlist=["_base_snapshot"])._base_snapshot,
            ) as validate:
                report = store.handoff(
                    base.generation_id,
                    "reuse",
                    ["one.py"],
                )
            self.assertTrue(report["parity"])
            self.assertEqual(1, validate.call_count)

    def test_reuses_artifact_digest_after_first_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            delta = store.create_delta(base.generation_id, "cache", ["one.py"])
            store.handoff(
                base.generation_id,
                "cache",
                ["one.py"],
                delta_generation=delta.delta_generation,
            )
            with patch(
                "simplicio_fast.delta._hash_source",
                side_effect=AssertionError("validated artifact was rehashed"),
            ):
                report = store.handoff(
                    base.generation_id,
                    "cache",
                    ["one.py"],
                    delta_generation=delta.delta_generation,
                )
            self.assertTrue(report["parity"])

    def test_source_hash_cache_reuses_identity_and_invalidates_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            path = root / "one.py"
            first = store.source_hash(path)
            with patch(
                "simplicio_fast.workspace._hash_source",
                wraps=lambda value: hashlib.sha256(value.read_bytes()).hexdigest(),
            ) as hashed:
                self.assertEqual(first, store.source_hash(path))
                hashed.assert_not_called()

                path.write_text("def one():\n    return 10\n", encoding="utf-8")
                second = store.source_hash(path)

            self.assertNotEqual(first, second)
            self.assertEqual(1, hashed.call_count)

    def test_reuses_manifest_parse_until_file_identity_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _root, store = self._store(directory)
            base = store.build_base()
            manifest_path = store.base_dir / base.generation_id / "manifest.json"
            with patch(
                "simplicio_fast.workspace.Manifest.from_dict",
                wraps=Manifest.from_dict,
            ) as parse:
                first = store.manifest(base.generation_id)
                second = store.manifest(base.generation_id)
                self.assertIs(first, second)
                self.assertEqual(1, parse.call_count)

                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                data["created_at"] = "changed-at"
                manifest_path.write_text(json.dumps(data), encoding="utf-8")
                changed = store.manifest(base.generation_id)

            self.assertEqual("changed-at", changed.created_at)
            self.assertEqual(2, parse.call_count)

    def test_unchanged_scoped_handoff_skips_compose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            delta = store.create_delta(base.generation_id, "unchanged", ["one.py"])
            self.assertEqual({}, delta.changed)
            with patch("simplicio_fast.delta.compose_delta") as compose:
                report = store.handoff(
                    base.generation_id,
                    "unchanged",
                    ["one.py"],
                    delta_generation=delta.delta_generation,
                )
            compose.assert_not_called()
            self.assertTrue(report["parity"])
            self.assertEqual(
                "unchanged_delta_not_materialized",
                report["parity_result"]["composed_symbol_count_reason"],
            )

    def test_persisted_unchanged_delta_revalidates_current_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            base = store.build_base()
            delta = store.create_delta(base.generation_id, "stale", ["one.py"])
            (root / "one.py").write_text(
                "def one():\n    return 99\n", encoding="utf-8"
            )

            report = store.handoff(
                base.generation_id,
                "stale",
                ["one.py"],
                delta_generation=delta.delta_generation,
            )

            self.assertEqual("parity_mismatch", report["status"])
            self.assertFalse(report["parity"])

    def test_benchmark_rejects_fewer_than_ten_repetitions(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 10"):
            run_delta_benchmark(files=4, repetitions=9)

    def test_rejects_dirty_git_canonical_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, store = self._store(directory)
            with (
                patch(
                    "simplicio_fast.workspace._commit",
                    return_value="a" * 40,
                ),
                patch(
                    "simplicio_fast.workspace._git_status",
                    return_value=" M one.py",
                ),
            ):
                with self.assertRaisesRegex(ValueError, "canonical_base_dirty"):
                    store.build_base()

    def test_physical_git_worktrees_share_immutable_base_without_cross_contamination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="simplicio-fast-worktrees-"
        ) as directory:
            root = Path(directory)
            canonical = root / "canonical"
            worktree_a = root / "worktree-a"
            worktree_b = root / "worktree-b"
            storage = root / "shared-fast"
            canonical.mkdir()
            (canonical / "one.py").write_text(
                "def one_base():\n    return 1\n", encoding="utf-8"
            )
            (canonical / "two.py").write_text(
                "def two_base():\n    return 2\n", encoding="utf-8"
            )

            def run_git(*arguments: str, cwd: Path = canonical) -> None:
                result = _run_external(
                    ["git", "-C", str(cwd), *arguments],
                    Path(os.devnull),
                    Path(os.devnull),
                )
                if result != 0:
                    raise AssertionError(
                        f"git command failed with status {result}: {arguments}"
                    )

            run_git("init")
            run_git("config", "user.name", "simplicio-fast-test")
            run_git("config", "user.email", "simplicio-fast-test@example.invalid")
            run_git("add", "one.py", "two.py")
            run_git("commit", "-m", "canonical base")
            run_git("pack-refs", "--all", "--prune")
            try:
                run_git("worktree", "add", str(worktree_a), "HEAD")
                run_git("worktree", "add", str(worktree_b), "HEAD")
                (worktree_a / "one.py").write_text(
                    "def one_slot_a():\n    return 10\n", encoding="utf-8"
                )
                (worktree_b / "two.py").write_text(
                    "def two_slot_b():\n    return 20\n", encoding="utf-8"
                )
                canonical_store = WorkspaceStore(canonical, storage=storage)
                base = canonical_store.build_base(
                    config={"profile": "physical-worktrees"}
                )
                base_path = storage / "base" / base.generation_id / base.snapshot
                base_bytes = base_path.read_bytes()
                base_digest = hashlib.sha256(base_bytes).hexdigest()
                store_a = WorkspaceStore(worktree_a, storage=storage)
                store_b = WorkspaceStore(worktree_b, storage=storage)
                reader_stores = [store_a, store_b] * 10

                def read_base(store: WorkspaceStore) -> tuple[str, str, list[str]]:
                    with store.open(base.generation_id) as view:
                        return (
                            view.base_generation,
                            view.manifest.snapshot_sha256,
                            sorted(symbol.name for symbol in view.find("base")),
                        )

                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
                    reader_results = list(pool.map(read_base, reader_stores))
                expected_reader = (
                    base.generation_id,
                    base.snapshot_sha256,
                    ["one_base", "two_base"],
                )
                self.assertEqual([expected_reader] * 20, reader_results)

                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    future_a = pool.submit(
                        store_a.create_delta, base.generation_id, "slot-a", ["one.py"]
                    )
                    future_b = pool.submit(
                        store_b.create_delta, base.generation_id, "slot-b", ["two.py"]
                    )
                    delta_a = future_a.result(timeout=30)
                    delta_b = future_b.result(timeout=30)

                self.assertEqual(["one.py"], sorted(delta_a.changed))
                self.assertEqual(["two.py"], sorted(delta_b.changed))
                with store_a.compose_delta(
                    base.generation_id, "slot-a", delta_a.delta_generation
                ) as view_a:
                    self.assertEqual(
                        ["one_slot_a"],
                        [symbol.name for symbol in view_a.find("one_slot")],
                    )
                    self.assertEqual([], view_a.find("two_slot"))
                    self.assertEqual(
                        ["two_base"], [symbol.name for symbol in view_a.find("two")]
                    )
                with store_b.compose_delta(
                    base.generation_id, "slot-b", delta_b.delta_generation
                ) as view_b:
                    self.assertEqual(
                        ["two_slot_b"],
                        [symbol.name for symbol in view_b.find("two_slot")],
                    )
                    self.assertEqual([], view_b.find("one_slot"))
                    self.assertEqual(
                        ["one_base"], [symbol.name for symbol in view_b.find("one")]
                    )

                with self.assertRaises(DeltaError) as crossed:
                    store_a.compose_delta(
                        base.generation_id, "slot-b", delta_b.delta_generation
                    )
                self.assertEqual("delta_source_unlisted", crossed.exception.reason_code)
                self.assertEqual(
                    base.generation_id,
                    canonical_store.manifest(base.generation_id).generation_id,
                )
                self.assertEqual(base_bytes, base_path.read_bytes())
                self.assertEqual(
                    base_digest, hashlib.sha256(base_path.read_bytes()).hexdigest()
                )
            finally:
                for worktree in (worktree_a, worktree_b):
                    if worktree.exists():
                        _run_external(
                            [
                                "git",
                                "-C",
                                str(canonical),
                                "worktree",
                                "remove",
                                "--force",
                                str(worktree),
                            ],
                            Path(os.devnull),
                            Path(os.devnull),
                        )
                _run_external(
                    ["git", "-C", str(canonical), "worktree", "prune"],
                    Path(os.devnull),
                    Path(os.devnull),
                )


if __name__ == "__main__":
    unittest.main()

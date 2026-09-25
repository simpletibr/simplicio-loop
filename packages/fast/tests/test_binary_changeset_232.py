from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.binary_changeset import (
    BinaryChangeJournal,
    BinaryChangeSet,
    BinaryChangeSetError,
    ChangeOperation,
    canonical,
    decode_binary,
    inspect_binary,
    materialize,
    prepare_from_json,
    sha256,
)


class BinaryChangeSet232Test(unittest.TestCase):
    def _change_set(
        self,
        root: Path,
        operations,
        worktree="slot-232",
        lease="lease-232",
        fence="fence-1",
    ):
        paths = sorted(
            {path for item in operations for path in (item.path, item.dest) if path}
        )
        return BinaryChangeSet(
            repository=str(root.resolve()),
            base_generation="b" * 64,
            overlay_generation="o" * 64,
            attempt="attempt-232",
            worktree_id=worktree,
            lease_id=lease,
            fencing_token=fence,
            allowed_paths=tuple(paths),
            operations=tuple(operations),
            verification_commands=(),
        )

    def test_deterministic_content_addressed_round_trip_and_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b"created\n"
            operation = ChangeOperation.from_dict(
                {
                    "op": "create",
                    "path": "created.py",
                    "content_b64": __import__("base64").b64encode(content).decode(),
                    "after_sha256": sha256(content),
                }
            )
            changeset = self._change_set(root, [operation])
            first = changeset.encode()
            second = changeset.encode()
            self.assertEqual(first, second)
            self.assertEqual(changeset, decode_binary(first))
            self.assertEqual(changeset.changeset_id, decode_binary(first).changeset_id)
            self.assertEqual("valid", inspect_binary(first)["status"])
            exported = changeset.to_dict()
            self.assertEqual(changeset.changeset_id, exported["changeset_id"])
            self.assertEqual("simplicio.fast.binary-changeset/v1", exported["schema"])

    def test_all_operations_materialize_through_dev_cli_and_replay_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_bytes(b"def value():\n    return 1\n")
            before = source.read_bytes()
            replacement = b"    return 2"
            replaced = b"def value():\n    return 2\n"
            operations = [
                ChangeOperation.from_dict(
                    {
                        "op": "replace-range",
                        "path": "source.py",
                        "before_sha256": sha256(before),
                        "after_sha256": sha256(replaced),
                        "content_b64": __import__("base64")
                        .b64encode(replacement)
                        .decode(),
                        "encoding": "utf-8",
                        "line_map": {"start_line": 2, "end_line": 2},
                    }
                ),
                ChangeOperation.from_dict(
                    {
                        "op": "create",
                        "path": "new.py",
                        "content": "new = True\n",
                        "after_sha256": sha256(b"new = True\n"),
                    }
                ),
            ]
            changeset = self._change_set(root, operations)
            journal = BinaryChangeJournal(
                root / ".overlay" / "slot-232" / "journal.bin",
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            refresh_calls = []
            receipt = materialize(
                changeset,
                root,
                journal,
                refresh=lambda path, paths: (
                    refresh_calls.append(tuple(paths)) or {"status": "refreshed"}
                ),
            )
            self.assertEqual("applied", receipt["status"])
            self.assertEqual("simplicio-dev-cli", receipt["source_writer"])
            self.assertEqual([("new.py", "source.py")], refresh_calls)
            self.assertEqual(b"def value():\n    return 2\n", source.read_bytes())
            self.assertTrue((root / "new.py").exists())
            replay = materialize(
                changeset, root, journal, refresh=lambda *_: {"status": "not-needed"}
            )
            self.assertEqual("idempotent", replay["status"])
            self.assertEqual(2, len(journal.read()))

    def test_rename_and_delete_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "old.py"
            old.write_bytes(b"old\n")
            renamed = ChangeOperation.from_dict(
                {
                    "op": "rename",
                    "path": "old.py",
                    "dest": "renamed.py",
                    "before_sha256": sha256(b"old\n"),
                    "after_sha256": sha256(b"old\n"),
                }
            )
            set_for_rename = self._change_set(root, [renamed])
            journal = BinaryChangeJournal(
                root / "j.bin",
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            refresh_calls = []
            self.assertEqual(
                "applied",
                materialize(
                    set_for_rename,
                    root,
                    journal,
                    refresh=lambda _root, paths: (
                        refresh_calls.append(tuple(paths)) or {"status": "refreshed"}
                    ),
                )["status"],
            )
            self.assertEqual([("old.py", "renamed.py")], refresh_calls)
            self.assertFalse(old.exists())
            self.assertTrue((root / "renamed.py").exists())
            deleted = ChangeOperation.from_dict(
                {
                    "op": "delete",
                    "path": "renamed.py",
                    "before_sha256": sha256(b"old\n"),
                }
            )
            set_for_delete = self._change_set(root, [deleted])
            delete_journal = BinaryChangeJournal(
                root / "j2.bin",
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            self.assertEqual(
                "applied",
                materialize(
                    set_for_delete,
                    root,
                    delete_journal,
                    refresh=lambda *_: {"status": "refreshed"},
                )["status"],
            )
            self.assertFalse((root / "renamed.py").exists())

    def test_path_alias_and_symlink_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(BinaryChangeSetError, "path_outside_repository"):
                ChangeOperation.from_dict(
                    {
                        "op": "delete",
                        "path": r"nested\..\outside.py",
                        "before_sha256": "a" * 64,
                    }
                )
            target = root.parent / f"{root.name}-outside.txt"
            target.write_bytes(b"outside")
            link = root / "linked.txt"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            operation = ChangeOperation.from_dict(
                {
                    "op": "delete",
                    "path": "linked.txt",
                    "before_sha256": sha256(b"outside"),
                }
            )
            changeset = self._change_set(root, [operation])
            with self.assertRaisesRegex(BinaryChangeSetError, "path_symlink"):
                changeset.validate(root)

    def test_stale_cross_worktree_and_ambiguous_offsets_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "one.py"
            path.write_text("one\n", encoding="utf-8")
            operation = ChangeOperation.from_dict(
                {
                    "op": "delete",
                    "path": "one.py",
                    "before_sha256": sha256(b"one\n"),
                }
            )
            journal = BinaryChangeJournal(
                root / "j.bin",
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            stale = self._change_set(root, [operation])
            path.write_text("changed\n", encoding="utf-8")
            receipt = materialize(
                stale, root, journal, refresh=lambda *_: {"status": "not-needed"}
            )
            self.assertEqual("rejected", receipt["status"])
            self.assertEqual("stale_source", receipt["reason_code"])
            with self.assertRaisesRegex(BinaryChangeSetError, "cross_worktree"):
                journal.append(
                    self._change_set(root, [operation], worktree="other"), "sealed"
                )
            with self.assertRaisesRegex(BinaryChangeSetError, "ambiguous_byte_offset"):
                ChangeOperation.from_dict(
                    {
                        "op": "replace-range",
                        "path": "one.py",
                        "byte_start": 0,
                        "byte_end": 1,
                        "before_sha256": sha256(b"one\n"),
                        "after_sha256": sha256(b"x\n"),
                        "content": "x",
                        "encoding": "utf-8",
                    }
                )

    def test_journal_chain_and_partial_tail_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"new\n"
            operation = ChangeOperation.from_dict(
                {
                    "op": "create",
                    "path": "new.py",
                    "content_b64": __import__("base64").b64encode(payload).decode(),
                    "after_sha256": sha256(payload),
                }
            )
            changeset = self._change_set(root, [operation])
            path = root / "slot-232" / "journal.bin"
            journal = BinaryChangeJournal(
                path,
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            journal.append(changeset, "sealed")
            original = path.read_bytes()
            path.write_bytes(original + b"\x00\x01\x02")
            with self.assertRaisesRegex(BinaryChangeSetError, "journal_truncated_tail"):
                journal.read()
            recovery = journal.recover()
            self.assertEqual("recovered", recovery["status"])
            self.assertGreater(recovery["truncated_bytes"], 0)
            self.assertEqual(1, len(journal.read()))

    def test_corruption_truncation_and_prepare_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"golden\n"
            value = {
                "schema": "simplicio.fast.binary-changeset/v1",
                "operations": [
                    {
                        "op": "create",
                        "path": "golden.py",
                        "content": "golden\n",
                        "after_sha256": sha256(payload),
                    }
                ],
            }
            changeset = prepare_from_json(
                value,
                root=root,
                base_generation="b" * 64,
                overlay_generation="o" * 64,
                attempt="a",
                worktree_id="slot-232",
                lease_id="lease-232",
                fencing_token="fence-1",
            )
            raw = changeset.encode()
            with self.assertRaisesRegex(
                BinaryChangeSetError, "binary_checksum_mismatch"
            ):
                decode_binary(raw[:-1] + bytes([raw[-1] ^ 1]))
            with self.assertRaisesRegex(BinaryChangeSetError, "binary_length_mismatch"):
                decode_binary(raw[:-3])
            self.assertEqual(
                changeset,
                BinaryChangeSet.from_dict(json.loads(json.dumps(changeset.to_dict()))),
            )

    def test_authority_binding_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operation = ChangeOperation.from_dict(
                {
                    "op": "delete",
                    "path": "x.py",
                    "before_sha256": "a" * 64,
                }
            )
            with self.assertRaisesRegex(BinaryChangeSetError, "authority_missing"):
                BinaryChangeSet(
                    str(root),
                    "b" * 64,
                    "o" * 64,
                    "a",
                    "slot-232",
                    "",
                    "f",
                    ("x.py",),
                    (operation,),
                )

    def test_canonical_json_rejects_non_finite_numbers(self):
        with self.assertRaisesRegex(BinaryChangeSetError, "json_encoding_invalid"):
            canonical({"value": float("nan")})


if __name__ == "__main__":
    unittest.main()

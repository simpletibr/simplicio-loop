"""bench/swebench manifest (#1819): a pinned, deterministic 30+ task selection, honest about what is missing.

No network. The committed manifest is a TEMPLATE (UNVERIFIED): it pins the dataset name and revision but
holds NO instance IDs, because the ID list cannot be read here without downloading the dataset. Every
selection test below runs on a SYNTHETIC toy pool generated in tmp_path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SWE = REPO / "bench" / "swebench"
sys.path.insert(0, str(SWE))

import swe_manifest as sm

REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"


def _committed() -> dict:
    return json.loads((SWE / "manifest.json").read_text(encoding="utf-8"))


def _toy_pool(sizes: dict[str, int], revision: str = "a" * 40) -> dict:
    """SYNTHETIC pool: invented IDs for tests only. Carries one non-allowed field to prove it is dropped."""
    inst = []
    for repo, k in sizes.items():
        owner, name = repo.split("/")
        for i in range(1, k + 1):
            inst.append({"instance_id": f"{owner}__{name}-{i}", "repo": repo, "base_commit": "b" * 40,
                         "problem_statement": "SYNTHETIC text that must never reach a manifest"})
    return {"dataset": {"name": "toy/dataset", "split": "test", "revision": revision}, "instances": inst}


# --- the committed TEMPLATE -----------------------------------------------------------------------------

def test_committed_manifest_is_an_explicit_unverified_template_with_no_instance_ids():
    man = _committed()
    assert man["status"] == "TEMPLATE (UNVERIFIED)"
    assert man["instances"] == []
    assert man["selection"]["pool_sha256"] is None and man["selection"]["pool_size"] is None
    assert "not in this file" in man["status_reason"] and "no ID was invented" in man["status_reason"]


def test_committed_manifest_pins_the_dataset_name_and_the_measured_revision():
    ds = _committed()["dataset"]
    assert ds["name"] == "princeton-nlp/SWE-bench_Verified" and ds["split"] == "test"
    assert ds["revision"] == REVISION and re.fullmatch(r"[0-9a-f]{40}", ds["revision"])
    assert "metadata only" in ds["revision_source"]


def test_committed_manifest_regenerates_byte_identically_from_its_template_builder():
    assert sm.dumps(sm.build_template()) == (SWE / "manifest.json").read_text(encoding="utf-8")


def test_check_passes_on_the_committed_template_and_labels_it_unverified(capsys):
    assert sm.main(["--check"]) == 0
    assert "TEMPLATE (UNVERIFIED)" in capsys.readouterr().out


def test_check_refuses_a_template_that_smuggles_in_instance_ids(tmp_path, capsys):
    man = _committed()
    man["instances"] = [{"instance_id": "x__y-1", "repo": "x/y"}]
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    assert sm.main(["--check", "--manifest", str(p)]) == 1
    assert "TEMPLATE" in capsys.readouterr().err


def test_check_fails_when_the_pinned_revision_is_edited_without_recomputing_the_id(tmp_path, capsys):
    man = _committed()
    man["dataset"]["revision"] = "1" * 40
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    assert sm.main(["--check", "--manifest", str(p)]) == 1
    assert "manifest_id" in capsys.readouterr().err


# --- the selection rule (SYNTHETIC pools) -------------------------------------------------------------------

def test_allocation_is_largest_remainder_and_sums_to_n():
    sizes = {"a/a": 231, "b/b": 75, "c/c": 44, "d/d": 2, "e/e": 1}
    alloc = sm.allocate(sizes, 40)
    assert sum(alloc.values()) == 40
    assert alloc["a/a"] >= 18 and alloc["e/e"] == 0
    assert alloc == sm.allocate(dict(reversed(list(sizes.items()))), 40)


def test_allocation_breaks_ties_by_repo_name():
    assert sm.allocate({"z/z": 5, "a/a": 5}, 3) == {"a/a": 2, "z/z": 1}


def test_allocation_never_exceeds_a_stratum_size():
    assert sm.allocate({"a/a": 1, "b/b": 1}, 2) == {"a/a": 1, "b/b": 1}
    with pytest.raises(ValueError):
        sm.allocate({"a/a": 1}, 2)


def test_selection_is_deterministic_and_independent_of_pool_order():
    pool = _toy_pool({"o/a": 40, "o/b": 25, "o/c": 9})
    first = sm.build_manifest(pool, seed="s1", n=30)
    again = sm.build_manifest(pool, seed="s1", n=30)
    shuffled = copy.deepcopy(pool)
    random.Random(5).shuffle(shuffled["instances"])
    assert sm.dumps(first) == sm.dumps(again) == sm.dumps(sm.build_manifest(shuffled, seed="s1", n=30))


def test_selection_changes_with_the_seed():
    pool = _toy_pool({"o/a": 40, "o/b": 25, "o/c": 9})
    ids = lambda m: [r["instance_id"] for r in m["instances"]]
    assert ids(sm.build_manifest(pool, seed="s1", n=30)) != ids(sm.build_manifest(pool, seed="s2", n=30))


def test_rank_is_sha256_of_seed_pipe_id_so_others_can_reproduce_it_in_any_language():
    assert sm.rank("seed", "o__a-1") == hashlib.sha256(b"seed|o__a-1").hexdigest()


def test_selected_ids_are_the_lowest_ranks_inside_each_stratum():
    pool = _toy_pool({"o/a": 40, "o/b": 25})
    man = sm.build_manifest(pool, seed="s", n=30)
    for repo, k in man["selection"]["allocation"].items():
        ranked = sorted((r["instance_id"] for r in pool["instances"] if r["repo"] == repo),
                        key=lambda i: sm.rank("s", i))
        chosen = sorted(r["instance_id"] for r in man["instances"] if r["repo"] == repo)
        assert chosen == sorted(ranked[:k])


def test_built_manifest_is_verified_keeps_only_id_and_metadata_fields_and_pins_the_pool():
    pool = _toy_pool({"o/a": 40, "o/b": 25})
    man = sm.build_manifest(pool, seed="s", n=30)
    assert man["status"] == "VERIFIED" and len(man["instances"]) == 30
    assert all(set(r) <= {"instance_id", "repo", "base_commit", "version", "difficulty"} for r in man["instances"])
    assert "problem_statement" not in sm.dumps(man)
    assert re.fullmatch(r"[0-9a-f]{64}", man["selection"]["pool_sha256"])
    other = _toy_pool({"o/a": 40, "o/b": 26})
    assert sm.build_manifest(other, seed="s", n=30)["selection"]["pool_sha256"] != man["selection"]["pool_sha256"]


def test_manifest_refuses_fewer_than_30_tasks():
    with pytest.raises(ValueError, match="30"):
        sm.build_manifest(_toy_pool({"o/a": 50}), seed="s", n=29)


def test_pool_revision_must_be_a_40_hex_commit():
    with pytest.raises(ValueError, match="revision"):
        sm.build_manifest(_toy_pool({"o/a": 40}, revision="main"), seed="s", n=30)


def test_stratification_is_proportional_within_one_task_per_repo():
    pool = _toy_pool({"a/a": 231, "b/b": 75, "c/c": 44, "d/d": 2, "e/e": 1})
    man = sm.build_manifest(pool, seed="s", n=40)
    sizes = {"a/a": 231, "b/b": 75, "c/c": 44, "d/d": 2, "e/e": 1}
    got: dict[str, int] = {}
    for r in man["instances"]:
        got[r["repo"]] = got.get(r["repo"], 0) + 1
    for repo, size in sizes.items():
        assert abs(got.get(repo, 0) - 40 * size / sum(sizes.values())) < 1.0


def test_manifest_id_is_the_digest_of_dataset_revision_and_ids_and_ignores_id_order():
    ds = {"name": "n", "revision": "r"}
    base = sm.compute_manifest_id(ds, ["a", "b"])
    assert sm.compute_manifest_id({"name": "n", "revision": "r2"}, ["a", "b"]) != base
    assert sm.compute_manifest_id(ds, ["a", "c"]) != base
    assert sm.compute_manifest_id(ds, ["b", "a"]) == base


# --- the ID-list build command ------------------------------------------------------------------------------

def test_build_cli_writes_the_same_bytes_twice_and_refuses_an_expected_revision_mismatch(tmp_path, capsys):
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(_toy_pool({"o/a": 40, "o/b": 25})), encoding="utf-8")
    out = tmp_path / "m.json"
    argv = ["build", "--ids-file", str(ids), "--out", str(out), "--seed", "s", "--n", "30"]
    assert sm.main(argv) == 0
    first = out.read_bytes()
    assert sm.main(argv) == 0 and out.read_bytes() == first
    assert sm.main(argv + ["--expect-revision", REVISION]) == 2
    assert "revision" in capsys.readouterr().err


def test_build_cli_refuses_fewer_than_30(tmp_path, capsys):
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(_toy_pool({"o/a": 40})), encoding="utf-8")
    assert sm.main(["build", "--ids-file", str(ids), "--out", str(tmp_path / "m.json"), "--n", "29"]) == 2
    assert "30" in capsys.readouterr().err
    assert not (tmp_path / "m.json").exists()

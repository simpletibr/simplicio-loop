"""#1824 -- the simplicio-27b val split must be disjoint from train (and from the benchmark).

Before: all 15 val instructions also sat in the train file (and only 13 distinct instructions
existed across 95 rows), so any validation loss measured memorisation. The split is now built by
`training/simplicio-27b/generate_dataset.py`: candidates are de-duplicated by normalised
instruction text (lowercase, collapsed whitespace, stripped), then the unique instructions are
partitioned into train and val by a seeded, hash-ordered split. `data/SPLIT.json` records the seed
and the sha256 of each file; regenerating with that seed must reproduce the files byte for byte.
"""
import hashlib
import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_DIR = os.path.join(REPO, "training", "simplicio-27b")
DATA_DIR = os.path.join(TRAIN_DIR, "data")
MANIFEST = os.path.join(DATA_DIR, "SPLIT.json")
TRAIN_FILE = "simplicio_loop_50pts_train.jsonl"
VAL_FILE = "simplicio_loop_50pts_val.jsonl"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load_module("_gen_dataset_1824", os.path.join(TRAIN_DIR, "generate_dataset.py"))
overlap = _load_module(
    "_benchmark_overlap_1824", os.path.join(REPO, "tests", "test_training_benchmark_overlap.py")
)


def _norm(text):
    return " ".join(text.lower().split())


def _read_rows(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _manifest():
    with open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------------------
# the committed data
# --------------------------------------------------------------------------------------
def test_val_instructions_are_disjoint_from_train():
    train = {_norm(r["instruction"]) for r in _read_rows(os.path.join(DATA_DIR, TRAIN_FILE))}
    val = {_norm(r["instruction"]) for r in _read_rows(os.path.join(DATA_DIR, VAL_FILE))}
    assert val, "val split is empty"
    assert train, "train split is empty"
    assert train & val == set(), "val instructions also in train: %r" % sorted(train & val)


@pytest.mark.parametrize("name", [TRAIN_FILE, VAL_FILE])
def test_no_duplicate_instructions_inside_a_split(name):
    norms = [_norm(r["instruction"]) for r in _read_rows(os.path.join(DATA_DIR, name))]
    assert len(norms) == len(set(norms)), "%s repeats an instruction" % name


@pytest.mark.parametrize("name", [TRAIN_FILE, VAL_FILE])
def test_each_split_is_disjoint_from_the_benchmark_cases(name):
    cases = overlap.all_benchmark_cases()
    assert len(cases) >= 4, "benchmark cases not discovered"
    blobs = [json.dumps(r, ensure_ascii=False) for r in _read_rows(os.path.join(DATA_DIR, name))]
    assert overlap.find_overlaps(cases, blobs) == []
    # exact-instruction check on top of the shared detector
    instructions = {_norm(r["instruction"]) for r in _read_rows(os.path.join(DATA_DIR, name))}
    for case in cases:
        for key in ("task", "instructions", "problem", "problem_statement"):
            v = case.get(key)
            if isinstance(v, str):
                assert _norm(v) not in instructions, "case %s task == a %s instruction" % (case.get("id"), name)


# --------------------------------------------------------------------------------------
# the manifest
# --------------------------------------------------------------------------------------
def test_manifest_records_seed_and_normalisation():
    m = _manifest()
    assert isinstance(m["seed"], int) and not isinstance(m["seed"], bool)
    assert m["seed"] == gen.SPLIT_SEED
    assert m["normalization"] == "lowercase, collapse whitespace, strip"
    assert set(m["files"]) == {TRAIN_FILE, VAL_FILE}


@pytest.mark.parametrize("name", [TRAIN_FILE, VAL_FILE])
def test_manifest_digest_and_row_count_match_the_file(name):
    entry = _manifest()["files"][name]
    path = os.path.join(DATA_DIR, name)
    assert entry["sha256"] == _sha256(path), "%s changed without regenerating SPLIT.json" % name
    assert entry["rows"] == len(_read_rows(path))


def test_manifest_counts_are_consistent():
    m = _manifest()
    rows = _read_rows(os.path.join(DATA_DIR, TRAIN_FILE)) + _read_rows(os.path.join(DATA_DIR, VAL_FILE))
    assert m["unique_instructions"] == len(rows)
    assert m["candidates"] - m["duplicates_removed"] == m["unique_instructions"]
    assert m["duplicates_removed"] > 0


def test_regenerating_with_the_recorded_seed_reproduces_the_files_byte_for_byte(tmp_path):
    m = _manifest()
    gen.main(["--output-dir", str(tmp_path), "--seed", str(m["seed"])])
    for name in (TRAIN_FILE, VAL_FILE):
        assert _sha256(str(tmp_path / name)) == m["files"][name]["sha256"], name
    with open(str(tmp_path / "SPLIT.json"), "rb") as a, open(MANIFEST, "rb") as b:
        assert a.read() == b.read(), "SPLIT.json is not reproducible"


# --------------------------------------------------------------------------------------
# the building blocks
# --------------------------------------------------------------------------------------
def test_normalize_instruction_lowercases_collapses_and_strips():
    assert gen.normalize_instruction("  Fix\tTHE\n  bug  ") == "fix the bug"
    assert gen.normalize_instruction("a b") == gen.normalize_instruction("A   B ")


def test_dedup_keeps_first_occurrence_and_counts_removed():
    recs = [
        {"instruction": "Fix  the bug", "n": 1},
        {"instruction": "other", "n": 2},
        {"instruction": " fix THE bug ", "n": 3},
    ]
    unique, removed = gen.dedup_by_instruction(recs)
    assert [r["n"] for r in unique] == [1, 2]
    assert removed == 1


def _pool(n):
    return [{"instruction": "task number %d" % i} for i in range(n)]


def test_split_is_disjoint_exhaustive_and_deterministic():
    pool = _pool(20)
    train, val = gen.split_disjoint(pool, seed=7, val_fraction=0.2)
    t = {_norm(r["instruction"]) for r in train}
    v = {_norm(r["instruction"]) for r in val}
    assert t & v == set()
    assert len(t) + len(v) == 20
    assert len(v) == 4
    assert (train, val) == gen.split_disjoint(pool, seed=7, val_fraction=0.2)


def test_split_depends_on_the_seed_but_not_on_input_order():
    pool = _pool(40)
    _, val_a = gen.split_disjoint(pool, seed=1, val_fraction=0.25)
    _, val_b = gen.split_disjoint(pool, seed=2, val_fraction=0.25)
    _, val_rev = gen.split_disjoint(list(reversed(pool)), seed=1, val_fraction=0.25)
    assert {r["instruction"] for r in val_a} != {r["instruction"] for r in val_b}
    assert {r["instruction"] for r in val_a} == {r["instruction"] for r in val_rev}


def test_split_always_leaves_both_sides_non_empty():
    train, val = gen.split_disjoint(_pool(2), seed=3, val_fraction=0.01)
    assert len(train) == 1 and len(val) == 1
    with pytest.raises(ValueError):
        gen.split_disjoint(_pool(1), seed=3, val_fraction=0.2)


def test_build_split_is_a_pure_function_of_the_seed():
    a = gen.build_split(seed=gen.SPLIT_SEED)
    b = gen.build_split(seed=gen.SPLIT_SEED)
    assert a == b
    assert a["stats"]["duplicates_removed"] == a["stats"]["candidates"] - a["stats"]["unique_instructions"]


def test_split_refuses_a_pool_that_was_not_deduplicated():
    with pytest.raises(ValueError):
        gen.split_disjoint([{"instruction": "Same"}, {"instruction": " same "}], seed=1)


def test_candidate_pool_covers_every_scenario_and_domain():
    stats = gen.build_split(seed=gen.SPLIT_SEED)["stats"]
    assert stats["unique_instructions"] == len(gen.SCENARIOS) + len(gen.VARIATION_DOMAINS)
    assert stats["candidates"] == gen.CANDIDATE_COUNT


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

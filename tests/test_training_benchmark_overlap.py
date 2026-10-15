"""#1813 -- no benchmark case may overlap the train/val data of the model it evaluates.

`training/simplicio-27b` ships a train split, a val split and a small benchmark suite
(`benchmark_simplicio_27b.py`, the Colab notebooks, `benchmarks/*`). A benchmark case that also
appears in train/val measures memorisation, not skill. The `tax_id` case was in all three.

Overlap is detected on two signals, both deterministic and offline:
  1. a distinctive identifier of the case (snake_case / CamelCase name taken from its code, task
     or file) appears as a whole word in any train/val record;
  2. the case's task sentence appears verbatim in any train/val record.
"""
import ast
import json
import os
import re
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN_DIR = os.path.join(REPO, "training", "simplicio-27b")
DATA_DIR = os.path.join(TRAIN_DIR, "data")

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _is_distinctive(ident):
    """snake_case or CamelCase names of 6+ chars; plain English words never qualify."""
    if len(ident) < 6:
        return False
    if "_" in ident.strip("_"):
        return True
    return ident[0].isupper() and any(c.islower() for c in ident) and any(c.isupper() for c in ident[1:])


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def case_identifiers(case):
    idents = set()
    for s in _strings(case):
        idents.update(i for i in _IDENT_RE.findall(s) if _is_distinctive(i))
    return idents


def case_task_sentences(case):
    out = []
    for key in ("task", "instructions", "problem", "problem_statement"):
        v = case.get(key)
        if isinstance(v, str) and len(v.strip()) >= 20:
            out.append(re.sub(r"\s+", " ", v).strip().lower())
    return out


def load_train_val_text():
    """One normalised text blob per train/val record."""
    blobs = []
    for name in sorted(os.listdir(DATA_DIR)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    blobs.append(json.dumps(json.loads(line), ensure_ascii=False))
    return blobs


def find_overlaps(cases, blobs):
    """Return [(case_id, reason)] for every case that overlaps a train/val record."""
    hits = []
    word_cache = [set(_IDENT_RE.findall(b)) for b in blobs]
    norm_blobs = [re.sub(r"\s+", " ", b).lower() for b in blobs]
    for case in cases:
        cid = case.get("id") or case.get("instance_id") or "?"
        shared = sorted(i for i in case_identifiers(case) if any(i in words for words in word_cache))
        if shared:
            hits.append((cid, "identifiers in train/val: %s" % ", ".join(shared)))
        for sentence in case_task_sentences(case):
            if any(sentence in nb for nb in norm_blobs):
                hits.append((cid, "task sentence appears verbatim in train/val"))
    return hits


def _cases_from_literals(tree):
    """Top-level `NAME = [ {...}, ... ]` assignments whose items are dicts with an id key."""
    cases = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            cases.extend(v for v in value if "id" in v or "instance_id" in v)
    return cases


def _python_cases(path):
    with open(path, encoding="utf-8") as fh:
        return _cases_from_literals(ast.parse(fh.read()))


def _notebook_cases(path):
    with open(path, encoding="utf-8") as fh:
        nb = json.load(fh)
    cases = []
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        try:
            tree = ast.parse("".join(cell.get("source", [])))
        except SyntaxError:  # cells with `!pip` magics
            continue
        cases.extend(_cases_from_literals(tree))
    return cases


def all_benchmark_cases():
    cases = []
    cases.extend(_python_cases(os.path.join(TRAIN_DIR, "benchmark_simplicio_27b.py")))
    bench_dir = os.path.join(TRAIN_DIR, "benchmarks")
    for name in sorted(os.listdir(bench_dir)):
        path = os.path.join(bench_dir, name)
        if name.endswith(".py"):
            cases.extend(_python_cases(path))
        elif name.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            cases.extend(c for c in data if isinstance(c, dict) and ("id" in c or "instance_id" in c))
    for name in sorted(os.listdir(TRAIN_DIR)):
        if name.endswith(".ipynb"):
            cases.extend(_notebook_cases(os.path.join(TRAIN_DIR, name)))
    return cases


# --------------------------------------------------------------------------------------
# the detector itself must not be vacuous
# --------------------------------------------------------------------------------------
def test_detector_flags_identifier_overlap():
    case = {"id": "c1", "original_code": "def sanitize_tax_id(v): return v", "task": "fix it"}
    blobs = [json.dumps({"instruction": "Corrija sanitize_tax_id no schema"})]
    assert find_overlaps([case], blobs), "an identifier shared with a train record must be flagged"


def test_detector_flags_verbatim_task_sentence():
    case = {"id": "c2", "task": "Handle empty input returning zero instead of raising."}
    blobs = [json.dumps({"instruction": "x. handle empty input returning zero instead of raising. y"})]
    assert find_overlaps([case], blobs)


def test_detector_ignores_plain_words_and_clean_cases():
    case = {"id": "c3", "original_code": "def compute(a, b):\n    return a + b", "task": "Add numbers safely."}
    blobs = [json.dumps({"instruction": "Fix compute and add numbers in this repository"})]
    assert find_overlaps([case], blobs) == []


# --------------------------------------------------------------------------------------
# the real repo
# --------------------------------------------------------------------------------------
def test_benchmark_cases_are_discovered():
    cases = all_benchmark_cases()
    ids = {c.get("id") or c.get("instance_id") for c in cases}
    assert "py_dict_key_error" in ids, "script TEST_CASES not discovered: %s" % sorted(ids)
    assert len(cases) >= 4


def test_train_and_val_data_present():
    blobs = load_train_val_text()
    assert len(blobs) >= 50


def test_tax_id_case_is_gone_from_every_benchmark():
    for case in all_benchmark_cases():
        cid = case.get("id") or case.get("instance_id")
        assert cid != "py_pydantic_validator", "tax_id case still present"
        blob = json.dumps(case, ensure_ascii=False)
        assert "tax_id" not in blob, "case %s still mentions tax_id" % cid


def test_zero_overlap_between_benchmark_cases_and_train_val():
    overlaps = find_overlaps(all_benchmark_cases(), load_train_val_text())
    assert overlaps == [], "benchmark cases overlap train/val: %r" % (overlaps,)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

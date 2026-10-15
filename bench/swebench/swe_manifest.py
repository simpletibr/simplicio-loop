"""Pinned SWE-bench Verified task manifest (#1819).

Two kinds of file, never mixed:

* ``manifest.json`` (committed): either a TEMPLATE (UNVERIFIED) that pins the dataset name and revision and
  holds NO instance IDs, or a VERIFIED manifest built from a full ID list with ``build``.
* the ID list (``--ids-file``): the dataset's ``instance_id`` + ``repo`` (+ ``base_commit``) rows, produced
  outside this repo by someone who can read the dataset at the pinned revision. It is never committed here.

The selection is a pure function of (ID list, seed, n); see ``RULE`` below, which is written into every
manifest so the published choice can be re-derived in any language. Standard library only.

Commands::

    python3 bench/swebench/swe_manifest.py --check [--manifest PATH]
    python3 bench/swebench/swe_manifest.py template --out bench/swebench/manifest.json
    python3 bench/swebench/swe_manifest.py build --ids-file IDS.json --out bench/swebench/manifest.json \
        --expect-revision <40-hex> [--seed simplicio-1819] [--n 30]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import swe_common as common

DEFAULT_MANIFEST = os.path.join(HERE, "manifest.json")

SCHEMA = "simplicio-swebench-manifest/1"
STATUS_TEMPLATE = "TEMPLATE (UNVERIFIED)"
STATUS_VERIFIED = "VERIFIED"
DATASET_NAME = "princeton-nlp/SWE-bench_Verified"
DATASET_SPLIT = "test"
# Read 2026-10-14 from the Hugging Face dataset metadata endpoint (its ``sha`` field). Only metadata was read;
# the parquet file was NOT downloaded, so the ID list is still unverified.
DATASET_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
REVISION_SOURCE = ("huggingface.co/api/datasets/princeton-nlp/SWE-bench_Verified, field sha, read 2026-10-14; "
                   "metadata only, the dataset file was not downloaded")
DEFAULT_SEED = "simplicio-1819"
DEFAULT_N = 30
MIN_TASKS = common.MIN_TASKS
ALGORITHM = "stratified-by-repo; largest-remainder allocation; lowest sha256 rank inside each stratum"
ROW_KEYS = ("instance_id", "repo")
ALLOWED_ROW_KEYS = ("instance_id", "repo", "base_commit", "version", "difficulty")
RULE = (
    "1. Pool = every row of the dataset split, reduced to instance_id and repo (plus base_commit, version and "
    "difficulty when present). Row order in the pool does not matter. "
    "2. Stratum = repo; size_r = number of pool rows with that repo; total = sum of size_r. "
    "3. Allocation with exact integers: floor_r = (n * size_r) // total; the n - sum(floor_r) leftover seats go, "
    "one each, to the repos with the largest remainder (n * size_r) % total, ties broken by repo name ascending. "
    "4. rank(seed, instance_id) = sha256(utf8(seed + '|' + instance_id)) as lowercase hex. "
    "5. Inside each stratum keep the alloc_r instance_ids with the lowest (rank, instance_id). "
    "6. The manifest lists the kept rows sorted by instance_id; manifest_id = sha256 of canonical JSON "
    "{dataset: {name, revision}, ids: sorted instance_ids}."
)
TEMPLATE_REASON = (
    "The instance-ID list is not in this file. It could not be read without downloading the dataset, and no "
    "ID was invented. Build it with: swe_manifest.py build --ids-file IDS.json --expect-revision "
    f"{DATASET_REVISION}"
)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-\d+$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def canonical(obj) -> str:
    return common.canonical_json(obj)


def dumps(obj) -> str:
    """The on-disk form: stable key order, two-space indent, trailing newline."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def rank(seed: str, instance_id: str) -> str:
    return hashlib.sha256(f"{seed}|{instance_id}".encode()).hexdigest()


def compute_manifest_id(dataset: dict, instance_ids) -> str:
    payload = {"dataset": {"name": dataset["name"], "revision": dataset["revision"]},
               "ids": sorted(instance_ids)}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def allocate(sizes: dict, n: int) -> dict:
    """Largest-remainder allocation of ``n`` seats over strata of the given sizes (exact integers)."""
    total = sum(sizes.values())
    if n > total:
        raise ValueError(f"cannot draw {n} tasks from a pool of {total}")
    floors = {repo: (n * size) // total for repo, size in sizes.items()}
    leftover = n - sum(floors.values())
    order = sorted(sizes, key=lambda repo: (-((n * sizes[repo]) % total), repo))
    for repo in order[:leftover]:
        floors[repo] += 1
    return {repo: floors[repo] for repo in sorted(floors)}


def _row(raw: dict) -> dict:
    return {k: raw[k] for k in ALLOWED_ROW_KEYS if k in raw}


def validate_pool(pool: dict) -> None:
    ds = pool.get("dataset") or {}
    if not isinstance(ds.get("name"), str) or not ds.get("name"):
        raise ValueError("pool dataset.name is missing")
    if not isinstance(ds.get("revision"), str) or not _SHA40.match(ds["revision"]):
        raise ValueError(f"pool dataset.revision must be a 40-hex commit, got {ds.get('revision')!r}")
    rows = pool.get("instances") or []
    if not rows:
        raise ValueError("pool has no instances")
    seen = set()
    for r in rows:
        iid = r.get("instance_id")
        if not isinstance(iid, str) or not _ID.match(iid):
            raise ValueError(f"malformed instance_id {iid!r}")
        if iid in seen:
            raise ValueError(f"duplicate instance_id {iid}")
        seen.add(iid)
        if not isinstance(r.get("repo"), str) or not _REPO.match(r["repo"]):
            raise ValueError(f"malformed repo for {iid}: {r.get('repo')!r}")


def _dataset_block(name: str, split: str, revision: str) -> dict:
    return {"name": name, "split": split, "revision": revision}


def build_template() -> dict:
    """The committed TEMPLATE: pins dataset and revision, holds no instance IDs."""
    dataset = _dataset_block(DATASET_NAME, DATASET_SPLIT, DATASET_REVISION)
    dataset["revision_source"] = REVISION_SOURCE
    return {
        "schema": SCHEMA,
        "status": STATUS_TEMPLATE,
        "status_reason": TEMPLATE_REASON,
        "dataset": dataset,
        "selection": {"algorithm": ALGORITHM, "rule": RULE, "seed": DEFAULT_SEED, "n": DEFAULT_N,
                      "pool_size": None, "pool_sha256": None, "allocation": None},
        "instances": [],
        "manifest_id": compute_manifest_id(dataset, []),
    }


def build_manifest(pool: dict, *, seed: str, n: int) -> dict:
    """A VERIFIED manifest: a pure function of (pool, seed, n)."""
    if n < MIN_TASKS:
        raise ValueError(f"a manifest needs at least {MIN_TASKS} tasks (asked for n={n})")
    validate_pool(pool)
    src = pool["dataset"]
    dataset = _dataset_block(src["name"], src.get("split", DATASET_SPLIT), src["revision"])
    rows = [_row(r) for r in pool["instances"]]
    sizes: dict[str, int] = {}
    for r in rows:
        sizes[r["repo"]] = sizes.get(r["repo"], 0) + 1
    alloc = allocate(sizes, n)
    chosen = []
    for repo, k in alloc.items():
        ranked = sorted((r for r in rows if r["repo"] == repo),
                        key=lambda r: (rank(seed, r["instance_id"]), r["instance_id"]))
        chosen.extend(ranked[:k])
    chosen.sort(key=lambda r: r["instance_id"])
    pool_digest = hashlib.sha256(canonical(sorted(rows, key=lambda r: r["instance_id"])).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "status": STATUS_VERIFIED,
        "dataset": dataset,
        "selection": {"algorithm": ALGORITHM, "rule": RULE, "seed": seed, "n": n, "pool_size": len(rows),
                      "pool_sha256": pool_digest, "allocation": alloc},
        "instances": chosen,
        "manifest_id": compute_manifest_id(dataset, [r["instance_id"] for r in chosen]),
    }


def check_manifest(man: dict) -> list[str]:
    """Problems with a manifest file ([] = internally consistent)."""
    problems: list[str] = []
    if man.get("schema") != SCHEMA:
        problems.append(f"schema is {man.get('schema')!r}, expected {SCHEMA!r}")
    status = man.get("status")
    if status not in (STATUS_TEMPLATE, STATUS_VERIFIED):
        problems.append(f"status {status!r} is neither TEMPLATE nor VERIFIED")
    ds = man.get("dataset") or {}
    if not isinstance(ds.get("name"), str) or not ds.get("name"):
        problems.append("dataset.name must be a non-empty string")
    if not isinstance(ds.get("revision"), str) or not _SHA40.match(ds["revision"]):
        problems.append("dataset.revision must be a 40-hex commit")
    sel = man.get("selection") or {}
    n = sel.get("n")
    if not isinstance(n, int) or n < MIN_TASKS:
        problems.append(f"selection.n must be an integer >= {MIN_TASKS}, got {n!r}")
    if sel.get("algorithm") != ALGORITHM or not isinstance(sel.get("rule"), str):
        problems.append("selection.algorithm or selection.rule is not the documented one")
    instances = man.get("instances")
    if not isinstance(instances, list):
        return problems + ["instances must be a list"]
    ids = []
    for r in instances:
        extra = set(r) - set(ALLOWED_ROW_KEYS)
        if extra:
            problems.append(f"row {r.get('instance_id')!r} has non-allowed fields {sorted(extra)}")
        if not all(k in r for k in ROW_KEYS) or not _ID.match(str(r.get("instance_id"))):
            problems.append(f"row {r!r} lacks a well-formed instance_id or repo")
        ids.append(r.get("instance_id"))
    if len(set(ids)) != len(ids):
        problems.append("instances hold duplicate instance_ids")
    if status == STATUS_TEMPLATE:
        if instances:
            problems.append("a TEMPLATE manifest must hold no instance IDs")
        if sel.get("pool_sha256") is not None or sel.get("allocation") is not None:
            problems.append("a TEMPLATE manifest must not claim a pool or an allocation")
    elif status == STATUS_VERIFIED:
        if not isinstance(n, int) or len(instances) != n or len(instances) < MIN_TASKS:
            problems.append(f"a VERIFIED manifest must hold exactly selection.n={n} instances, >= {MIN_TASKS}; "
                            f"it holds {len(instances)}")
        alloc = sel.get("allocation") or {}
        if sum(alloc.values()) != len(instances):
            problems.append("selection.allocation does not sum to the instance count")
        if not isinstance(sel.get("pool_sha256"), str) or not _SHA64.match(sel["pool_sha256"]):
            problems.append("selection.pool_sha256 must be a 64-hex digest")
    if man.get("manifest_id") != compute_manifest_id(ds, ids):
        problems.append("manifest_id does not match dataset and instance IDs (edited or stale)")
    return problems


class ManifestError(ValueError):
    pass


def require_runnable(man: dict) -> None:
    """Raises ManifestError (with the BLOCKED reason) unless the manifest is VERIFIED and consistent."""
    if man.get("status") == STATUS_TEMPLATE:
        raise ManifestError(
            f"BLOCKED: manifest is {STATUS_TEMPLATE} with no instance IDs. {TEMPLATE_REASON}")
    problems = check_manifest(man)
    if problems:
        raise ManifestError("manifest is not runnable: " + "; ".join(problems))


def load_manifest(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_atomic(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _check_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Check the committed manifest (no network).")
    ap.add_argument("--check", action="store_true", help="validate the manifest (default action)")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    args = ap.parse_args(argv)
    try:
        man = load_manifest(args.manifest)
    except (OSError, ValueError) as e:
        print(f"error: cannot read {args.manifest}: {e}", file=sys.stderr)
        return 1
    problems = check_manifest(man)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 1
    print(f"OK {man['status']}: {len(man['instances'])} instances; dataset {man['dataset']['name']} "
          f"@ {man['dataset']['revision']}; manifest_id {man['manifest_id']}")
    return 0


def _template_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Write the TEMPLATE manifest.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    _write_atomic(args.out, dumps(build_template()))
    print(f"wrote {args.out} ({STATUS_TEMPLATE})")
    return 0


def _build_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build a VERIFIED manifest from an ID list (no network).")
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", default=DEFAULT_SEED)
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--expect-revision", default=None, help="refuse an ID list pinned to another revision")
    args = ap.parse_args(argv)
    try:
        with open(args.ids_file, encoding="utf-8") as f:
            pool = json.load(f)
        if args.expect_revision and (pool.get("dataset") or {}).get("revision") != args.expect_revision:
            print(f"error: ID list revision {(pool.get('dataset') or {}).get('revision')!r} differs from "
                  f"--expect-revision {args.expect_revision}", file=sys.stderr)
            return 2
        man = build_manifest(pool, seed=args.seed, n=args.n)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    _write_atomic(args.out, dumps(man))
    print(f"wrote {args.out} (VERIFIED, {len(man['instances'])} instances, manifest_id {man['manifest_id']})")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "build":
        return _build_main(argv[1:])
    if argv and argv[0] == "template":
        return _template_main(argv[1:])
    return _check_main(argv)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Regenerate / verify contracts/mapper-artifacts/v1/ fixtures (issue #157).

The mapper-artifacts contract is only trustworthy if it is checked against
*real* mapper output, not hand-written JSON that merely looks plausible.
This script is that check: it runs the actual `simplicio-mapper` CLI against
the three tiny source repos committed under
`contracts/mapper-artifacts/v1/fixtures/*/source/`, then either:

  update  - normalizes the fresh output (absolute paths -> a stable
            placeholder, `generated_at` -> a fixed sentinel, so fixtures
            stay small diffs instead of churning every run) and writes it
            into `contracts/mapper-artifacts/v1/fixtures/*/artifacts/`.
            Run this after a deliberate mapper change that legitimately
            changes artifact shape, alongside a bump of the schema files
            under `contracts/mapper-artifacts/v1/schemas/`.

  check   - regenerates fresh (unnormalized) output in a temp directory and
            validates it against the versioned schemas
            (simplicio_mapper.contract). Fails if the *current* mapper no
            longer produces output matching the committed contract — i.e.
            an incompatible artifact shipped without an explicit contract
            bump. This is the CI gate (wired into python-ci.yml).

Usage:
  python3 scripts/regen_contract_fixtures.py update
  python3 scripts/regen_contract_fixtures.py check
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_ROOT = os.path.join(ROOT, "contracts", "mapper-artifacts", "v1")
FIXTURES_ROOT = os.path.join(CONTRACT_ROOT, "fixtures")

sys.path.insert(0, ROOT)

from simplicio_mapper.contract import ContractError, validate_payload  # noqa: E402

FIXTURE_NAMES = ["python-minimal", "node-minimal", "mixed-workspace"]
ARTIFACT_FILENAMES = [
    "project-map.json",
    "precedent-index.json",
    "architecture-inventory.json",
    "symbol-index.json",
    "call-graph.json",
]
# Only one fixture also carries the `index --json` payload (issue #157 AC:
# "the `simplicio-mapper index . --json` payload is covered by a fixture").
INDEX_RESULT_FIXTURE = "python-minimal"
INDEX_RESULT_FILENAME = "mapper-index-result.json"

NORMALIZED_ROOT_PLACEHOLDER = "<fixture-root>"
NORMALIZED_TIMESTAMP = "1970-01-01T00:00:00.000Z"


def _source_dir(name: str) -> str:
    return os.path.join(FIXTURES_ROOT, name, "source")


def _artifacts_dir(name: str) -> str:
    return os.path.join(FIXTURES_ROOT, name, "artifacts")


def _run_map(source_dir: str, out_dir: str) -> None:
    subprocess.run(
        [
            sys.executable, "-m", "simplicio_mapper.cli", "map",
            "--root", source_dir, "--out", out_dir, "--silent",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def _run_index_json(source_dir: str, out_dir: str) -> dict:
    result = subprocess.run(
        [
            sys.executable, "-m", "simplicio_mapper.cli", "index",
            source_dir, "--out", out_dir, "--json",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _normalize(value, source_dir_abs: str, out_dir_abs: str | None = None):
    """Replace the fixture's absolute source (and, when given, output)
    directory paths with stable placeholders and pin any `generated_at`
    field, so committed fixtures do not churn on every regen run for
    reasons unrelated to real shape drift (temp dir names, timestamps)."""
    if isinstance(value, str):
        text = value
        if out_dir_abs and out_dir_abs in text:
            text = text.replace(out_dir_abs, NORMALIZED_ROOT_PLACEHOLDER + "/.simplicio")
        if source_dir_abs in text:
            text = text.replace(source_dir_abs, NORMALIZED_ROOT_PLACEHOLDER)
        return text
    if isinstance(value, list):
        return [_normalize(item, source_dir_abs, out_dir_abs) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, sub_value in value.items():
            if key == "generated_at":
                out[key] = NORMALIZED_TIMESTAMP
            else:
                out[key] = _normalize(sub_value, source_dir_abs, out_dir_abs)
        return out
    return value


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def cmd_update() -> int:
    for name in FIXTURE_NAMES:
        source_dir = _source_dir(name)
        if not os.path.isdir(source_dir):
            print(f"::error::missing fixture source dir: {source_dir}", file=sys.stderr)
            return 1
        source_dir_abs = os.path.abspath(source_dir)
        with tempfile.TemporaryDirectory() as tmp_out:
            _run_map(source_dir, tmp_out)
            artifacts_dir = _artifacts_dir(name)
            os.makedirs(artifacts_dir, exist_ok=True)
            for filename in ARTIFACT_FILENAMES:
                with open(os.path.join(tmp_out, filename), encoding="utf-8") as handle:
                    payload = json.load(handle)
                _write_json(
                    os.path.join(artifacts_dir, filename),
                    _normalize(payload, source_dir_abs),
                )
            print(f"[update] wrote {len(ARTIFACT_FILENAMES)} artifacts for fixtures/{name}/")

        if name == INDEX_RESULT_FIXTURE:
            with tempfile.TemporaryDirectory() as tmp_out2:
                index_payload = _run_index_json(source_dir, tmp_out2)
                _write_json(
                    os.path.join(FIXTURES_ROOT, name, INDEX_RESULT_FILENAME),
                    _normalize(index_payload, source_dir_abs, os.path.abspath(tmp_out2)),
                )
            print(f"[update] wrote fixtures/{name}/{INDEX_RESULT_FILENAME}")
    return 0


def _validate_and_report(label: str, payload: dict) -> list[str]:
    try:
        schema_id, errors = validate_payload(payload, CONTRACT_ROOT)
    except ContractError as error:
        return [f"{label}: {error}"]
    if errors:
        return [f"{label} ({schema_id}): {error}" for error in errors]
    print(f"[ok]   {label} ({schema_id})")
    return []


def cmd_check() -> int:
    if not os.path.isdir(os.path.join(CONTRACT_ROOT, "schemas")):
        print(f"::error::missing contract schemas dir under {CONTRACT_ROOT}", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for name in FIXTURE_NAMES:
        source_dir = _source_dir(name)
        if not os.path.isdir(source_dir):
            all_errors.append(f"fixtures/{name}: missing source dir {source_dir}")
            continue
        with tempfile.TemporaryDirectory() as tmp_out:
            _run_map(source_dir, tmp_out)
            for filename in ARTIFACT_FILENAMES:
                with open(os.path.join(tmp_out, filename), encoding="utf-8") as handle:
                    payload = json.load(handle)
                all_errors.extend(_validate_and_report(f"fixtures/{name}/{filename}", payload))

        if name == INDEX_RESULT_FIXTURE:
            with tempfile.TemporaryDirectory() as tmp_out2:
                index_payload = _run_index_json(source_dir, tmp_out2)
                all_errors.extend(
                    _validate_and_report(f"fixtures/{name}/{INDEX_RESULT_FILENAME}", index_payload)
                )

    if all_errors:
        print(
            "::error::mapper output no longer matches contracts/mapper-artifacts/v1/schemas/. "
            "If this is a deliberate, compatible change, bump the contract (new schema file(s) "
            "+ `python3 scripts/regen_contract_fixtures.py update`); otherwise fix the mapper.",
            file=sys.stderr,
        )
        for error in all_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("mapper-artifacts contract check OK: real mapper output validates against contracts/mapper-artifacts/v1/schemas/")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("update", "check"):
        print(__doc__)
        return 2
    return cmd_update() if argv[0] == "update" else cmd_check()


if __name__ == "__main__":
    sys.exit(main())

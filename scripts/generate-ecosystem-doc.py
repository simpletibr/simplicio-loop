#!/usr/bin/env python3
"""Generate SIMPLICIO_ECOSYSTEM.md from real package metadata (issue #156).

``SIMPLICIO_ECOSYSTEM.md`` used to be hand-maintained and could drift from
``pyproject.toml`` / ``package.json`` (the real release version) and from
what downstream repos actually declare as their minimum supported
``simplicio-mapper`` version. This script makes the file a generated
artifact instead: run it to refresh the doc, or run it with ``--check`` to
fail loudly (CI-friendly) when the committed doc no longer matches reality.

Consumer constraints (who depends on this repo, and what minimum version
they declare) are not fetched live from other repos — this repo has no
cross-repo access. Instead they come from a small local fixture,
``scripts/ecosystem-consumers.json`` (schema ``simplicio.ecosystem-consumers/v1``):

    {
      "schema": "simplicio.ecosystem-consumers/v1",
      "consumers": [
        {
          "name": "simplicio-dev-cli",
          "repo": "https://github.com/wesleysimplicio/simplicio-dev-cli",
          "min_version": "0.15.0",
          "constraint_source": "pyproject.toml dependency `simplicio-mapper>=0.15.0`"
        }
      ]
    }

Update that fixture by hand whenever a consumer bumps its declared floor.
The generator compares each consumer's ``min_version`` against the real
current version (read from ``pyproject.toml``/``package.json``) and flags:

  - ``ahead``   — the consumer expects a *newer* mapper than what has been
                  released. Hard divergence: something is broken (the
                  consumer's floor cannot be satisfied). ``--check`` and the
                  default (write) mode both fail on this.
  - ``behind``  — the consumer's declared floor trails the current release.
                  Normal/expected most of the time (releases happen before
                  every consumer bumps its constraint), so this is reported
                  as a note in the generated doc rather than a failure, but
                  it is never silently dropped.
  - ``current`` — the consumer's floor matches the current release exactly.

Usage:
  python3 scripts/generate-ecosystem-doc.py            # regenerate + write
  python3 scripts/generate-ecosystem-doc.py --check    # verify freshness, exit 1 if stale
  python3 scripts/generate-ecosystem-doc.py --consumers <path>  # override fixture path
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT_PATH = os.path.join(ROOT, "pyproject.toml")
PACKAGE_JSON_PATH = os.path.join(ROOT, "package.json")
ECOSYSTEM_DOC_PATH = os.path.join(ROOT, "SIMPLICIO_ECOSYSTEM.md")
DEFAULT_CONSUMERS_PATH = os.path.join(ROOT, "scripts", "ecosystem-consumers.json")

GENERATED_MARKER = "<!-- simplicio-generated-doc: SIMPLICIO_ECOSYSTEM.md -->"
# The line that legitimately changes on every run (a fresh timestamp). It is
# excluded from the `--check` comparison so freshness checks do not flap
# daily on nothing but the clock; everything else in the doc must match.
DATE_LINE_PREFIX = "_Generated: "


class EcosystemDocError(RuntimeError):
    """Raised for unrecoverable metadata problems (e.g. version sources disagree)."""


def read_pyproject_version(path: str = PYPROJECT_PATH) -> str:
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise EcosystemDocError(f'could not find `version = "..."` in {path}')
    return match.group(1)


def read_package_json_version(path: str = PACKAGE_JSON_PATH) -> str:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    version = data.get("version")
    if not version:
        raise EcosystemDocError(f'could not find "version" in {path}')
    return version


def resolve_current_version() -> str:
    """Return the real current version, or raise if the two sources disagree.

    A mismatch here means the repo is already in an inconsistent release
    state (see also ``scripts/check-version-sync.js``); generating a doc
    from disagreeing sources would just encode a lie, so this is a hard
    error rather than a pick-one-and-hope.
    """
    pyproject_version = read_pyproject_version()
    package_json_version = read_package_json_version()
    if pyproject_version != package_json_version:
        raise EcosystemDocError(
            "version mismatch between pyproject.toml "
            f"({pyproject_version}) and package.json ({package_json_version}); "
            "fix the release bump before regenerating SIMPLICIO_ECOSYSTEM.md "
            "(see scripts/check-version-sync.js)."
        )
    return pyproject_version


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = re.split(r"[.\-+]", version.strip())
    numbers: list[int] = []
    for part in parts[:3]:
        try:
            numbers.append(int(part))
        except ValueError:
            numbers.append(0)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def compare_versions(left: str, right: str) -> int:
    """Return -1/0/1 comparing two dotted version strings (major.minor.patch)."""
    left_tuple, right_tuple = _parse_semver(left), _parse_semver(right)
    if left_tuple < right_tuple:
        return -1
    if left_tuple > right_tuple:
        return 1
    return 0


def load_consumers(path: str = DEFAULT_CONSUMERS_PATH) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    consumers = data.get("consumers", [])
    if not isinstance(consumers, list):
        raise EcosystemDocError(f'"consumers" in {path} must be a list')
    return consumers


def build_report(consumers: list[dict], current_version: str) -> list[dict]:
    """Attach a divergence ``status`` to each consumer entry.

    See module docstring for the ``ahead``/``behind``/``current`` semantics.
    """
    report = []
    for consumer in consumers:
        min_version = consumer.get("min_version", "0.0.0")
        cmp = compare_versions(min_version, current_version)
        status = "current" if cmp == 0 else ("ahead" if cmp > 0 else "behind")
        report.append({**consumer, "min_version": min_version, "status": status})
    return report


def divergent_consumers(report: list[dict]) -> list[dict]:
    """Consumers whose constraint is *ahead* of the current release.

    This is the only status treated as a hard failure: a consumer declaring
    a floor newer than what has actually shipped means that consumer's
    constraint cannot be satisfied by the real world right now.
    """
    return [entry for entry in report if entry["status"] == "ahead"]


def render_markdown(current_version: str, report: list[dict], generated_at: str) -> str:
    lines: list[str] = []
    lines.append("# simplicio-mapper no Ecossistema Simplicio")
    lines.append("")
    lines.append(GENERATED_MARKER)
    lines.append(
        "<!-- GENERATED FILE — do not hand-edit. Run "
        "`python3 scripts/generate-ecosystem-doc.py` to refresh it, or "
        "`python3 scripts/generate-ecosystem-doc.py --check` to verify it is "
        "fresh (wired into CI via .github/workflows/python-ci.yml). Source of "
        "truth: pyproject.toml / package.json versions plus "
        "scripts/ecosystem-consumers.json (consumer-constraints fixture; see "
        "scripts/README.md for its schema). -->"
    )
    lines.append("")
    lines.append("## Quem depende deste repo")
    if report:
        for entry in report:
            name = entry.get("name", "?")
            repo = entry.get("repo", "")
            min_version = entry.get("min_version", "0.0.0")
            label = f"[{name}]({repo})" if repo else name
            lines.append(f"- {label} >={min_version}")
    else:
        lines.append("- (nenhum consumidor conhecido em scripts/ecosystem-consumers.json)")
    lines.append("")
    lines.append("## De quem este repo depende")
    lines.append(
        "Nenhum outro repositório Simplicio. `simplicio-mapper` é a **base "
        "independente** do grafo do ecossistema Simplicio: nada nele exige "
        "outro pacote Simplicio para rodar, e todo o resto do ecossistema "
        "(simplicio-dev-cli, simplicio-loop, simplicio-runtime) consome os "
        "artefatos que ele produz."
    )
    lines.append("")
    lines.append("## Versão atual")
    lines.append(f"{current_version} (lido de `pyproject.toml` e `package.json`)")
    lines.append("")
    lines.append("## Versão mínima esperada pelos dependentes")
    if report:
        lines.append("| Consumidor | Constraint mínima | Status |")
        lines.append("|---|---|---|")
        for entry in report:
            name = entry.get("name", "?")
            min_version = entry.get("min_version", "0.0.0")
            status = entry["status"]
            if status == "current":
                status_label = "em dia com a versão atual"
            elif status == "behind":
                status_label = (
                    f"atrás da versão atual ({current_version}) — constraint "
                    "antiga, considerar atualizar no repo consumidor"
                )
            else:
                status_label = (
                    f"**à FRENTE da versão atual ({current_version}) — "
                    "divergência: o consumidor espera uma versão que ainda "
                    "não foi lançada**"
                )
            lines.append(f"| {name} | >={min_version} | {status_label} |")
    else:
        lines.append("(nenhum consumidor conhecido)")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"{DATE_LINE_PREFIX}{generated_at}_")
    lines.append("")
    return "\n".join(lines)


def _strip_date_line(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith(DATE_LINE_PREFIX))


def cmd_write(consumers_path: str) -> int:
    current_version = resolve_current_version()
    report = build_report(load_consumers(consumers_path), current_version)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    markdown = render_markdown(current_version, report, generated_at)
    with open(ECOSYSTEM_DOC_PATH, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    ahead = divergent_consumers(report)
    behind = [entry for entry in report if entry["status"] == "behind"]
    print(f"Wrote {ECOSYSTEM_DOC_PATH} (current version {current_version}).")
    for entry in behind:
        print(f"  [note] {entry['name']} constraint (>={entry['min_version']}) trails current release.")
    for entry in ahead:
        print(
            f"::error::{entry['name']} declares min_version {entry['min_version']} "
            f"which is AHEAD of the current release {current_version} (hard divergence)."
        )
    return 1 if ahead else 0


def cmd_check(consumers_path: str) -> int:
    current_version = resolve_current_version()
    report = build_report(load_consumers(consumers_path), current_version)
    ahead = divergent_consumers(report)
    for entry in ahead:
        print(
            f"::error::{entry['name']} declares min_version {entry['min_version']} "
            f"which is AHEAD of the current release {current_version} (hard divergence)."
        )
    if not os.path.isfile(ECOSYSTEM_DOC_PATH):
        print(f"::error::{ECOSYSTEM_DOC_PATH} is missing. Run "
              "`python3 scripts/generate-ecosystem-doc.py` and commit the result.",
              file=sys.stderr)
        return 1
    with open(ECOSYSTEM_DOC_PATH, encoding="utf-8") as handle:
        committed = handle.read()
    fresh = render_markdown(current_version, report, generated_at="placeholder")
    if _strip_date_line(committed) != _strip_date_line(fresh):
        print(
            f"::error::{ECOSYSTEM_DOC_PATH} is stale (does not match pyproject.toml / "
            "package.json / scripts/ecosystem-consumers.json). Run "
            "`python3 scripts/generate-ecosystem-doc.py` and commit the result.",
            file=sys.stderr,
        )
        return 1
    if ahead:
        return 1
    print(f"{ECOSYSTEM_DOC_PATH} is fresh (current version {current_version}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify freshness, do not write")
    parser.add_argument(
        "--consumers",
        default=DEFAULT_CONSUMERS_PATH,
        help="path to the consumer-constraints fixture (default: scripts/ecosystem-consumers.json)",
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            return cmd_check(args.consumers)
        return cmd_write(args.consumers)
    except EcosystemDocError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

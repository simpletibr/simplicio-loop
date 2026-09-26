"""Spec-drift detection and traceability matrix (Flow Documentation Engine F7).

Verifies ``.specs/**``/``docs/**`` against the real code: unresolved
template placeholders, specs that reference paths no longer in the tree
("orphan specs"), high fan-in code with zero mention in any spec/doc
("orphan code"), and doc staleness (delegates to
``docsync.build_docs_sync(check=True)``, F5).

Consults ``template-manifest.json`` (see ADR-004,
``.specs/architecture/ADR-004-template-vs-product-content-manifest.md``) so
this repo's own generic starter-template files (``ADR-template.md``,
``task-template.md``, the sprint-01 worked example) never register as
false-positive placeholders.

Emits ``simplicio.spec-drift/v1`` as documented in
``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import json
import os
import re

from .docsync import build_docs_sync
from .mapper import build_artifacts

SPEC_DRIFT_SCHEMA = "simplicio.spec-drift/v1"
SPEC_DRIFT_VERSION = 1

_SPEC_DIRS = (".specs", "docs")
_EXCLUDE_DIRS = {".simplicio-loop", "node_modules", ".git", "__pycache__"}
# All-caps SNAKE_CASE only (`<PRODUCT_NAME>`, `<TEAM>`, `<SYMPTOM>`) — matches
# scripts/check-placeholders.sh's own convention. Deliberately excludes
# lowercase CLI-usage placeholders like `<file>`/`<path>` in `usage: cmd <path>`
# examples, which are normal prose, not an unfilled starter template token.
_PLACEHOLDER_TOKEN = re.compile(r"<[A-Z][A-Z0-9_]{1,40}>")
# All-caps tokens that legitimately appear in technical prose (redacted
# secrets, auth scheme names) and are not starter-template placeholders.
_PLACEHOLDER_TOKEN_DENYLIST = {"REDACTED", "JWT", "UUID", "TODO", "FIXME"}
_PATH_REF = re.compile(r"`([\w][\w./-]*\.[A-Za-z0-9]{1,6})(?::\d+)?`")
_WILDCARD_SEGMENT = re.compile(r"(?:^|[/-])(XX|NNN|YYY|NN)(?:[/.-]|$)")
_KNOWN_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".yml", ".yaml", ".toml",
    ".sh", ".ps1", ".rs", ".go", ".java", ".rb", ".cs",
}
_DEFAULT_THRESHOLD = 10
_MIN_ORPHAN_FAN_IN = 3
_MAX_ORPHAN_FINDINGS = 15


def _load_manifest(cwd: str) -> dict:
    try:
        with open(os.path.join(cwd, "template-manifest.json"), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _spec_doc_paths(cwd: str) -> list[str]:
    paths = []
    for base in _SPEC_DIRS:
        base_path = os.path.join(cwd, base)
        if not os.path.isdir(base_path):
            continue
        for current, dirs, names in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            for name in names:
                if name.endswith(".md"):
                    rel = os.path.relpath(os.path.join(current, name), cwd).replace(os.sep, "/")
                    paths.append(rel)
    return sorted(paths)


def _read(cwd: str, rel: str) -> str:
    try:
        with open(os.path.join(cwd, rel), encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def _check_placeholders(cwd: str, spec_paths: list[str], generic_paths: set[str]) -> list[dict]:
    findings = []
    for rel in spec_paths:
        if rel in generic_paths:
            continue
        text = _read(cwd, rel)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _PLACEHOLDER_TOKEN.finditer(line):
                if match.group(0)[1:-1] in _PLACEHOLDER_TOKEN_DENYLIST:
                    continue
                findings.append({
                    "check": "placeholder",
                    "severity": "warn",
                    "target": rel,
                    "line": lineno,
                    "message": "template placeholder content detected",
                    "evidence": match.group(0),
                })
    return findings


def _check_orphan_specs(
    cwd: str, spec_paths: list[str], known_files: set[str], generic_paths: set[str],
) -> tuple[list[dict], dict[str, list[str]]]:
    findings: list[dict] = []
    links: dict[str, list[str]] = {}
    for rel in spec_paths:
        linked: list[str] = []
        if rel not in generic_paths:
            doc_dir = os.path.dirname(rel)
            text = _read(cwd, rel)
            for lineno, line in enumerate(text.splitlines(), start=1):
                for match in _PATH_REF.finditer(line):
                    candidate = match.group(1)
                    if os.path.splitext(candidate)[1] not in _KNOWN_EXTS:
                        continue
                    if "/" not in candidate:
                        # A bare filename (`VISION.md`, `project-map.json`) is too
                        # ambiguous to treat as an orphan reference — it's often a
                        # generated-artifact name (never part of the static tree),
                        # a naming-convention example, or a self-reference. Only
                        # multi-segment paths are precise enough to flag.
                        continue
                    if _WILDCARD_SEGMENT.search(candidate):
                        # Illustrative placeholder path (`sprint-XX/SPRINT.md`,
                        # `ADR-NNN-title.md`) — a naming pattern, not a real link.
                        continue
                    # A reference may be repo-root-relative (`src/main.py`) or
                    # relative to the doc's own directory (a markdown-link
                    # style reference like `product/VISION.md` inside
                    # `.specs/README.md`, meaning `.specs/product/VISION.md`).
                    # Try both before flagging it as orphaned.
                    root_relative = candidate.lstrip("./")
                    doc_relative = os.path.normpath(os.path.join(doc_dir, candidate)).replace(os.sep, "/")
                    resolved = None
                    for normalized in (root_relative, doc_relative):
                        if normalized in known_files or os.path.isfile(os.path.join(cwd, normalized)):
                            resolved = normalized
                            break
                    if resolved is not None:
                        linked.append(resolved)
                        continue
                    findings.append({
                        "check": "orphan-spec",
                        "severity": "warn",
                        "target": rel,
                        "line": lineno,
                        "message": f"references a path that does not exist: {candidate}",
                        "evidence": candidate,
                    })
        links[rel] = sorted(set(linked))
    return findings, links


def _check_orphan_code(architecture_inventory: dict, spec_paths: list[str], cwd: str) -> list[dict]:
    corpus = "\n".join(_read(cwd, rel) for rel in spec_paths)
    fan_in: dict[str, int] = {}
    for edge in architecture_inventory.get("relationships") or []:
        if edge.get("type") != "imports":
            continue
        target = edge.get("target_file")
        if not target:
            continue
        module = target.split("/", 1)[0] if "/" in target else "."
        fan_in[module] = fan_in.get(module, 0) + 1

    findings = []
    for module, count in sorted(fan_in.items(), key=lambda kv: (-kv[1], kv[0])):
        if count < _MIN_ORPHAN_FAN_IN:
            continue
        if module in corpus:
            continue
        findings.append({
            "check": "orphan-code",
            "severity": "info",
            "target": module,
            "line": None,
            "message": f"module has {count} incoming reference(s) but no mention in any spec/doc",
            "evidence": module,
        })
        if len(findings) >= _MAX_ORPHAN_FINDINGS:
            break
    return findings


def _scoped_paths(manifest: dict, all_paths: list[str], scope: str) -> tuple[list[str], set[str]]:
    if scope not in {"all", "product", "template"}:
        raise ValueError("scope must be all, product, or template")
    if scope == "all":
        return all_paths, set(manifest.get("generic_placeholder_paths") or [])
    if scope == "product":
        allowed = set(manifest.get("product_paths") or [])
        return sorted(path for path in all_paths if path in allowed), set()
    allowed = set(manifest.get("template_paths") or []) | set(manifest.get("generic_placeholder_paths") or [])
    return sorted(path for path in all_paths if path in allowed), allowed


def build_spec_drift(
    cwd: str,
    out_dir: str = ".simplicio-loop",
    threshold: int = _DEFAULT_THRESHOLD,
    *,
    scope: str = "all",
) -> dict:
    abs_cwd = os.path.abspath(cwd)
    manifest = _load_manifest(abs_cwd)
    generic_paths = set(manifest.get("generic_placeholder_paths") or [])

    artifacts = build_artifacts(abs_cwd, output_dir=out_dir)
    known_files = {f["path"] for f in artifacts["project_map"].get("files") or []}
    spec_paths, scope_generic_paths = _scoped_paths(manifest, _spec_doc_paths(abs_cwd), scope)
    if scope == "template":
        generic_paths = generic_paths - scope_generic_paths
    elif scope == "product":
        generic_paths = set()

    findings: list[dict] = []
    findings.extend(_check_placeholders(abs_cwd, spec_paths, generic_paths))
    orphan_spec_findings, links = _check_orphan_specs(abs_cwd, spec_paths, known_files, generic_paths)
    findings.extend(orphan_spec_findings)
    findings.extend(_check_orphan_code(artifacts["architecture_inventory"], spec_paths, abs_cwd))

    # Generated-doc freshness has its own `sync --check` gate. Keep it out of
    # the product/template ownership score so unrelated dirty artifacts do not
    # change the classification of product content.
    if scope == "all":
        sync_payload = build_docs_sync(abs_cwd, out_dir=out_dir, check=True)
        for doc in sync_payload.get("stale_docs") or []:
            findings.append({
                "check": "doc-stale",
                "severity": "warn",
                "target": doc,
                "line": None,
                "message": "generated doc is stale relative to the working tree — run `sync`",
                "evidence": doc,
            })

    traceability = {rel: links.get(rel, []) for rel in spec_paths if rel not in generic_paths}
    matrix_summary = {
        "specs_total": len(spec_paths),
        "specs_linked": sum(1 for rel, refs in traceability.items() if refs),
        "code_modules_uncovered": sorted({f["target"] for f in findings if f["check"] == "orphan-code"}),
    }

    findings.sort(key=lambda f: (f["check"], f["target"], f["line"] or 0))
    drift_count = len(findings)
    return {
        "schema": SPEC_DRIFT_SCHEMA,
        "version": SPEC_DRIFT_VERSION,
        "scope": scope,
        "findings": findings,
        "matrix_summary": matrix_summary,
        "traceability": traceability,
        "score": {"drift_findings": drift_count, "threshold": threshold, "pass": drift_count <= threshold},
    }


def render_drift_markdown(payload: dict) -> str:
    findings = payload["findings"]
    score = payload["score"]
    summary = payload["matrix_summary"]
    lines = [
        "# Spec Drift Report",
        "",
        "Auto-generated. Verifies `.specs/**` and `docs/**` against the real code: "
        "unresolved template placeholders, specs referencing paths that no longer "
        "exist, high-impact code with no spec/doc mention, and stale generated docs.",
        "",
        f"- Findings: {len(findings)} (threshold: {score['threshold']}, "
        f"{'PASS' if score['pass'] else 'FAIL'})",
        f"- Specs tracked: {summary['specs_total']} ({summary['specs_linked']} with at least one code reference)",
        "",
    ]
    if not findings:
        lines.append("No drift findings.")
        return "\n".join(lines)

    by_check: dict[str, list[dict]] = {}
    for finding in findings:
        by_check.setdefault(finding["check"], []).append(finding)
    for check in sorted(by_check):
        lines += [f"## {check}", "", "| Severity | Target | Message |", "| --- | --- | --- |"]
        for finding in by_check[check]:
            target = f"{finding['target']}:{finding['line']}" if finding.get("line") else finding["target"]
            lines.append(f"| {finding['severity']} | `{target}` | {finding['message']} |")
        lines.append("")

    if summary["code_modules_uncovered"]:
        lines += ["## Traceability — uncovered high-impact modules", ""]
        for module in summary["code_modules_uncovered"]:
            lines.append(f"- `{module}`")
        lines.append("")

    return "\n".join(lines)

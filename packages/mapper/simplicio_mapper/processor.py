"""simplicio_mapper.processor — PlanDAG and task understanding (Issue #654).

Extracts bounded project context via snapshot mmap and SemanticScorer,
builds PlanDAG v2 representations with ContextHandles and validation gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .changeset import (
    PreparedChange,
    load_changeset,
    prepare_changes,
)
from .store.neural.semantic_scoring import SemanticBudgets, SemanticScorer, SourceDocument
from .store.snapshot import (
    DEFAULT_MAX_SOURCE_FILE_BYTES,
    ContextSpan,
    Snapshot,
    build_snapshot,
)

STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "build",
    "change",
    "create",
    "do",
    "for",
    "from",
    "implement",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "through",
    "to",
    "update",
    "with",
    "criar",
    "de",
    "da",
    "e",
    "em",
    "implementar",
    "o",
    "os",
    "para",
    "por",
    "um",
    "uma",
}

STRUCTURAL_NOISE = STOP_WORDS | {
    "against",
    "benchmark",
    "check",
    "compare",
    "ensure",
    "measure",
    "reference",
    "run",
    "through",
    "validate",
}

IDENTIFIER_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*")
MAX_CONTEXT_CANDIDATES = 128


@dataclass(frozen=True, slots=True)
class Understanding:
    schema: str
    task: str
    terms: list[str]
    files: list[str]
    symbols: list[str]
    context: list[ContextSpan]
    selection: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlanNode:
    id: str
    kind: str
    depends_on: list[str]
    inputs: dict[str, Any]
    acceptance: list[str]


def _context_handle_id(span: ContextSpan) -> str:
    """Return the stable opaque ID for a PlanDAG context handle."""
    if span.symbol_id:
        return span.symbol_id
    identity = "|".join(
        (span.file, str(span.start_line), str(span.end_line), span.source_sha256)
    )
    return "context:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _context_handle(span: ContextSpan, generation: str) -> dict[str, Any]:
    """Return Mapper-bound lineage needed to reject stale context."""
    return {
        "handle": _context_handle_id(span),
        "generation": generation,
        "base_generation": span.base_generation or generation,
        "overlay_generation": span.overlay_generation,
        "source_sha256": span.source_sha256,
    }


def _identifier_terms(value: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [token.casefold() for token in IDENTIFIER_TOKEN.findall(expanded)]


def _task_index_terms(task: str) -> list[str]:
    return list(
        dict.fromkeys(
            token
            for token in _identifier_terms(task)
            if len(token) >= 2 and token not in STRUCTURAL_NOISE
        )
    )


def task_terms(task: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task.casefold())
    return list(dict.fromkeys(word for word in words if word not in STOP_WORDS))


def _resolve_default_snapshot(root: Path) -> Path:
    candidates = [
        root / ".simplicio-loop" / "project.sfast",
        root / ".simplicio-loop" / "fast" / "project.sfast",
        root / ".simplicio" / "fast" / "project.sfast",
        root / ".simplicio" / "project.sfast",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def run_dev_cli_changeset(
    root: Path, changeset: dict[str, Any], *, write: bool
) -> dict[str, Any] | None:
    try:
        from simplicio.mechanical_edit import execute_plan  # type: ignore[import-not-found]
    except ImportError:
        return None

    operations: list[dict[str, Any]] = []
    touched: list[str] = []
    for change in changeset.get("changes", ()):
        relative = change["path"]
        touched.append(relative)
        path = root / relative
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != change["expected_sha256"]:
            raise ValueError(f"stale source hash for {relative}")
        lines = raw.decode("utf-8").splitlines(keepends=True)
        for replacement in change["replacements"]:
            start = replacement["start_line"]
            end = replacement["end_line"]
            range_text = "".join(lines[start - 1 : end])
            text = replacement["content"]
            if text and not text.endswith("\n"):
                text += "\n"
            operations.append(
                {
                    "op": "replace_range",
                    "path": relative,
                    "start_line": start,
                    "end_line": end,
                    "text": text,
                    "file_sha256": hashlib.sha256(raw).hexdigest(),
                    "range_sha256": hashlib.sha256(range_text.encode("utf-8")).hexdigest(),
                }
            )
    result = execute_plan(
        {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": sorted(set(touched)),
            "operations": operations,
        },
        root=root,
        apply=write,
    )
    return {
        "adapter": "simplicio-dev-cli",
        "status": "executed",
        "result": result,
    }


class ProjectProcessor:
    def __init__(self, root: Path | str, snapshot_path: Path | str | None = None) -> None:
        self.root = Path(root).resolve()
        self.snapshot_path = (
            Path(snapshot_path).resolve()
            if snapshot_path
            else _resolve_default_snapshot(self.root)
        )

    def ingest(
        self,
        *,
        timeout_seconds: float | None = None,
        max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
    ) -> dict[str, Any]:
        metrics = build_snapshot(
            self.root,
            self.snapshot_path,
            timeout_seconds=timeout_seconds,
            max_file_bytes=max_file_bytes,
        )
        return {
            "schema": "simplicio.fast.ingest/v2",
            "snapshot": str(self.snapshot_path),
            "mapper": {
                "adapter": "simplicio-mapper",
                "status": "integrated",
            },
            "metrics": asdict(metrics),
        }

    @staticmethod
    def _symbol_key(symbol: Any) -> str:
        return (
            symbol.symbol_id or f"{symbol.qualified_name}|{symbol.file}|{symbol.line}"
        )

    @staticmethod
    def _span_key(span: ContextSpan) -> str:
        return span.symbol_id or f"{span.symbol}|{span.file}|{span.start_line}"

    @staticmethod
    def _term_idf_weights(
        terms: list[str], term_symbol_counts: dict[str, int], total_symbols: int
    ) -> dict[str, float]:
        total = max(1, total_symbols)
        raw = {
            term: math.log(1.0 + total / max(1, term_symbol_counts.get(term, total)))
            for term in terms
        }
        peak = max(raw.values(), default=1.0) or 1.0
        return {term: value / peak for term, value in raw.items()}

    @staticmethod
    def _structural_score(
        symbol: Any, terms: set[str], idf: dict[str, float] | None = None
    ) -> tuple[float, tuple[str, ...]]:
        idf = idf or {}
        name_terms = set(_identifier_terms(symbol.name))
        path_terms = set(_identifier_terms(Path(symbol.file).stem))
        searchable = {
            token
            for value in (
                symbol.name,
                symbol.qualified_name,
                symbol.file,
                symbol.signature,
            )
            for token in _identifier_terms(value)
        }
        matched = tuple(sorted(terms.intersection(searchable)))
        if not matched:
            return 0.0, ()

        def weight(term: str) -> float:
            return idf.get(term, 1.0)

        total_weight = sum(weight(term) for term in terms) or 1.0
        matched_weight = sum(weight(term) for term in matched)
        weighted_coverage = min(1.0, matched_weight / total_weight)
        name_ratio = sum(weight(t) for t in terms.intersection(name_terms)) / total_weight
        path_ratio = sum(weight(t) for t in terms.intersection(path_terms)) / total_weight
        kind_bonus = (
            1.0 if symbol.kind in {"class", "function", "async_function"} else 0.0
        )
        score = min(
            1.0,
            0.30
            + 0.30 * weighted_coverage
            + 0.15 * min(1.0, name_ratio)
            + 0.10 * kind_bonus
            + 0.15 * min(1.0, path_ratio),
        )
        return score, matched

    def _legacy_context(
        self,
        snapshot: Snapshot,
        terms: list[str],
        *,
        max_results: int,
        max_bytes: int,
    ) -> list[ContextSpan]:
        contexts: list[ContextSpan] = []
        seen: set[tuple[str, int, int]] = set()
        remaining = max_bytes
        for term in terms:
            if remaining <= 0 or len(contexts) >= max_results:
                break
            matches = snapshot.context(
                self.root,
                term,
                max_results=max_results - len(contexts),
                max_bytes=remaining,
            )
            for match in matches:
                key = (match.file, match.start_line, match.end_line)
                if key in seen:
                    continue
                seen.add(key)
                contexts.append(match)
                remaining -= len(match.content.encode())
                if remaining <= 0 or len(contexts) >= max_results:
                    break
        if contexts:
            return contexts
        ranked = sorted(
            snapshot.symbols(),
            key=lambda item: (
                0 if item.kind == "class" else 1,
                len(item.qualified_name),
                item.file,
            ),
        )
        for symbol in ranked[: min(max_results, 5)]:
            for match in snapshot.context(
                self.root,
                symbol.qualified_name,
                max_results=1,
                max_bytes=max(1, remaining),
            ):
                key = (match.file, match.start_line, match.end_line)
                if key not in seen:
                    seen.add(key)
                    contexts.append(match)
                    remaining -= len(match.content.encode())
        return contexts

    def _semantic_context(
        self,
        snapshot: Snapshot,
        task: str,
        *,
        max_results: int,
        max_bytes: int,
    ) -> tuple[list[ContextSpan], dict[str, Any]]:
        terms = _task_index_terms(task)
        receipt: dict[str, Any] = {
            "schema": "simplicio.fast.semantic-ranking-receipt/v1",
            "selection_mode": "structural-semantic",
            "requested_mode": "semantic",
            "generation": snapshot.generation,
            "candidate_terms": terms,
        }
        if not terms:
            return [], {
                **receipt,
                "selection_mode": "legacy-regex",
                "fallback": {"used": True, "reason_code": "NO_STRUCTURAL_TERMS"},
            }
        records: dict[str, dict[str, Any]] = {}
        term_set = set(terms)
        stems = {
            path_value: set(_identifier_terms(Path(path_value).stem))
            for path_value, _ in snapshot.files()
        }
        term_matches: dict[str, list[Any]] = {}
        for term in terms:
            found = {self._symbol_key(symbol): symbol for symbol in snapshot.search(term)}
            for path_value, stem_terms in stems.items():
                if term in stem_terms:
                    for symbol in snapshot.search("", path=path_value):
                        found.setdefault(self._symbol_key(symbol), symbol)
            term_matches[term] = list(found.values())
        term_symbol_counts = {
            term: len(matches) for term, matches in term_matches.items()
        }
        idf_weights = self._term_idf_weights(
            terms, term_symbol_counts, snapshot.symbol_count
        )
        receipt["term_document_frequency"] = term_symbol_counts
        for term in terms:
            for symbol in term_matches[term]:
                score, matched = self._structural_score(
                    symbol, term_set, idf_weights
                )
                if not matched:
                    continue
                key = self._symbol_key(symbol)
                record = records.setdefault(
                    key,
                    {
                        "symbol": symbol,
                        "structural_score": score,
                        "matched_terms": set(),
                    },
                )
                record["structural_score"] = max(record["structural_score"], score)
                record["matched_terms"].update(matched)
        ranked_records = sorted(
            records.values(),
            key=lambda item: (
                -item["structural_score"],
                -len(item["matched_terms"]),
                item["symbol"].qualified_name,
                item["symbol"].file,
            ),
        )[:MAX_CONTEXT_CANDIDATES]
        if not ranked_records:
            return [], {
                **receipt,
                "selection_mode": "legacy-regex",
                "candidate_count": 0,
                "fallback": {"used": True, "reason_code": "NO_STRUCTURAL_CANDIDATES"},
            }
        spans = snapshot.context_many(
            self.root,
            [item["symbol"].qualified_name for item in ranked_records],
            max_results=MAX_CONTEXT_CANDIDATES,
            max_bytes=max_bytes,
        )
        records_by_span = {
            self._span_key(item["symbol"]): item for item in ranked_records
        }
        documents: list[SourceDocument] = []
        spans_by_id: dict[str, ContextSpan] = {}
        explanations: dict[str, dict[str, Any]] = {}
        for span in spans:
            record = records_by_span.get(self._span_key(span))
            if record is None:
                continue
            canonical_id = f"{self._span_key(span)}:{span.end_line}"
            documents.append(
                SourceDocument.create(
                    canonical_id,
                    f"{span.file}\n{span.content}",
                    structural_score=float(record["structural_score"]),
                )
            )
            spans_by_id[canonical_id] = span
            explanations[canonical_id] = {
                "symbol": span.symbol,
                "file": span.file,
                "matched_terms": sorted(record["matched_terms"]),
                "structural_score": record["structural_score"],
            }
        if not documents:
            return [], {
                **receipt,
                "candidate_count": len(ranked_records),
                "abstention": {
                    "abstained": True,
                    "reason": "NO_CONTEXT_FOR_CANDIDATES",
                },
            }
        budgets = SemanticBudgets(
            max_candidates=len(documents),
            max_selected=min(max_results, len(documents)),
            max_request_bytes=max(256_000, max_bytes + len(task.encode("utf-8"))),
            max_selected_tokens=max(1, max_bytes // 4),
        )
        ranking = SemanticScorer(budgets=budgets).score(
            generation=snapshot.generation,
            query=task,
            candidates=documents,
        )
        selected_ids = {item["canonical_id"] for item in ranking["selected"]}
        for result in ranking["results"]:
            detail = explanations.get(result["canonical_id"], {})
            result["matched_terms"] = detail.get("matched_terms", [])
            result["selection_reason"] = (
                "selected"
                if result["canonical_id"] in selected_ids
                else f"rejected:{result.get('reason', 'lower_score')}"
            )
        ranking["selection_mode"] = "structural-semantic"
        ranking["requested_mode"] = "semantic"
        ranking["candidate_terms"] = terms
        ranking["candidate_explanations"] = explanations
        return [
            spans_by_id[item["canonical_id"]] for item in ranking["selected"]
        ], ranking

    def understand(
        self,
        task: str,
        *,
        max_results: int = 12,
        max_bytes: int = 48_000,
        max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
        selection_mode: str = "semantic",
    ) -> Understanding:
        if selection_mode not in {"semantic", "legacy-regex"}:
            raise ValueError("selection_mode must be semantic or legacy-regex")
        if not self.snapshot_path.exists():
            self.ingest(max_file_bytes=max_file_bytes)
        terms = task_terms(task)
        with Snapshot(self.snapshot_path) as snapshot:
            if selection_mode == "legacy-regex":
                contexts = self._legacy_context(
                    snapshot, terms, max_results=max_results, max_bytes=max_bytes
                )
                selection = {
                    "schema": "simplicio.fast.semantic-ranking-receipt/v1",
                    "selection_mode": "legacy-regex",
                    "requested_mode": selection_mode,
                    "generation": snapshot.generation,
                    "fallback": {"used": True, "reason_code": "EXPLICIT_LEGACY_MODE"},
                }
            else:
                contexts, selection = self._semantic_context(
                    snapshot, task, max_results=max_results, max_bytes=max_bytes
                )
                if selection.get("selection_mode") == "legacy-regex":
                    contexts = self._legacy_context(
                        snapshot, terms, max_results=max_results, max_bytes=max_bytes
                    )
                    selection["requested_mode"] = selection_mode
            selection["snapshot_provenance"] = snapshot.provenance
        return Understanding(
            schema="simplicio.fast.understanding/v2",
            task=task,
            terms=terms,
            files=sorted({item.file for item in contexts}),
            symbols=[item.symbol for item in contexts],
            context=contexts,
            selection=selection,
        )

    def plan(
        self,
        task: str,
        *,
        max_bytes: int = 48_000,
        max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
        selection_mode: str = "semantic",
    ) -> dict[str, Any]:
        understanding = self.understand(
            task,
            max_bytes=max_bytes,
            max_file_bytes=max_file_bytes,
            selection_mode=selection_mode,
        )
        generation = str(understanding.selection.get("generation") or "")
        context_handles = [
            _context_handle(item, generation) for item in understanding.context
        ]
        source_hashes = {
            item.file: item.source_sha256 for item in understanding.context
        }
        validation = self._validation_commands()
        nodes = [
            PlanNode(
                "orient",
                "context",
                [],
                {
                    "task": task,
                    "files": understanding.files,
                    "symbols": understanding.symbols,
                    "context_handles": context_handles,
                    "source_hashes": source_hashes,
                    "selection": understanding.selection,
                },
                ["context handles identify current bounded spans"],
            ),
            PlanNode(
                "modify",
                "structured_patch",
                ["orient"],
                {
                    "allowed_files": understanding.files,
                    "context_handles": context_handles,
                    "required_hashes": source_hashes,
                    "selection": understanding.selection,
                    "format": "simplicio.fast.changeset/v2",
                },
                [
                    "normal source files contain the requested behavior",
                    "all hash guards pass",
                ],
            ),
            PlanNode(
                "validate",
                "command_gate",
                ["modify"],
                {"commands": validation},
                ["all configured validation commands exit successfully"],
            ),
            PlanNode(
                "refresh",
                "snapshot_refresh",
                ["validate"],
                {"snapshot": str(self.snapshot_path)},
                ["changed files are visible in the next snapshot generation"],
            ),
        ]
        plan_understanding = {
            "schema": understanding.schema,
            "task": understanding.task,
            "terms": understanding.terms,
            "files": understanding.files,
            "symbols": understanding.symbols,
            "context_handles": context_handles,
            "selection": understanding.selection,
        }
        return {
            "schema": "simplicio.fast.plandag/v2",
            "task": task,
            "root": str(self.root),
            "context_handles": context_handles,
            "understanding": plan_understanding,
            "nodes": [asdict(node) for node in nodes],
        }

    def _validation_commands(self) -> list[list[str]]:
        commands: list[list[str]] = []
        pyproject = self.root / "pyproject.toml"
        pytest_ini = self.root / "pytest.ini"
        has_pytest = pytest_ini.exists() or (
            pyproject.exists() and "pytest" in pyproject.read_text(encoding="utf-8", errors="ignore")
        )
        if has_pytest:
            commands.append(["pytest"])
        elif pyproject.exists() or (self.root / "tests").exists():
            commands.append(
                ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
            )
        if (self.root / "package.json").exists():
            commands.append(["npm", "test"])
        if (self.root / "Cargo.toml").exists():
            commands.append(["cargo", "test"])
        if not commands:
            commands.append(["python", "-m", "compileall", "-q", "."])
        return commands

    @staticmethod
    def _atomic_replace(path: Path, data: bytes) -> None:
        temporary: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".simplicio-fast",
                delete=False,
            ) as handle:
                temporary = handle.name
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(path)
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    def _prepare_changes(self, changes: list[Any]) -> list[PreparedChange]:
        return prepare_changes(changes, root=self.root)

    def apply_changeset(
        self, changeset: dict[str, Any], *, write: bool
    ) -> dict[str, Any]:
        if changeset.get("schema") != "simplicio.fast.changeset/v2":
            raise ValueError("unsupported changeset schema")
        changes = changeset.get("changes")
        if not isinstance(changes, list) or not changes:
            raise ValueError("changeset must contain at least one change")
        prepared = self._prepare_changes(changes)
        before = self._file_records(prepared)

        try:
            delegated = run_dev_cli_changeset(self.root, changeset, write=write)
        except ValueError as error:
            if "stale source hash" in str(error):
                raise
            delegated = self._native_refusal("native_adapter_error", str(error))
        except Exception as error:  # noqa: BLE001
            delegated = self._native_refusal("native_adapter_error", str(error))

        if delegated is not None:
            result = delegated.get("result")
            if not isinstance(result, dict):
                result = {"status": "refused", "code": "invalid_native_receipt"}
                delegated = {**delegated, "result": result}
            if self._native_succeeded(result, write=write):
                after = self._file_records(prepared)
                expected_key = "result_sha256" if write else "before_sha256"
                if any(item["after_sha256"] != item[expected_key] for item in after):
                    self._restore_prepared(prepared)
                    result = {
                        "status": "refused",
                        "code": "native_output_hash_mismatch",
                        "message": (
                            "native adapter bytes differ from the canonical Fast result; "
                            "newline and encoding normalization must be byte-exact"
                        ),
                    }
                    delegated = {**delegated, "result": result}
                else:
                    return self._receipt(
                        mode="write" if write else "dry-run",
                        executor=delegated,
                        files=after,
                        native={
                            "status": "ok",
                            "before_sha256": {
                                item["path"]: item["before_sha256"] for item in before
                            },
                            "after_sha256": {
                                item["path"]: item["after_sha256"] for item in after
                            },
                            "no_write_proof": not write,
                        },
                        no_write_proof=not write,
                        outcome="applied" if write else "dry_run",
                        applied=write,
                        write_attempted=write,
                        reason_code=None,
                        rollback={
                            "attempted": False,
                            "status": "not-needed",
                            "restored_paths": [],
                        },
                    )

            native_before = self._file_records(prepared)
            restored = self._restore_prepared(prepared)
            native_after = self._file_records(prepared)
            if any(
                item["after_sha256"] != item["before_sha256"] for item in native_after
            ):
                raise RuntimeError("native refusal could not be rolled back safely")
            return self._fallback_receipt(
                prepared,
                write=write,
                reason="native_adapter_refused",
                native={
                    "adapter": delegated.get("adapter", "simplicio-dev-cli"),
                    "status": result.get("status", "refused"),
                    "result": result,
                    "before_sha256": {
                        item["path"]: item["before_sha256"] for item in native_before
                    },
                    "after_sha256": {
                        item["path"]: item["after_sha256"] for item in native_after
                    },
                    "rollback": {"attempted": bool(restored), "restored": restored},
                    "no_write_proof": True,
                },
                reason_code=str(result.get("code") or "native_adapter_refused"),
                rollback={
                    "attempted": True,
                    "status": "restored",
                    "restored_paths": restored,
                },
            )

        return self._fallback_receipt(
            prepared,
            write=write,
            reason="simplicio-dev-cli is not installed",
            native={
                "adapter": "simplicio-dev-cli",
                "status": "unavailable",
                "before_sha256": {
                    item["path"]: item["before_sha256"] for item in before
                },
                "after_sha256": {
                    item["path"]: item["before_sha256"] for item in before
                },
                "no_write_proof": True,
            },
            reason_code="native_unavailable",
            rollback={"attempted": False, "status": "not-needed", "restored_paths": []},
        )

    @staticmethod
    def _native_refusal(code: str, message: str) -> dict[str, Any]:
        return {
            "adapter": "simplicio-dev-cli",
            "status": "refused",
            "result": {"status": "refused", "code": code, "message": message},
        }

    @staticmethod
    def _native_succeeded(result: dict[str, Any], *, write: bool) -> bool:
        if result.get("status") != "ok":
            return False
        errors = result.get("errors")
        if isinstance(errors, list) and errors:
            return False
        return not (write and result.get("applied") is False)

    def _file_records(self, prepared: list[PreparedChange]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for item in prepared:
            current = item.path.read_bytes()
            records.append(
                {
                    "path": item.relative,
                    "replacements": item.replacements,
                    "expected_sha256": item.expected_sha256,
                    "before_sha256": hashlib.sha256(item.original).hexdigest(),
                    "after_sha256": hashlib.sha256(current).hexdigest(),
                    "result_sha256": hashlib.sha256(item.updated).hexdigest(),
                    "byte_representation": "raw-file-bytes",
                    "newline": "crlf" if b"\r\n" in item.updated else "lf",
                }
            )
        return records

    @staticmethod
    def _receipt(
        *,
        mode: str,
        executor: dict[str, Any],
        files: list[dict[str, Any]],
        native: dict[str, Any],
        no_write_proof: bool,
        outcome: str,
        applied: bool,
        write_attempted: bool,
        reason_code: str | None,
        rollback: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema": "simplicio.fast.apply-receipt/v2",
            "mode": mode,
            "executor": executor,
            "files": files,
            "native": native,
            "no_write_proof": no_write_proof,
            "outcome": outcome,
            "applied": applied,
            "write_attempted": write_attempted,
            "reason_code": reason_code,
            "rollback": rollback,
        }

    def _fallback_receipt(
        self,
        prepared: list[PreparedChange],
        *,
        write: bool,
        reason: str,
        native: dict[str, Any],
        reason_code: str,
        rollback: dict[str, Any],
    ) -> dict[str, Any]:
        if write:
            self._write_prepared(prepared)
        files = self._file_records(prepared)
        expected_after = {
            item.relative: hashlib.sha256(
                item.updated if write else item.original
            ).hexdigest()
            for item in prepared
        }
        if any(item["after_sha256"] != expected_after[item["path"]] for item in files):
            raise RuntimeError("internal fallback produced an unexpected output hash")
        fallback = {
            "adapter": "internal-bootstrap",
            "status": "fallback",
            "reason": reason,
            "write_applied": write,
            "no_write_proof": not write,
        }
        return self._receipt(
            mode="write" if write else "dry-run",
            executor=fallback,
            files=files,
            native=native,
            no_write_proof=not write,
            outcome="applied" if write else "dry_run",
            applied=write,
            write_attempted=write,
            reason_code=reason_code,
            rollback=rollback,
        )

    def _write_prepared(self, prepared: list[PreparedChange]) -> None:
        applied: list[PreparedChange] = []
        try:
            for item in prepared:
                if item.path.read_bytes() != item.original:
                    raise ValueError(f"stale source hash for {item.relative}")
                self._atomic_replace(item.path, item.updated)
                applied.append(item)
        except Exception:
            for item in reversed(applied):
                self._atomic_replace(item.path, item.original)
            raise

    def _restore_prepared(self, prepared: list[PreparedChange]) -> list[str]:
        restored: list[str] = []
        for item in prepared:
            if item.path.read_bytes() != item.original:
                self._atomic_replace(item.path, item.original)
                restored.append(item.relative)
        return restored


def understand(
    task: str,
    root: Path | str | None = None,
    snapshot_path: Path | str | None = None,
    *,
    max_results: int = 12,
    max_bytes: int = 48_000,
    max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
    selection_mode: str = "semantic",
) -> Understanding:
    root_path = Path(root or Path.cwd()).resolve()
    snap = (
        Path(snapshot_path).resolve()
        if snapshot_path
        else _resolve_default_snapshot(root_path)
    )
    processor = ProjectProcessor(root_path, snap)
    return processor.understand(
        task,
        max_results=max_results,
        max_bytes=max_bytes,
        max_file_bytes=max_file_bytes,
        selection_mode=selection_mode,
    )


def plan(
    task: str,
    root: Path | str | None = None,
    snapshot_path: Path | str | None = None,
    *,
    max_bytes: int = 48_000,
    max_file_bytes: int = DEFAULT_MAX_SOURCE_FILE_BYTES,
    selection_mode: str = "semantic",
) -> dict[str, Any]:
    root_path = Path(root or Path.cwd()).resolve()
    snap = (
        Path(snapshot_path).resolve()
        if snapshot_path
        else _resolve_default_snapshot(root_path)
    )
    processor = ProjectProcessor(root_path, snap)
    return processor.plan(
        task,
        max_bytes=max_bytes,
        max_file_bytes=max_file_bytes,
        selection_mode=selection_mode,
    )


def run_understand_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper understand",
        description="Understand a task using bounded project context.",
    )
    parser.add_argument("task", help="task description in natural language")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--snapshot", default=None, help="path to .sfast snapshot")
    parser.add_argument("--max-results", type=int, default=12)
    parser.add_argument("--max-bytes", type=int, default=48_000)
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_SOURCE_FILE_BYTES,
        help="maximum source file size to index",
    )
    parser.add_argument(
        "--selection-mode",
        choices=("semantic", "legacy-regex"),
        default="semantic",
    )
    args = parser.parse_args(list(argv))
    res = understand(
        args.task,
        root=args.root,
        snapshot_path=args.snapshot,
        max_results=args.max_results,
        max_bytes=args.max_bytes,
        max_file_bytes=args.max_file_bytes,
        selection_mode=args.selection_mode,
    )
    print(json.dumps(asdict(res), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


def run_plan_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="simplicio-mapper plan",
        description="Compile a task and semantic context into a PlanDAG.",
    )
    parser.add_argument("task", help="task description in natural language")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--snapshot", default=None, help="path to .sfast snapshot")
    parser.add_argument("--max-bytes", type=int, default=48_000)
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_SOURCE_FILE_BYTES,
        help="maximum source file size to index",
    )
    parser.add_argument(
        "--selection-mode",
        choices=("semantic", "legacy-regex"),
        default="semantic",
    )
    args = parser.parse_args(list(argv))
    res = plan(
        args.task,
        root=args.root,
        snapshot_path=args.snapshot,
        max_bytes=args.max_bytes,
        max_file_bytes=args.max_file_bytes,
        selection_mode=args.selection_mode,
    )
    print(json.dumps(res, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


__all__ = [
    "Understanding",
    "PlanNode",
    "PreparedChange",
    "ProjectProcessor",
    "understand",
    "plan",
    "run_understand_cli",
    "run_plan_cli",
    "build_snapshot",
    "load_changeset",
    "task_terms",
]

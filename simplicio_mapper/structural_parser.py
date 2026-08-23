"""Deterministic AST-first structural extraction.

Python uses the stdlib AST as the semantic source. Other supported languages
use a deliberately conservative declaration/import fallback until a mature
parser is installed by the host; fallback facts are never labelled exact.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable

from .structural_graph import EdgeKind, GraphEdge, GraphNode, NodeKind, StructuralGraph


LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".pyi": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".php": "php",
}


@dataclass(frozen=True, slots=True)
class Coverage:
    path: str
    language: str
    parser: str
    indexed_bytes: int
    skipped_bytes: int
    syntax_errors: tuple[str, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()
    confidence: float = 0.0

    @property
    def complete(self) -> bool:
        return not self.syntax_errors and self.skipped_bytes == 0 and self.confidence >= 0.9


@dataclass(frozen=True, slots=True)
class ParsedFile:
    path: str
    language: str
    content_hash: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    coverage: Coverage


def language_for_path(path: str) -> str:
    return LANGUAGE_BY_SUFFIX.get(PurePosixPath(path).suffix.lower(), "unknown")


def _source_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _line_end(node: ast.AST) -> int:
    return int(getattr(node, "end_lineno", getattr(node, "lineno", 0)))


def _qualified(prefix: tuple[str, ...], name: str) -> str:
    return ".".join((*prefix, name)) if prefix else name


class _PythonCollector(ast.NodeVisitor):
    def __init__(self, path: str, source: str, repo_identity: str, generation_id: str) -> None:
        self.path = path
        self.source = source
        self.repo_identity = repo_identity
        self.generation_id = generation_id
        self.content_hash = _source_hash(source)
        self.nodes: list[GraphNode] = []
        self.edges: list[GraphEdge] = []
        self.symbols: dict[str, GraphNode] = {}
        self.module = GraphNode.create(
            repo_identity,
            NodeKind.MODULE,
            path.replace("/", "."),
            path=path,
            language="python",
            content_hash=self.content_hash,
            generation_id=generation_id,
            provenance="ast",
        )
        self.nodes.append(self.module)
        self.scope: list[str] = []

    def _add_symbol(self, name: str, kind: NodeKind, node: ast.AST) -> GraphNode:
        qualified = _qualified(tuple(self.scope), name)
        symbol = GraphNode.create(
            self.repo_identity,
            kind,
            qualified,
            path=self.path,
            language="python",
            start_line=int(getattr(node, "lineno", 0)),
            end_line=_line_end(node),
            content_hash=self.content_hash,
            generation_id=self.generation_id,
            provenance="ast",
        )
        self.nodes.append(symbol)
        self.symbols[qualified] = symbol
        parent = self.symbols.get(_qualified(tuple(self.scope[:-1]), self.scope[-1])) if self.scope else self.module
        self.edges.append(GraphEdge(parent.node_id, symbol.node_id, EdgeKind.DEFINES, evidence=(f"{self.path}:{symbol.start_line}",)))
        return symbol

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add_symbol(node.name, NodeKind.CLASS, node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = NodeKind.METHOD if self.scope else NodeKind.FUNCTION
        self._add_symbol(node.name, kind, node)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target = self._module_target(alias.name)
            self.edges.append(GraphEdge(self.module.node_id, target.node_id, EdgeKind.IMPORTS, resolution_kind="import-resolved", evidence=(f"{self.path}:{node.lineno}",)))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = "." * node.level + (node.module or "")
        target = self._module_target(module_name)
        self.edges.append(GraphEdge(self.module.node_id, target.node_id, EdgeKind.IMPORTS, resolution_kind="import-resolved", evidence=(f"{self.path}:{node.lineno}",)))

    def _module_target(self, name: str) -> GraphNode:
        existing = self.symbols.get(f"@module:{name}")
        if existing:
            return existing
        target = GraphNode.create(
            self.repo_identity,
            NodeKind.PACKAGE,
            name or ".",
            path="",
            language="python",
            generation_id=self.generation_id,
            provenance="ast-import",
            confidence=0.95,
            metadata={"external": True},
        )
        self.nodes.append(target)
        self.symbols[f"@module:{name}"] = target
        return target

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            local = [symbol for qualified, symbol in self.symbols.items() if qualified == name or qualified.endswith(f".{name}")]
            if len(local) == 1:
                source = self._current_scope_symbol()
                self.edges.append(GraphEdge(source.node_id, local[0].node_id, EdgeKind.CALLS, evidence=(f"{self.path}:{node.lineno}",)))
            else:
                target = self._unresolved_target(name)
                source = self._current_scope_symbol()
                self.edges.append(GraphEdge(source.node_id, target.node_id, EdgeKind.CALL_REFERENCE, resolution_kind="ambiguous", confidence=0.25, evidence=(f"{self.path}:{node.lineno}",)))
        self.generic_visit(node)

    def _current_scope_symbol(self) -> GraphNode:
        if not self.scope:
            return self.module
        return self.symbols.get(_qualified(tuple(self.scope), "")) or self.symbols.get(".".join(self.scope)) or self.module

    def _unresolved_target(self, name: str) -> GraphNode:
        key = f"@unresolved:{name}"
        existing = self.symbols.get(key)
        if existing:
            return existing
        target = GraphNode.create(
            self.repo_identity,
            NodeKind.FUNCTION,
            name,
            language="python",
            generation_id=self.generation_id,
            provenance="ast-unresolved",
            confidence=0.25,
            metadata={"unresolved": True},
        )
        self.nodes.append(target)
        self.symbols[key] = target
        return target


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


_FALLBACK_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], NodeKind], ...]] = {
    "rust": ((re.compile(r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.FUNCTION), (re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.STRUCT)),
    "typescript": ((re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.CLASS), (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.FUNCTION)),
    "javascript": ((re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.CLASS), (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.FUNCTION)),
    "go": ((re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", re.MULTILINE), NodeKind.FUNCTION), (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct", re.MULTILINE), NodeKind.STRUCT)),
    "java": ((re.compile(r"^\s*(?:public\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.CLASS), (re.compile(r"^\s*(?:public\s+)?interface\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.INTERFACE)),
    "kotlin": ((re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.CLASS), (re.compile(r"^\s*fun\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.FUNCTION)),
    "csharp": ((re.compile(r"^\s*(?:public\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), NodeKind.CLASS),),
}


def parse_source(path: str, source: str, repo_identity: str, generation_id: str, language: str | None = None) -> ParsedFile:
    language = language or language_for_path(path)
    content_hash = _source_hash(source)
    if language == "python":
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as error:
            coverage = Coverage(path, language, "python-ast", len(source.encode()), len(source.encode()), (str(error),), confidence=0.0)
            return ParsedFile(path, language, content_hash, (), (), coverage)
        collector = _PythonCollector(path, source, repo_identity, generation_id)
        collector.visit(tree)
        coverage = Coverage(path, language, "python-ast", len(source.encode()), 0, confidence=1.0)
        return ParsedFile(path, language, content_hash, tuple(collector.nodes), tuple(collector.edges), coverage)

    patterns = _FALLBACK_PATTERNS.get(language, ())
    nodes: list[GraphNode] = [
        GraphNode.create(repo_identity, NodeKind.MODULE, path, path=path, language=language, content_hash=content_hash, generation_id=generation_id, provenance="fallback", confidence=0.45)
    ]
    edges: list[GraphEdge] = []
    for pattern, kind in patterns:
        for match in pattern.finditer(source):
            name = match.group(1)
            line = source.count("\n", 0, match.start()) + 1
            node = GraphNode.create(repo_identity, kind, f"{path}:{name}", path=path, language=language, start_line=line, end_line=line, content_hash=content_hash, generation_id=generation_id, provenance="fallback", confidence=0.45)
            nodes.append(node)
            edges.append(GraphEdge(nodes[0].node_id, node.node_id, EdgeKind.DEFINES, resolution_kind="exact-lexical", confidence=0.45, evidence=(f"{path}:{line}",)))
    coverage = Coverage(path, language, "conservative-regex-fallback", len(source.encode()), 0 if patterns else len(source.encode()), unsupported_constructs=("semantic-resolution",), confidence=0.45 if patterns else 0.1)
    return ParsedFile(path, language, content_hash, tuple(nodes), tuple(edges), coverage)


def build_structural_graph(
    files: Iterable[tuple[str, str]], *, repo_identity: str, generation_id: str
) -> tuple[StructuralGraph, tuple[Coverage, ...]]:
    parsed = [parse_source(path, source, repo_identity, generation_id) for path, source in sorted(files)]
    graph = StructuralGraph(repo_identity, generation_id)
    for item in parsed:
        for node in item.nodes:
            graph.add_node(node)
    for item in parsed:
        for edge in item.edges:
            graph.add_edge(edge)
    return graph, tuple(item.coverage for item in parsed)


__all__ = ["Coverage", "ParsedFile", "build_structural_graph", "language_for_path", "parse_source"]

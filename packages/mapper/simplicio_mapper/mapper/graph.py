"""Call-graph, architecture-inventory, symbol-index and macro-map
construction: everything that turns the discovered file list (see
``.parse``) into cross-file structure -- symbol definitions, import
resolution, call edges, architecture signals. Split from the former
monolithic ``mapper.py`` (issue #159) -- pure move, no behavior change.
"""

from __future__ import annotations

import keyword
import os
import posixpath
import re
import subprocess
from bisect import bisect_right

from ..models import ProjectFile
from ..relations import relation_coverage, relation_id
from ..semantic_resolution import RoslynSemanticAdapter, resolution_key, resolve_semantic_calls
from .parse import (
    _RE_CONFIG,
    _RE_DOMAIN,
    _RE_ROUTE,
    _RE_TEST_FILE,
    _RE_TEST_PATH,
    _RE_UI,
    ARCHITECTURE_INVENTORY_SCHEMA,
    ARTIFACT_VERSION,
    CALL_GRAPH_SCHEMA,
    CONFIG_FILES,
    ENTRYPOINT_STEMS,
    MACRO_MAP_SCHEMA,
    SYMBOL_INDEX_SCHEMA,
    _content_for,
    _json_text,
    _language_for,
    _layers_for_file,
    _module_name_for_path,
    _normalize_rel,
    _now_iso,
    _parse_json_safe,
    _responsibility_for_file,
    _walk,
)

_ARCH_CHECKS = [
    ("nextjs", re.compile(r"next")),
    ("react", re.compile(r"react")),
    ("vue", re.compile(r"vue")),
    ("angular", re.compile(r"angular|@angular")),
    ("express", re.compile(r"express")),
    ("nestjs", re.compile(r"nestjs|@nestjs")),
    ("fastapi", re.compile(r"fastapi")),
    ("django", re.compile(r"django")),
    ("dotnet", re.compile(r"aspnetcore|\.csproj|dotnet")),
    ("go", re.compile(r"\bgo\.mod\b|\bgin\b|\bfiber\b")),
    ("rust", re.compile(r"cargo\.toml|actix|axum")),
    ("playwright", re.compile(r"playwright")),
    ("stripe", re.compile(r"stripe")),
    ("prisma", re.compile(r"prisma")),
]

CALL_GRAPH_EDGE_LIMIT = 1000


def _semantic_line(value: dict) -> int | None:
    raw = value.get("line") or value.get("source_line")
    if isinstance(raw, bool):
        return None
    try:
        line = int(raw)
    except (TypeError, ValueError):
        return None
    return line if line >= 1 else None


def _csharp_parameter_signature(parameters: str) -> str:
    """Return a stable type-only signature for a C# method declaration."""
    result: list[str] = []
    for raw in parameters.split(","):
        value = re.sub(r"\s*=.*$", "", raw.strip())
        value = re.sub(r"\[[^]]*\]\s*", "", value)
        value = re.sub(r"\b(?:this|ref|out|in|params|scoped)\b\s*", "", value)
        tokens = value.split()
        if len(tokens) > 1 and re.fullmatch(r"[A-Za-z_]\w*", tokens[-1]):
            tokens.pop()
        if tokens:
            result.append(" ".join(tokens))
    return ", ".join(result)


def _call_graph_edge_limit(edge_limit: int | None = None) -> int:
    """Resolve the bounded graph output limit without hiding omissions."""
    if edge_limit is not None:
        return max(0, int(edge_limit))
    raw = os.environ.get("SIMPLICIO_MAPPER_CALL_GRAPH_EDGE_LIMIT", "")
    try:
        return max(0, int(raw)) if raw else CALL_GRAPH_EDGE_LIMIT
    except ValueError:
        return CALL_GRAPH_EDGE_LIMIT


def _collect_architecture_signals(pkg: dict, corpus: str, stack: str) -> list[str]:
    text = f"{stack}\n{_json_text(pkg)}\n{corpus}".lower()
    return sorted(name for name, rx in _ARCH_CHECKS if rx.search(text))

def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1

def _symbol_definitions_for_file(file: ProjectFile, text: str) -> list[dict]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    if file.language == "python":
        patterns = [
            (re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*def\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language in ("javascript", "typescript", "vue", "svelte"):
        patterns = [
            (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
            (
                re.compile(
                    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>",
                    re.MULTILINE,
                ),
                "function",
            ),
        ]
    elif file.language == "dart":
        patterns = [
            (re.compile(r"^\s*(?:abstract\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*enum\s+([A-Za-z_]\w*)", re.MULTILINE), "enum"),
            (re.compile(r"^\s*mixin\s+([A-Za-z_]\w*)", re.MULTILINE), "mixin"),
            (re.compile(r"^[ \t]*(?:[A-Za-z_][\w<>,? \t]*?[ \t]+)?(?!(?:if|for|while|switch|else|catch|finally|return|new|await|yield)\b)([a-z_]\w*)\s*\([^)]*\)\s*(?:async\s*)?\{", re.MULTILINE), "function"),
        ]
    elif file.language == "swift":
        patterns = [
            (re.compile(r"^\s*(?:public\s+|private\s+|internal\s+|open\s+|final\s+)*(?:class|struct|enum|protocol|extension|actor)\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*(?:public\s+|private\s+|internal\s+|static\s+|override\s+)*func\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language == "objectivec":
        patterns = [
            (re.compile(r"^\s*@interface\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*@implementation\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*[-+]\s*\([^)]*\)\s*([A-Za-z_]\w*)", re.MULTILINE), "method"),
        ]
    elif file.language == "cpp":
        patterns = [
            (re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^[ \t]*(?:[A-Za-z_][\w:<>, \t\*&]*?[ \t]+)([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?\{", re.MULTILINE), "function"),
        ]
    elif file.language == "c":
        patterns = [
            (re.compile(r"^\s*struct\s+([A-Za-z_]\w*)", re.MULTILINE), "struct"),
            (re.compile(r"^[ \t]*(?:[A-Za-z_][\w \t\*]*?[ \t]+)\**([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", re.MULTILINE), "function"),
        ]
    elif file.language == "scala":
        patterns = [
            (re.compile(r"^\s*(?:case\s+)?(?:class|object|trait)\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*def\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language == "sql":
        patterns = [
            (re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[\"`]?[A-Za-z_]\w*[\"`]?\.)?[\"`]?([A-Za-z_]\w*)[\"`]?", re.IGNORECASE), "table"),
            (re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:[\"`]?[A-Za-z_]\w*[\"`]?\.)?[\"`]?([A-Za-z_]\w*)[\"`]?", re.IGNORECASE), "view"),
            (re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+(?:[\"`]?[A-Za-z_]\w*[\"`]?\.)?[\"`]?([A-Za-z_]\w*)[\"`]?(?:\s|\(|$)", re.IGNORECASE), "procedure"),
            (re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:[\"`]?[A-Za-z_]\w*[\"`]?\.)?[\"`]?([A-Za-z_]\w*)[\"`]?(?:\s|\(|$)", re.IGNORECASE), "function"),
        ]
    elif file.language == "elixir":
        patterns = [
            (re.compile(r"^\s*defmodule\s+([A-Z][A-Za-z0-9_.]*)", re.MULTILINE), "module"),
            (re.compile(r"^\s*defp?\s+([a-z_]\w*[!?]?)", re.MULTILINE), "function"),
            (re.compile(r"^\s*defmacro(?:p)?\s+([a-z_]\w*[!?]?)", re.MULTILINE), "macro"),
        ]
    elif file.language == "erlang":
        patterns = [
            (re.compile(r"^\s*-\s*module\(([a-zA-Z0-9_@]+)\)\.", re.MULTILINE), "module"),
            (re.compile(r"^\s*([a-z][A-Za-z0-9_]*)\s*\([^)]*\)\s*->", re.MULTILINE), "function"),
        ]
    elif file.language == "lua":
        patterns = [
            (re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_]\w*(?:[:.][A-Za-z_]\w*)?)", re.MULTILINE), "function"),
        ]
    elif file.language == "r":
        patterns = [
            (re.compile(r"^\s*([A-Za-z.][A-Za-z0-9._]*)\s*(?:<-|=)\s*function\s*\(", re.MULTILINE), "function"),
        ]
    elif file.language == "julia":
        patterns = [
            (re.compile(r"^\s*module\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE), "module"),
            (re.compile(r"^\s*(?:mutable\s+)?struct\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*function\s+([A-Za-z_]\w*[!?]?)", re.MULTILINE), "function"),
            (re.compile(r"^\s*([A-Za-z_]\w*[!?]?)\s*\([^)]*\)\s*=", re.MULTILINE), "function"),
        ]
    elif file.language == "perl":
        patterns = [
            (re.compile(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_:]*)\s*;", re.MULTILINE), "module"),
            (re.compile(r"^\s*sub\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language == "matlab":
        patterns = [
            (re.compile(r"^\s*classdef\s+([A-Z][A-Za-z0-9_]*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*function\s+(?:\[[^\]]+\]\s*=|[A-Za-z_]\w*\s*=)?\s*([A-Za-z_]\w*)\s*\(", re.MULTILINE), "function"),
        ]
    elif file.language in ("css", "scss", "sass", "less"):
        patterns = [
            (re.compile(r"(?m)^\s*\.([A-Za-z_][\w-]*)\b"), "class"),
            (re.compile(r"(?m)^\s*#([A-Za-z_][\w-]*)\b"), "id"),
        ]
    elif file.language in ("html", "xhtml", "html-template"):
        patterns = [
            (re.compile(r"\bid\s*=\s*['\"]([A-Za-z_][\w:-]*)['\"]", re.IGNORECASE), "id"),
            (re.compile(r"<([A-Z][A-Za-z0-9:_-]*)\b"), "component"),
        ]
    elif file.language in ("csharp", "razor"):
        patterns = [
            (re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?(?:sealed\s+|static\s+|partial\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (
                re.compile(
                    r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z0-9_<>,\[\]\s?.]+\s+([A-Za-z_]\w*)\s*\(([^)]*)\)",
                    re.MULTILINE,
                ),
                "method",
            ),
        ]
    elif file.language == "go":
        patterns = [
            (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+struct\b", re.MULTILINE), "struct"),
            (re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+interface\b", re.MULTILINE), "interface"),
            (re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(", re.MULTILINE), "function"),
        ]
    elif file.language == "rust":
        patterns = [
            (re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
            (re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)", re.MULTILINE), "struct"),
            (re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z_]\w*)", re.MULTILINE), "enum"),
            (re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Za-z_]\w*)", re.MULTILINE), "trait"),
        ]
    elif file.language == "java":
        patterns = [
            (re.compile(r"^\s*(?:public\s+|protected\s+|private\s+)?(?:abstract\s+|final\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*(?:public\s+|protected\s+|private\s+)?interface\s+([A-Za-z_]\w*)", re.MULTILINE), "interface"),
            (re.compile(r"^\s*(?:public\s+|protected\s+|private\s+)?enum\s+([A-Za-z_]\w*)", re.MULTILINE), "enum"),
            (re.compile(r"^\s*(?:public\s+|protected\s+|private\s+)?record\s+([A-Za-z_]\w*)", re.MULTILINE), "record"),
            (
                re.compile(
                    r"(?:^|[;{}]\s*)(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?[A-Za-z0-9_<>,\[\]\s?]+\s+([A-Za-z_]\w*)\s*\(",
                    re.MULTILINE,
                ),
                "method",
            ),
        ]
    elif file.language == "kotlin":
        patterns = [
            (re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?interface\s+([A-Za-z_]\w*)", re.MULTILINE), "interface"),
            (re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?object\s+([A-Za-z_]\w*)", re.MULTILINE), "object"),
            (re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+)?fun\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language == "php":
        patterns = [
            (re.compile(r"^\s*(?:final\s+|abstract\s+)?class\s+([A-Za-z_]\w*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*interface\s+([A-Za-z_]\w*)", re.MULTILINE), "interface"),
            (re.compile(r"^\s*trait\s+([A-Za-z_]\w*)", re.MULTILINE), "trait"),
            (re.compile(r"^\s*enum\s+([A-Za-z_]\w*)", re.MULTILINE), "enum"),
            (re.compile(r"^\s*function\s+([A-Za-z_]\w*)", re.MULTILINE), "function"),
        ]
    elif file.language == "ruby":
        patterns = [
            (re.compile(r"\bclass\s+([A-Za-z_]\w*)"), "class"),
            (re.compile(r"\bmodule\s+([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)"), "module"),
            (re.compile(r"^\s*def\s+([A-Za-z_]\w*[!?=]?)", re.MULTILINE), "function"),
        ]
    else:
        return []

    symbols = []
    seen: set[tuple[str, int, str]] = set()
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)
            # Use the captured name's own start, not the whole match's start:
            # every pattern above anchors on `^\s*<keyword>` with re.MULTILINE,
            # and `\s` matches newlines too, so when a definition is preceded
            # by one or more blank lines `^` can anchor at an earlier blank
            # line and let `\s*` swallow the intervening newlines -- shifting
            # match.start() (and the reported line number) to that earlier
            # blank line instead of the real definition line. match.start(1)
            # sits on the identifier itself, which is always on the correct
            # source line regardless of how much leading whitespace matched.
            line = _line_number(text, match.start(1))
            key = (name, line, kind)
            if key in seen:
                continue
            seen.add(key)
            symbol = {
                "name": name,
                "qualified_name": f"{file.path}::{name}",
                "kind": kind,
                "language": file.language,
                "defined_in": file.path,
                "line": line,
                "evidence": {"file": file.path, "line": line},
            }
            if file.language in {"csharp", "razor"} and kind == "method":
                parameter_text = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
                signature = f"{name}({_csharp_parameter_signature(parameter_text)})"
                containing_class = max(
                    (
                        item
                        for item in symbols
                        if item["defined_in"] == file.path
                        and item["kind"] == "class"
                        and int(item["line"]) <= line
                    ),
                    key=lambda item: int(item["line"]),
                    default=None,
                )
                identity_prefix = (
                    f"{containing_class['name']}::" if containing_class is not None else ""
                )
                symbol["signature"] = signature
                symbol["symbol_id"] = f"{file.path}::{identity_prefix}{signature}"
                symbol["qualified_name"] = symbol["symbol_id"]
                symbol["evidence"]["resolution"] = "heuristic"
            symbols.append(symbol)
    return sorted(symbols, key=lambda item: (item["defined_in"], item["line"], item["name"]))

def _build_symbol_index(
    cwd: str,
    files: list[ProjectFile],
    generated_at: str,
    contents: dict[str, str] | None = None,
) -> dict:
    symbols = []
    for file in files:
        text = _content_for(cwd, file.path, contents)
        symbols.extend(_symbol_definitions_for_file(file, text))
    return {
        "schema": SYMBOL_INDEX_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "root": cwd.replace(os.sep, "/"),
        "symbols": symbols,
        "counts": {
            "symbols": len(symbols),
            "files": len({item["defined_in"] for item in symbols}),
        },
    }

def _strip_known_ext(rel: str) -> str:
    root, ext = posixpath.splitext(rel)
    return root if ext else rel

def _known_path_suffix_index(known_paths: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Bucket ``known_paths`` for the suffix-match fallback below, built once
    per :func:`_build_call_graph` call instead of re-derived per import.

    ``_candidate_import_targets``'s fallback keeps a candidate ``known`` path
    only when ``known_base.endswith(f"/{normalized}")`` or
    ``known_base == normalized`` (``known_base`` = extension-stripped
    ``known``). Either condition can only hold when the *final path segment*
    of ``known_base`` equals the final path segment of ``normalized`` -- an
    ``endswith("/" + normalized)`` match necessarily ends the string with
    ``normalized``'s last component, and an exact-equality match trivially
    shares it. Bucketing by that last segment therefore preserves the exact
    same matches as the original full scan while letting each import target
    only inspect its own bucket instead of every known path in the project
    (issue #235 follow-up -- fixes the profiled ``O(n^2)`` scan; see
    ADR-009).
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for known in known_paths:
        known_base = _strip_known_ext(known)
        bucket_key = known_base.rsplit("/", 1)[-1]
        index.setdefault(bucket_key, []).append((known, known_base))
    return index

def _candidate_import_targets(
    import_name: str,
    source_file: str,
    known_paths: set[str],
    known_path_index: dict[str, list[tuple[str, str]]] | None = None,
) -> list[str]:
    if not import_name or import_name.startswith("@"):
        return []
    if import_name.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_file), import_name))
    elif "/" in import_name and not import_name.startswith("/"):
        base = import_name
    elif "." in import_name:
        base = import_name.replace(".", "/")
    else:
        base = import_name

    bases = [base.lstrip("/")]
    if base.endswith("/index"):
        bases.append(base[:-6])
    candidates = []
    for item in bases:
        candidates.append(item)
        for ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".cs", ".go", ".rs"):
            candidates.append(f"{item}{ext}")
        for ext in (".py", ".js", ".ts", ".tsx"):
            candidates.append(f"{item}/index{ext}")
        candidates.append(f"{item}/__init__.py")
    direct = [candidate for candidate in candidates if candidate in known_paths]
    if direct:
        return direct

    normalized = _strip_known_ext(base).lstrip("/")
    bucket_key = normalized.rsplit("/", 1)[-1]
    index = known_path_index if known_path_index is not None else _known_path_suffix_index(known_paths)
    suffix_matches = [
        known
        for known, known_base in index.get(bucket_key, ())
        if known_base.endswith(f"/{normalized}") or known_base == normalized
    ]
    return sorted(suffix_matches)

_CALL_SKIP_NAMES = {
    "if", "for", "while", "switch", "catch", "return", "function", "class", "def",
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
}
_PYTHON_KEYWORDS = frozenset(keyword.kwlist) | frozenset(getattr(keyword, "softkwlist", ()))


def _is_skipped_call_name(name: str) -> bool:
    """Control-flow keywords and lexical noise never become ``type=calls``."""
    return name in _CALL_SKIP_NAMES or name in _PYTHON_KEYWORDS


_CALL_GRAPH_LANGUAGES = {
    "python", "javascript", "typescript", "csharp", "razor", "go", "rust",
    "java", "kotlin", "php", "ruby",
    "dart", "swift", "objectivec", "c", "cpp", "scala", "vue", "svelte",
    "elixir", "erlang", "lua", "r", "julia", "perl", "matlab",
}

def _call_expressions(text: str) -> list[tuple[str, int]]:
    calls = []
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", text):
        name = match.group(1)
        if _is_skipped_call_name(name):
            continue
        calls.append((name, _line_number(text, match.start())))
    return calls

def _nearest_symbol(
    symbols: list[dict],
    file: str,
    line: int,
    *,
    symbols_by_file: dict[str, list[dict]] | None = None,
    symbol_lines_by_file: dict[str, list[int]] | None = None,
) -> dict | None:
    if symbols_by_file is None:
        previous = [item for item in symbols if item["defined_in"] == file and item["line"] <= line]
        return max(previous, key=lambda item: int(item["line"]), default=None)

    candidates = symbols_by_file.get(file, [])
    if not candidates:
        return None
    lines = (symbol_lines_by_file or {}).get(file)
    if lines is None:
        lines = [int(item["line"]) for item in candidates]
    index = bisect_right(lines, line) - 1
    return candidates[index] if index >= 0 else None

def _build_call_graph(
    cwd: str,
    files: list[ProjectFile],
    symbol_index: dict,
    generated_at: str,
    contents: dict[str, str] | None = None,
    *,
    edge_limit: int | None = None,
    semantic_adapter: RoslynSemanticAdapter | None = None,
) -> dict:
    """Build the canonical Mapper v1 relation envelope.

    The parser is intentionally conservative: name lookup can enumerate
    candidates, but it cannot claim language-semantic resolution.  Ambiguous
    candidates stay as separate relations with the same call-site provenance.
    Unresolved *import* sites stay as explicit unknown relations.  Unresolved
    *calls* never enter the graph (no ``resolution_status=unknown`` and no
    null ``target_file``); they may appear on an optional ``unresolved`` list.
    """
    known_paths = {file.path for file in files}
    known_path_index = _known_path_suffix_index(known_paths)
    symbols = list(symbol_index.get("symbols") or [])
    symbols_by_name: dict[str, list[dict]] = {}
    symbols_by_file: dict[str, list[dict]] = {}
    for symbol in symbols:
        symbols_by_name.setdefault(symbol["name"], []).append(symbol)
        symbols_by_file.setdefault(symbol["defined_in"], []).append(symbol)
    for definitions in symbols_by_file.values():
        definitions.sort(key=lambda item: (int(item["line"]), str(item.get("qualified_name") or item.get("name") or "")))
    symbol_lines_by_file = {
        path: [int(item["line"]) for item in definitions]
        for path, definitions in symbols_by_file.items()
    }

    call_sites: list[dict] = []
    definition_sites = {
        (str(item.get("defined_in") or ""), int(item.get("line") or 0), str(item.get("name") or ""))
        for item in symbols
    }
    for file in files:
        if file.language not in _CALL_GRAPH_LANGUAGES:
            continue
        text = _content_for(cwd, file.path, contents)
        for name, line in _call_expressions(text):
            if (file.path, line, name) in definition_sites:
                continue
            if _is_skipped_call_name(name):
                continue
            call_sites.append({"source_file": file.path, "name": name, "line": line})

    semantic_by_site: dict[tuple[str, int, str], dict] = {}
    semantic_receipts: list[dict] = []
    for language in ("csharp", "razor"):
        language_sites = [item for item in call_sites if next(
            (file.language for file in files if file.path == item["source_file"]), ""
        ) == language]
        if not language_sites:
            continue
        source_generation = [
            {"path": file.path, "content": _content_for(cwd, file.path, contents)}
            for file in files
            if file.language == language
        ]
        result, receipt = resolve_semantic_calls(
            cwd,
            language,
            source_generation,
            symbols,
            language_sites,
            adapter=semantic_adapter,
        )
        semantic_receipts.append(receipt)
        if isinstance(result, dict):
            for item in result.get("resolutions", []):
                if not isinstance(item, dict):
                    continue
                key = resolution_key(item)
                if key is not None:
                    semantic_by_site[key] = item
            by_definition = {
                (str(item.get("defined_in") or ""), int(item.get("line") or 0), str(item.get("name") or "")): item
                for item in symbols
            }
            for item in result.get("symbols", []):
                if not isinstance(item, dict):
                    continue
                line = _semantic_line(item)
                if line is None:
                    continue
                key = (
                    str(item.get("defined_in") or item.get("source_file") or ""),
                    line,
                    str(item.get("name") or ""),
                )
                symbol = by_definition.get(key)
                if symbol is None:
                    continue
                resolved_name = item.get("symbol_id") or item.get("qualified_name")
                if isinstance(resolved_name, str) and resolved_name:
                    symbol["qualified_name"] = resolved_name
                    symbol["symbol_id"] = resolved_name
                if isinstance(item.get("signature"), str) and item["signature"]:
                    symbol["signature"] = item["signature"]
                evidence = symbol.setdefault("evidence", {})
                evidence["resolution"] = "semantic"
                evidence["semantic_provider"] = receipt.get("provider")

    if semantic_receipts:
        status_set = {str(item.get("status")) for item in semantic_receipts}
        if status_set == {"available"}:
            semantic_status = "available"
        elif "available" in status_set:
            semantic_status = "degraded"
        else:
            semantic_status = "unavailable"
        semantic_resolution = {
            "schema": "simplicio.mapper-semantic-resolution/v1",
            "protocol": "v1",
            "status": semantic_status,
            "languages": sorted({language for item in semantic_receipts for language in item.get("languages", [])}),
            "providers": sorted({item["provider"] for item in semantic_receipts if item.get("provider")}),
            "provider_versions": sorted({item["provider_version"] for item in semantic_receipts if item.get("provider_version")}),
            "resolved_calls": sum(int(item.get("resolved_calls") or 0) for item in semantic_receipts),
            "symbols": sum(int(item.get("symbols") or 0) for item in semantic_receipts),
            "reasons": sorted({item["reason"] for item in semantic_receipts if item.get("reason")}),
        }
    else:
        semantic_resolution = {
            "schema": "simplicio.mapper-semantic-resolution/v1",
            "protocol": "v1",
            "status": "not_required",
            "languages": [],
            "providers": [],
            "provider_versions": [],
            "resolved_calls": 0,
            "symbols": 0,
            "reasons": ["no_csharp_or_razor_call_sites"],
        }

    # Rebuild indexes after semantic services have supplied unique symbol
    # identities for overloaded methods.
    symbols_by_name = {}
    symbols_by_file = {}
    for symbol in symbols:
        symbols_by_name.setdefault(symbol["name"], []).append(symbol)
        symbols_by_file.setdefault(symbol["defined_in"], []).append(symbol)
    for definitions in symbols_by_file.values():
        definitions.sort(key=lambda item: (int(item["line"]), str(item.get("qualified_name") or item.get("name") or "")))
    symbol_lines_by_file = {
        path: [int(item["line"]) for item in definitions]
        for path, definitions in symbols_by_file.items()
    }
    symbols_by_identity = {
        str(item.get("symbol_id") or item.get("qualified_name") or ""): item
        for item in symbols
        if item.get("symbol_id") or item.get("qualified_name")
    }
    file_by_path = {file.path: file for file in files}

    def semantic_target(resolution: dict) -> dict | None:
        identity = resolution.get("target_symbol") or resolution.get("symbol_id") or resolution.get("target_symbol_id")
        if isinstance(identity, str) and identity in symbols_by_identity:
            return symbols_by_identity[identity]
        target_file = resolution.get("target_file")
        target_line = resolution.get("target_line")
        target_name = resolution.get("target_name") or resolution.get("name")
        if isinstance(target_file, str) and isinstance(target_line, int) and not isinstance(target_line, bool) and isinstance(target_name, str):
            matches = [
                item for item in symbols_by_file.get(target_file.replace("\\", "/"), [])
                if int(item.get("line") or 0) == target_line and item.get("name") == target_name
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    edges: list[dict] = []
    unresolved: list[dict] = []
    seen: set[str] = set()

    def add_edge(edge: dict) -> None:
        if not edge.get("target_file") or edge.get("resolution_status") in {None, "unknown"}:
            return
        edge["relation_id"] = relation_id(edge)
        key = edge["relation_id"]
        if key in seen:
            return
        seen.add(key)
        edges.append(edge)

    for file in files:
        for imported in file.imports:
            targets = _candidate_import_targets(imported, file.path, known_paths, known_path_index)
            evidence_class = "import_resolved" if len(targets) == 1 else "lexical_ambiguous"
            candidates = sorted(targets)
            if not candidates:
                unresolved.append({
                    "source_file": file.path,
                    "queried_symbol": imported,
                    "kind": "import",
                })
                continue
            for target in candidates:
                if target == file.path:
                    continue
                add_edge({
                    "type": "imports",
                    "source_file": file.path,
                    "target_file": target,
                    "import": imported,
                    "evidence_class": evidence_class,
                    "resolution_status": "resolved" if len(candidates) == 1 else "ambiguous",
                    "target_candidates": candidates,
                    "provenance": {
                        "method": "import-resolution",
                        "import": imported,
                        "candidate_count": len(candidates),
                        "candidates": candidates,
                    },
                    "confidence": None,
                })

    for call_site in call_sites:
        file = file_by_path[call_site["source_file"]]
        name = call_site["name"]
        line = call_site["line"]
        if name in _PYTHON_KEYWORDS:
            continue
        resolution = semantic_by_site.get((file.path, line, name))
        target = semantic_target(resolution) if resolution is not None else None
        targets = [target] if target is not None else list(symbols_by_name.get(name, []))
        targets = [item for item in targets if item.get("defined_in")]
        target_candidates = sorted(
            str(item.get("symbol_id") or item.get("qualified_name") or item.get("name") or "")
            for item in targets
        )
        is_semantic = target is not None and resolution is not None
        is_csharp = file.language in {"csharp", "razor"}
        if not targets:
            unresolved.append({
                "source_file": file.path,
                "line": line,
                "queried_symbol": name,
            })
            continue
        for candidate in targets:
            if candidate["defined_in"] == file.path and candidate["line"] == line:
                continue
            caller = _nearest_symbol(
                symbols,
                file.path,
                line,
                symbols_by_file=symbols_by_file,
                symbol_lines_by_file=symbol_lines_by_file,
            )
            evidence_class = "semantic_resolved" if is_semantic else (
                "heuristic" if is_csharp else "lexical_unique" if len(targets) == 1 else "lexical_ambiguous"
            )
            resolution_status = "resolved" if is_semantic else (
                "inferred" if is_csharp and len(targets) == 1 else "resolved" if len(targets) == 1 else "ambiguous"
            )
            provenance = {
                "method": "roslyn-semantic-service" if is_semantic else "semantic-service-fallback" if is_csharp else "symbol-name-lookup",
                "queried_symbol": name,
                "candidate_count": len(targets),
                "candidates": target_candidates,
                "caller_resolution": "lexical_nearest" if caller else "unknown",
            }
            if is_semantic:
                provenance.update({
                    "provider": semantic_resolution.get("providers", [None])[0],
                    "provider_version": semantic_resolution.get("provider_versions", [None])[0],
                    "semantic_symbol_id": candidate.get("symbol_id") or candidate.get("qualified_name"),
                    "overload_signature": candidate.get("signature"),
                })
            else:
                provenance["fallback_reason"] = semantic_resolution.get("reasons", []) if is_csharp else None
            add_edge({
                "type": "calls",
                "source_file": file.path,
                "source_symbol": caller["qualified_name"] if caller else None,
                "target_file": candidate["defined_in"],
                "target_symbol": candidate.get("symbol_id") or candidate["qualified_name"],
                "line": line,
                "target_candidates": target_candidates,
                "evidence_class": evidence_class,
                "resolution_status": resolution_status,
                "provenance": provenance,
                "confidence": None,
            })

    symbol_index["semantic_resolution"] = semantic_resolution

    limit = _call_graph_edge_limit(edge_limit)
    ordered_edges = sorted(edges, key=lambda item: (
        item.get("source_file") or "",
        item.get("target_file") or "",
        item.get("type") or "",
        item.get("target_symbol") or item.get("import") or "",
        item.get("line") or 0,
        item.get("relation_id") or "",
    ))
    emitted_edges = ordered_edges[:limit]
    unresolved.sort(key=lambda item: (
        str(item.get("source_file") or ""),
        int(item.get("line") or 0),
        str(item.get("queried_symbol") or ""),
    ))
    payload = {
        "schema": CALL_GRAPH_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_symbol_index": ".simplicio/symbol-index.json",
        "edges": emitted_edges,
        "counts": {
            "edges": len(emitted_edges),
            "imports": len([item for item in emitted_edges if item["type"] == "imports"]),
            "calls": len([item for item in emitted_edges if item["type"] == "calls"]),
        },
        "coverage": relation_coverage(
            emitted_edges,
            observed_edges=len(ordered_edges),
            edge_limit=limit,
        ),
        "semantic_resolution": semantic_resolution,
    }
    if unresolved:
        payload["unresolved"] = unresolved
    return payload

def _build_architecture_inventory(
    cwd: str,
    project_map: dict,
    files: list[ProjectFile],
    symbol_index: dict,
    call_graph: dict,
    generated_at: str,
) -> dict:
    symbols_by_file: dict[str, list[dict]] = {}
    for symbol in symbol_index.get("symbols", []):
        symbols_by_file.setdefault(symbol["defined_in"], []).append(symbol)

    inventory_files = []
    modules: dict[str, dict] = {}
    layers: dict[str, dict] = {}

    for file in files:
        file_layers = _layers_for_file(file)
        file_symbols = symbols_by_file.get(file.path, [])
        file_entry = {
            "path": file.path,
            "language": file.language,
            "module": _module_name_for_path(file.path),
            "layers": file_layers,
            "roles": file.roles,
            "imports": file.imports,
            "symbols": [item["name"] for item in file_symbols],
            "summary": _responsibility_for_file(file, file_layers),
            "evidence": [{"file": file.path}],
        }
        inventory_files.append(file_entry)

        module = modules.setdefault(file_entry["module"], {
            "name": file_entry["module"],
            "files": [],
            "layers": set(),
            "entry_points": [],
            "tests": [],
            "public_symbols": [],
        })
        module["files"].append(file.path)
        module["layers"].update(file_layers)
        if "entrypoint" in file_layers:
            module["entry_points"].append(file.path)
        if "test" in file_layers:
            module["tests"].append(file.path)
        module["public_symbols"].extend(file_entry["symbols"])

        for layer_name in file_layers:
            layer = layers.setdefault(layer_name, {"name": layer_name, "files": [], "modules": set()})
            layer["files"].append(file.path)
            layer["modules"].add(file_entry["module"])

    module_entries = []
    for module in sorted(modules.values(), key=lambda item: item["name"]):
        module_entries.append({
            "name": module["name"],
            "summary": f"Groups {len(module['files'])} files across {len(module['layers'])} detected layers.",
            "file_count": len(module["files"]),
            "files": module["files"][:80],
            "layers": sorted(module["layers"]),
            "entry_points": sorted(module["entry_points"]),
            "tests": sorted(module["tests"]),
            "public_symbols": sorted(set(module["public_symbols"]))[:40],
            "evidence": [{"file": path} for path in module["files"][:10]],
        })

    layer_entries = []
    for layer in sorted(layers.values(), key=lambda item: item["name"]):
        layer_entries.append({
            "name": layer["name"],
            "file_count": len(layer["files"]),
            "files": sorted(layer["files"])[:100],
            "modules": sorted(layer["modules"]),
            "evidence": [{"file": path} for path in sorted(layer["files"])[:10]],
        })

    relationships = list(call_graph.get("edges") or [])[:250]
    return {
        "schema": ARCHITECTURE_INVENTORY_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "root": cwd.replace(os.sep, "/"),
        "source_project_map": ".simplicio/project-map.json",
        "source_symbol_index": ".simplicio/symbol-index.json",
        "source_call_graph": ".simplicio/call-graph.json",
        "product": project_map.get("product", {}),
        "architecture": project_map.get("architecture", {}),
        "modules": module_entries,
        "layers": layer_entries,
        "files": sorted(inventory_files, key=lambda item: item["path"]),
        "relationships": relationships,
        "coverage": {
            "files": len(files),
            "modules": len(module_entries),
            "layers": len(layer_entries),
            "symbols": len(symbol_index.get("symbols", []) or []),
            "relationships": len(relationships),
            "tests": len(project_map.get("test_files", []) or []),
        },
        "relationship_coverage": relation_coverage(
            relationships,
            observed_edges=len(call_graph.get("edges", []) or []),
            edge_limit=250,
        ),
        "notes": [
            "Generated from deterministic repository inspection.",
            "Relationship evidence_class and resolution_status describe how each edge was obtained; null confidence is not a calibrated probability.",
        ],
    }

_ENDPOINT_EXTS = {".cs", ".py", ".ts", ".tsx", ".js", ".jsx"}

def _macro_roles_for_path(rel: str, base: str, main_value: str, bin_values: list[str]) -> set[str]:
    """Path-only role detection (mirror of :func:`_roles_for`, no content reads)."""
    roles: set[str] = set()
    no_ext = re.sub(r"\.[^.]+$", "", base).lower()
    if _RE_TEST_PATH.search(rel) or _RE_TEST_FILE.search(base):
        roles.add("test")
    if base in CONFIG_FILES or _RE_CONFIG.search(base):
        roles.add("config")
    if main_value == rel or rel in bin_values or no_ext in ENTRYPOINT_STEMS:
        roles.add("entrypoint")
    if _RE_ROUTE.search(rel):
        roles.add("route")
    if _RE_UI.search(rel):
        roles.add("ui")
    if _RE_DOMAIN.search(rel):
        roles.add("domain")
    return roles

def _macro_layers_for_path(rel: str, base: str, language: str, roles: set[str]) -> set[str]:
    """Path-only layer detection (mirror of :func:`_layers_for_file`)."""
    low = rel.lower()
    layers = set(roles)
    if "controller" in low:
        layers.add("controller")
    if "service" in low:
        layers.add("service")
    if "repository" in low or "repositories" in low or "repo" in base.lower():
        layers.add("repository")
    if "model" in low or "entity" in low or "schema" in low:
        layers.add("model")
    if "route" in low or "router" in low:
        layers.add("route")
    if low.startswith("scripts/"):
        layers.add("script")
    if low.startswith("docs/") or language == "markdown":
        layers.add("documentation")
    if not layers:
        layers.add("code" if language in {"python", "javascript", "typescript", "csharp", "go", "rust", "dart", "swift", "objectivec", "c", "cpp", "scala", "vue", "svelte", "elixir", "erlang", "lua", "r", "julia", "perl", "matlab"} else "asset")
    return layers

def _is_macro_screen(rel: str, base: str, language: str) -> bool:
    """Shallow screen heuristic from path alone (no content reads)."""
    low = rel.lower()
    if language == "razor":
        return True
    if base.endswith((".page.ts", ".page.tsx", ".page.js", ".page.jsx")):
        return True
    if ".component.ts" in base or ".component.tsx" in base:
        return True
    if language in {"javascript", "typescript"} and ("/pages/" in low or low.startswith("pages/") or "/app/" in low):
        if base in {"page.tsx", "page.jsx", "page.ts", "page.js", "index.tsx", "index.jsx"}:
            return True
    return False

def _macro_git(cwd: str) -> dict:
    head = ""
    dirty = False
    degraded = False
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return {"head": "", "dirty": False, "degraded": False}
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL,
        )
        if rev.returncode == 0:
            head = rev.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd, capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL,
        )
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        degraded = True
        return {"head": head, "dirty": dirty, "degraded": degraded}
    return {"head": head, "dirty": dirty, "degraded": degraded}

def build_macro_map(cwd: str, meta: dict | None = None) -> dict:
    """Sub-second shallow project skeleton (``simplicio.macro-map/v1``).

    Derived from filenames plus a few manifests only — no per-file content
    reads, no symbol/call-graph pass. Confidence is therefore ``shallow``.
    """
    meta = meta or {}
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    pkg = _parse_json_safe(os.path.join(abs_cwd, "package.json"))
    pyproject = os.path.exists(os.path.join(abs_cwd, "pyproject.toml"))

    main_value = _normalize_rel(pkg["main"]) if isinstance(pkg.get("main"), str) else ""
    bin_field = pkg.get("bin")
    if isinstance(bin_field, str):
        bin_values = [_normalize_rel(bin_field)]
    elif isinstance(bin_field, dict):
        bin_values = [_normalize_rel(v) for v in bin_field.values() if isinstance(v, str)]
    else:
        bin_values = []

    by_language: dict[str, int] = {}
    module_counts: dict[str, int] = {}
    layer_counts: dict[str, int] = {}
    entry_points: list[str] = []
    config_files: list[str] = []
    files = 0
    screens = 0
    endpoint_files = 0
    tests = 0

    for path in _walk(abs_cwd):
        rel = _normalize_rel(os.path.relpath(path, abs_cwd))
        base = os.path.basename(rel)
        ext = os.path.splitext(base)[1].lower()
        language = _language_for(path)
        files += 1
        by_language[language] = by_language.get(language, 0) + 1
        module = _module_name_for_path(rel)
        module_counts[module] = module_counts.get(module, 0) + 1
        roles = _macro_roles_for_path(rel, base, main_value, bin_values)
        for layer in _macro_layers_for_path(rel, base, language, roles):
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
        if "entrypoint" in roles:
            entry_points.append(rel)
        if "config" in roles:
            config_files.append(rel)
        if "test" in roles:
            tests += 1
        if ext in _ENDPOINT_EXTS:
            endpoint_files += 1
        if _is_macro_screen(rel, base, language):
            screens += 1

    if pkg.get("name"):
        stack = meta.get("stack") or pkg.get("type") or "node"
    elif pyproject:
        stack = meta.get("stack") or "python"
    else:
        stack = meta.get("stack") or "unknown"
    product_name = meta.get("product_name") or pkg.get("name") or os.path.basename(abs_cwd)

    modules = [
        {"name": name, "file_count": count}
        for name, count in sorted(module_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    layers = [
        {"name": name, "file_count": count}
        for name, count in sorted(layer_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {
        "schema": MACRO_MAP_SCHEMA,
        "generated_at": _now_iso(),
        "product": {
            "name": product_name,
            "stack": stack,
            "project_mode": meta.get("project_mode", "root"),
        },
        "counts": {
            "files": files,
            "by_language": dict(sorted(by_language.items())),
            "screens": screens,
            "endpoint_files": endpoint_files,
            "tests": tests,
            "modules": len(modules),
        },
        "modules": modules,
        "layers": layers,
        "entry_points": sorted(entry_points),
        "config_files": sorted(config_files),
        "git": _macro_git(abs_cwd),
        "confidence": "shallow",
    }

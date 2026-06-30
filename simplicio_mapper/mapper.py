"""Project mapper that emits the Simplicio machine-readable artifacts.

This is the Python port of ``bin/mapper-artifacts.js``. It produces
``.simplicio/project-map.json`` (schema ``simplicio.project-map/v1``) and
``.simplicio/precedent-index.json`` (schema ``simplicio.precedent-index/v1``)
as documented in ``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import orjson

from . import _native
from .cache import FileProcessingCache
from .models import CodeEntity, PrecedentItem, ProjectFile

ARTIFACT_SCHEMA = "simplicio.project-map/v1"
PRECEDENT_SCHEMA = "simplicio.precedent-index/v1"
ARCHITECTURE_INVENTORY_SCHEMA = "simplicio.architecture-inventory/v1"
SYMBOL_INDEX_SCHEMA = "simplicio.symbol-index/v1"
CALL_GRAPH_SCHEMA = "simplicio.call-graph/v1"
MACRO_MAP_SCHEMA = "simplicio.macro-map/v1"
ARTIFACT_VERSION = 1
_JSON_WRITE_OPTIONS = orjson.OPT_INDENT_2 | orjson.OPT_APPEND_NEWLINE

TEXT_EXTS = {
    ".md", ".txt", ".json", ".jsonc", ".yml", ".yaml", ".toml",
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".kt", ".php", ".rb", ".cs",
    ".cshtml", ".razor", ".sh", ".ps1", ".env", "",
    # Tier 1/2 language support
    ".dart", ".sql", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh",
    ".swift", ".m", ".mm", ".vue", ".svelte", ".scala",
    # Tier 3 niche/basic language support
    ".ex", ".exs", ".erl", ".hrl", ".lua", ".r", ".jl", ".pl", ".pm",
    ".html", ".htm", ".xhtml", ".css", ".scss", ".sass", ".less",
    ".eex", ".heex", ".leex", ".erb",
}

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "out", "output", "coverage",
    ".next", ".nuxt", "playwright-report", "test-results", ".turbo",
    ".venv", "venv", "__pycache__", ".idea", ".vscode", ".simplicio",
    ".catalog", ".receipts", ".angular", ".docusaurus", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".gradle", "obj", "target",
}

CONFIG_FILES = {
    "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "settings.gradle", "tsconfig.json",
    "vite.config.ts", "next.config.js", "angular.json", "Dockerfile",
}

LANGUAGE_BY_EXT = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".php": "php",
    ".rb": "ruby",
    ".cs": "csharp",
    ".cshtml": "razor",
    ".razor": "razor",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sh": "shell",
    ".ps1": "powershell",
    # Tier 1/2 language support
    ".dart": "dart",
    ".sql": "sql",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".swift": "swift",
    ".m": "objectivec",
    ".mm": "objectivec",
    ".vue": "vue",
    ".svelte": "svelte",
    ".scala": "scala",
    # Tier 3 niche/basic language support
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".lua": "lua",
    ".r": "r",
    ".jl": "julia",
    ".pl": "perl",
    ".pm": "perl",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "xhtml",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".eex": "html-template",
    ".heex": "html-template",
    ".leex": "html-template",
    ".erb": "html-template",
}

ENTRYPOINT_STEMS = {"index", "main", "server", "app", "program", "cli"}
TOKEN_STOPWORDS = {"src", "lib", "test", "tests", "index", "main"}

# Directive contract handed to any LLM that consumes mapper artifacts. The
# mapper has already done the survey work, so a downstream model must act
# directly — never deliberate, never reach the internet, and load only the
# tools/skills the task strictly requires.
LLM_DIRECTIVES = {
    "no_thinking": True,
    "no_internet": True,
    "tools": "only_necessary",
    "skills": "only_necessary",
    "instruction": (
        "No-thinking: act directly, do not deliberate or chain-of-think. "
        "No-internet: do not access the network. "
        "Load only strictly necessary tools. Load only strictly necessary skills."
    ),
}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def _normalize_rel(file: str) -> str:
    return file.replace(os.sep, "/")


def _read_safe(file: str) -> str:
    try:
        with open(file, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _sha256(text: str) -> str:
    if _native.HAS_NATIVE and _native.sha256_hex is not None:
        return _native.sha256_hex(text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_text(data: Any) -> str:
    return orjson.dumps(data).decode("utf-8")


def _parse_json_safe(file: str) -> dict:
    try:
        with open(file, "rb") as handle:
            return orjson.loads(handle.read() or b"{}")
    except (OSError, orjson.JSONDecodeError, TypeError):
        return {}


def _walk(root: str):
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return
    for entry in entries:
        if _should_skip_dir(entry):
            continue
        if entry.is_dir(follow_symlinks=False):
            yield from _walk(entry.path)
        elif entry.is_file(follow_symlinks=False):
            yield entry.path


def _should_skip_dir(entry: os.DirEntry[str]) -> bool:
    if entry.name in SKIP_DIRS:
        return True
    if entry.name == "bin":
        try:
            parent = os.path.dirname(entry.path)
            return any(name.endswith(".csproj") for name in os.listdir(parent))
        except OSError:
            return False
    return False


def _language_for(file: str, text: str | None = None) -> str:
    base = os.path.basename(file)
    if base == "Dockerfile":
        return "dockerfile"
    ext = os.path.splitext(file)[1].lower()
    if ext == ".m":
        if text is None:
            return "objectivec"
        probe = text
        if re.search(r"^\s*(#\s*import|@interface|@implementation|@import\b)", probe, re.MULTILINE):
            return "objectivec"
        return "matlab"
    if ext in LANGUAGE_BY_EXT:
        return LANGUAGE_BY_EXT[ext]
    return ext[1:] if ext else "text"


def _git_status_map(cwd: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return out
    if result.returncode != 0:
        return out
    for line in (result.stdout or "").split("\n"):
        if not line.strip():
            continue
        status = line[:2].strip() or "modified"
        raw = line[3:].strip()
        file = raw.split(" -> ")[-1] if " -> " in raw else raw
        out[_normalize_rel(file)] = status
    return out


def _collect_text_files(cwd: str) -> list[str]:
    files = []
    for file in _walk(cwd):
        ext = os.path.splitext(file)[1].lower()
        if ext not in TEXT_EXTS:
            continue
        try:
            if os.path.getsize(file) > 250_000:
                continue
        except OSError:
            continue
        files.append(file)
    return sorted(files)


_NATIVE_IMPORT_LANGUAGES = {"javascript", "typescript", "python", "csharp", "razor", "go"}


def _parse_imports(text: str, language: str) -> list[str]:
    # The optional Rust crate only implements the original language set; newer
    # languages always take the pure-Python path below.
    if _native.HAS_NATIVE and _native.parse_imports is not None and language in _NATIVE_IMPORT_LANGUAGES:
        return _native.parse_imports(text, language)
    patterns: list[re.Pattern[str]] = []
    if language in ("javascript", "typescript"):
        patterns.append(re.compile(r"import\s+[^'\"]*['\"]([^'\"]+)['\"]"))
        patterns.append(re.compile(r"require\(['\"]([^'\"]+)['\"]\)"))
    elif language == "python":
        patterns.append(re.compile(r"^\s*from\s+([A-Za-z0-9_.]+)\s+import\s+", re.MULTILINE))
        patterns.append(re.compile(r"^\s*import\s+([A-Za-z0-9_.]+)", re.MULTILINE))
    elif language in ("csharp", "razor"):
        patterns.append(re.compile(r"^\s*using\s+([A-Za-z0-9_.]+)\s*;", re.MULTILINE))
    elif language == "go":
        patterns.append(re.compile(r'^\s*import\s+"([^"]+)"', re.MULTILINE))
    elif language in ("vue", "svelte"):
        patterns.append(re.compile(r"import\s+[^'\"]*['\"]([^'\"]+)['\"]"))
        patterns.append(re.compile(r"require\(['\"]([^'\"]+)['\"]\)"))
    elif language == "dart":
        patterns.append(re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]", re.MULTILINE))
    elif language == "swift":
        patterns.append(re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE))
    elif language == "scala":
        patterns.append(re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE))
    elif language in ("c", "cpp"):
        patterns.append(re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE))
    elif language == "objectivec":
        patterns.append(re.compile(r'^\s*#\s*import\s+[<"]([^>"]+)[>"]', re.MULTILINE))
        patterns.append(re.compile(r"^\s*@import\s+([A-Za-z_][\w.]*)", re.MULTILINE))
    elif language == "elixir":
        patterns.append(re.compile(r"^\s*(?:alias|import|require|use)\s+([A-Z][A-Za-z0-9_.]*)", re.MULTILINE))
    elif language == "erlang":
        patterns.append(re.compile(r'^\s*-\s*include(?:_lib)?\("([^"]+)"\)', re.MULTILINE))
        patterns.append(re.compile(r"^\s*-\s*import\(([a-zA-Z0-9_@]+)\s*,", re.MULTILINE))
    elif language == "lua":
        patterns.append(re.compile(r"require\s*\(?\s*['\"]([^'\"]+)['\"]\s*\)?"))
    elif language == "r":
        patterns.append(re.compile(r"^\s*(?:library|require)\(\s*([A-Za-z][A-Za-z0-9._]*)\s*\)", re.MULTILINE))
        patterns.append(re.compile(r"^\s*source\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE))
    elif language == "julia":
        patterns.append(re.compile(r"^\s*(?:using|import)\s+([A-Za-z_][\w.]*)", re.MULTILINE))
        patterns.append(re.compile(r"^\s*include\(\s*['\"]([^'\"]+)['\"]\s*\)", re.MULTILINE))
    elif language == "perl":
        patterns.append(re.compile(r"^\s*(?:use|require)\s+([A-Za-z_][A-Za-z0-9_:]*)", re.MULTILINE))
    elif language == "matlab":
        patterns.append(re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE))
    elif language in ("css", "scss", "sass", "less"):
        patterns.append(re.compile(r"@import\s+['\"]([^'\"]+)['\"]"))
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            found.append(match.group(1))
    uniq = list(dict.fromkeys(found))
    return sorted(uniq[:20])


_SYMBOL_PATTERNS = [
    re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"\bfunction\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+(?:async\s+)?function\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bexport\s+const\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bdef\s+([A-Za-z0-9_]+)"),
    re.compile(r"\bfunc\s+([A-Za-z0-9_]+)"),
]


def _parse_symbols(text: str) -> list[str]:
    found: list[str] = []
    for pattern in _SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            found.append(match.group(1))

    # Enhanced C# / ASP.NET detection (added during EVT alignment work)
    if "Controller" in text or "[Http" in text or "[ApiController" in text:
        for m in re.finditer(r"\bclass\s+([A-Za-z0-9_]+Controller)\b", text):
            found.append(m.group(1))
        for m in re.finditer(r'\[Http(Get|Post|Put|Delete|Patch)\s*\(\s*"([^"]+)"', text):
            found.append(f"[{m.group(1)}] {m.group(2)}")
        for m in re.finditer(r'\[Route\s*\(\s*"([^"]+)"', text):
            found.append(f"[Route] {m.group(1)}")

    uniq = list(dict.fromkeys(found))
    return sorted(uniq[:40])


_RE_TEST_PATH = re.compile(r"(\b|/)(__tests__|tests?|specs?)(/|\b)", re.IGNORECASE)
_RE_TEST_FILE = re.compile(r"\.(test|spec)\.[^.]+$", re.IGNORECASE)
_RE_CONFIG = re.compile(r"config|rc$|\.config\.", re.IGNORECASE)
_RE_ROUTE = re.compile(r"routes?|controllers?|pages?|app/", re.IGNORECASE)
_RE_UI = re.compile(r"components?|views?", re.IGNORECASE)
_RE_DOMAIN = re.compile(r"services?|repositories?|models?|entities?", re.IGNORECASE)


def _roles_for(rel: str, pkg: dict) -> list[str]:
    roles: set[str] = set()
    base = os.path.basename(rel)
    no_ext = re.sub(r"\.[^.]+$", "", base).lower()
    if _RE_TEST_PATH.search(rel) or _RE_TEST_FILE.search(base):
        roles.add("test")
    if base in CONFIG_FILES or _RE_CONFIG.search(base):
        roles.add("config")
    main_value = _normalize_rel(pkg["main"]) if isinstance(pkg.get("main"), str) else ""
    bin_field = pkg.get("bin")
    if isinstance(bin_field, str):
        bin_values = [_normalize_rel(bin_field)]
    elif isinstance(bin_field, dict):
        bin_values = [_normalize_rel(v) for v in bin_field.values() if isinstance(v, str)]
    else:
        bin_values = []
    if main_value == rel or rel in bin_values or no_ext in ENTRYPOINT_STEMS:
        roles.add("entrypoint")
    if _RE_ROUTE.search(rel):
        roles.add("route")
    if _RE_UI.search(rel):
        roles.add("ui")
    if _RE_DOMAIN.search(rel):
        roles.add("domain")
    return sorted(roles)


def _importance_for(roles: list[str], imports: list[str], exports: list[str], git_status: str) -> float:
    score = 0.12
    if "entrypoint" in roles:
        score += 0.45
    if "test" in roles:
        score += 0.25
    if "config" in roles:
        score += 0.2
    if "domain" in roles:
        score += 0.2
    if imports:
        score += 0.08
    if exports:
        score += 0.08
    if git_status and git_status != "clean":
        score += 0.2
    return min(1.0, round(score, 2))


_RE_CAMEL = re.compile(r"([a-z])([A-Z])")
_RE_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _token_words(value: Any) -> list[str]:
    spaced = _RE_CAMEL.sub(r"\1 \2", str(value or ""))
    out = []
    for part in _RE_NON_ALNUM.split(spaced):
        token = part.lower()
        if len(token) > 2 and token not in TOKEN_STOPWORDS:
            out.append(token)
    return out


def _collect_entities(files: list[ProjectFile]) -> list[dict]:
    scores: dict[str, int] = {}
    for file in files:
        stem = os.path.basename(file.path)
        ext = os.path.splitext(file.path)[1]
        if ext and stem.endswith(ext):
            stem = stem[: -len(ext)]
        for token in _token_words(stem):
            scores[token] = scores.get(token, 0) + 1
        for symbol in file.exports:
            for token in _token_words(symbol):
                scores[token] = scores.get(token, 0) + 2
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [CodeEntity(name, score).to_dict() for name, score in ordered[:30]]


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


def _collect_architecture_signals(pkg: dict, corpus: str, stack: str) -> list[str]:
    text = f"{stack}\n{_json_text(pkg)}\n{corpus}".lower()
    return sorted(name for name, rx in _ARCH_CHECKS if rx.search(text))


def _brown_hilbert_address(parts: list[int]) -> str:
    """Build a Brown-Hilbert address string like ``R.0.1.2``.

    ``R`` is the root, and each element in *parts* is a numeric port at that
    tree depth.
    """
    if not parts:
        return "R"
    return "R." + ".".join(str(p) for p in parts)


def _agent_id_from_seed(seed: str) -> str:
    """8‑byte (16‑hex‑char) agent identity derived from *seed*.

    Uses ``sha256(seed)[:16]``, matching the Asolaria convention.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _build_brown_hilbert_map(files: list[ProjectFile]) -> dict[str, tuple[str, str]]:
    """Assign a Brown-Hilbert address and agent ID to every file.

    Returns ``{path: (bh_address, agent_id)}``.

    Topology
    --------
    - Module (first path segment) → ``R.<module_index>``
    - File within module → ``R.<module_index>.<file_index>``

    The agent ID is deterministically derived from the BH address, so every
    address always maps to the same agent identity.
    """
    result: dict[str, tuple[str, str]] = {}

    # Group files by module (first path component).
    modules: dict[str, list[str]] = {}
    for f in files:
        module = f.path.split("/")[0] if "/" in f.path else "."
        modules.setdefault(module, []).append(f.path)

    for mod_idx, (module, paths) in enumerate(sorted(modules.items())):
        # Module-level address R.<mod_idx>
        mod_addr = _brown_hilbert_address([mod_idx])
        mod_agent = _agent_id_from_seed(mod_addr)
        # Also register a sentinel for the module node itself
        result[f"__module__:{module}"] = (mod_addr, mod_agent)

        for file_idx, path in enumerate(sorted(paths)):
            addr = _brown_hilbert_address([mod_idx, file_idx])
            agent = _agent_id_from_seed(addr)
            result[path] = (addr, agent)

    return result


def _build_agent_tree(
    files: list[ProjectFile],
    bh_map: dict[str, tuple[str, str]],
) -> dict:
    """Build a nested Brown-Hilbert agent tree from the file inventory.

    The tree mirrors the project's module structure and annotates every node
    with its BH address, agent ID, and the resources it owns.
    """
    # Collect module nodes
    module_groups: dict[str, dict] = {}
    for f in files:
        module = f.path.split("/")[0] if "/" in f.path else "."
        if module not in module_groups:
            mod_addr, mod_agent = bh_map.get(f"__module__:{module}", ("R.0", ""))
            module_groups[module] = {
                "bh_address": mod_addr,
                "agent_id": mod_agent,
                "module": module,
                "children": [],
            }
        addr, agent = bh_map.get(f.path, ("", ""))
        module_groups[module]["children"].append({
            "bh_address": addr,
            "agent_id": agent,
            "path": f.path,
            "language": f.language,
            "roles": f.roles,
        })

    # Root node
    root_agent = _agent_id_from_seed("R")
    root_node: dict = {
        "bh_address": "R",
        "agent_id": root_agent,
        "module": ".",
        "children": [],
    }

    for module_name in sorted(module_groups):
        root_node["children"].append(module_groups[module_name])

    return root_node


def _group_modules(files: list[ProjectFile]) -> list[dict]:
    groups: dict[str, dict] = {}
    for file in files:
        first = file.path.split("/")[0] if "/" in file.path else "."
        group = groups.setdefault(first, {"name": first, "files": [], "roles": set()})
        group["files"].append(file.path)
        group["roles"].update(file.roles)
    result = []
    for group in sorted(groups.values(), key=lambda g: g["name"]):
        result.append({
            "name": group["name"],
            "files": group["files"][:20],
            "roles": sorted(group["roles"]),
            "file_count": len(group["files"]),
        })
    return result


def _detect_changed_files(files: list[ProjectFile], previous_map: dict, status_map: dict, incremental: bool) -> list[str]:
    previous = {f["path"]: f for f in previous_map.get("files", [])}
    changed = {file for file, status in status_map.items() if status != "clean"}
    if incremental:
        for file in files:
            before = previous.get(file.path)
            if not before or before.get("file_hash") != file.file_hash or before.get("size_bytes") != file.size_bytes:
                changed.add(file.path)
    present = {entry.path for entry in files}
    return sorted(file for file in changed if file in present)


def _load_previous_map(output_dir: str) -> dict:
    target = os.path.join(output_dir, "project-map.json")
    try:
        with open(target, "rb") as handle:
            return orjson.loads(handle.read() or b"{}")
    except (OSError, orjson.JSONDecodeError, TypeError):
        return {}


def _cached_parse_file(abs_path: str, rel: str, stat: os.stat_result, cache: FileProcessingCache | None) -> dict:
    cached = cache.get_processed_file(rel, stat.st_size, stat.st_mtime_ns) if cache else None
    if cached is not None:
        return cached

    text = _read_safe(abs_path)
    language = _language_for(rel, text)
    result = {
        "language": language,
        "file_hash": _sha256(text),
        "imports": _parse_imports(text, language),
        "exports": _parse_symbols(text),
        "text_preview": text[:3000],
    }
    if cache is not None:
        cache.set_processed_file(rel, stat.st_size, stat.st_mtime_ns, result)
    return result


def _build_file_inventory(
    cwd: str,
    pkg: dict,
    status_map: dict,
    cache: FileProcessingCache | None = None,
) -> list[ProjectFile]:
    inventory: list[ProjectFile] = []
    for abs_path in _collect_text_files(cwd):
        rel = _normalize_rel(os.path.relpath(abs_path, cwd))
        try:
            stat = os.stat(abs_path)
        except OSError:
            continue
        parsed = _cached_parse_file(abs_path, rel, stat, cache)
        roles = _roles_for(rel, pkg)
        imports = list(parsed.get("imports") or [])
        exports = list(parsed.get("exports") or [])
        git_status = status_map.get(rel, "clean")
        entry = ProjectFile(
            path=rel,
            language=str(parsed.get("language") or _language_for(rel)),
            size_bytes=stat.st_size,
            last_modified=_iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
            file_hash=str(parsed.get("file_hash") or ""),
            git_status=git_status,
            roles=roles,
            imports=imports,
            exports=exports,
            text_preview=str(parsed.get("text_preview") or ""),
        )
        entry.importance = _importance_for(entry.roles, entry.imports, entry.exports, entry.git_status)
        inventory.append(entry)
    inventory = sorted(inventory, key=lambda e: e.path)

    # Assign Brown-Hilbert addresses and agent IDs after sorting.
    bh_map = _build_brown_hilbert_map(inventory)
    for entry in inventory:
        addr, agent = bh_map.get(entry.path, ("", ""))
        entry.bh_address = addr
        entry.agent_id = agent

    return inventory


_RE_PLACEHOLDER = re.compile(r"<[A-Z][A-Z0-9_]+>")
_PRECEDENT_PATTERNS = [
    (re.compile(r"\btest\s*\(|\bit\s*\(|\bdescribe\s*\(|\bdef\s+test_", re.IGNORECASE), "test"),
    (re.compile(r"\bclass\s+[A-Z]|\bfunction\s+\w+|\bdef\s+\w+|\bfunc\s+\w+", re.IGNORECASE), None),
    (re.compile(r"\btry\b|\bcatch\b|\bexcept\b|\bthrow\b", re.IGNORECASE), "error-handling"),
    (re.compile(r"\brouter\.|\bapp\.get\b|\bapp\.post\b|@app\.", re.IGNORECASE), "route"),
]


def _extract_snippet(lines: list[str], line_index: int, radius: int = 2) -> str:
    start = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    return "\n".join(lines[start:end])[:1200]


def _build_precedent_items(cwd: str, files: list[ProjectFile]) -> list[dict]:
    items: list[PrecedentItem] = []
    for file in files:
        abs_path = os.path.join(cwd, file.path)
        lines = _read_safe(abs_path).split("\n")
        is_test = "test" in file.roles
        for i, line in enumerate(lines):
            change_type = None
            for rx, fixed_type in _PRECEDENT_PATTERNS:
                if rx.search(line):
                    change_type = fixed_type if fixed_type is not None else ("test" if is_test else "feature")
                    break
            if change_type is None:
                continue
            snippet = _extract_snippet(lines, i)
            if _RE_PLACEHOLDER.search(snippet):
                break
            tags = list(dict.fromkeys(
                [r for r in file.roles if r]
                + ([file.language] if file.language else [])
                + _token_words(file.path)
            ))[:10]
            items.append(PrecedentItem(
                id=_sha256(f"{file.path}:{i + 1}:{line}")[:16],
                path=file.path,
                line=i + 1,
                language=file.language,
                change_type=change_type,
                tags=tags,
                summary=f"{change_type} precedent in {file.path}",
                snippet=snippet,
            ))
            break
    items.sort(key=lambda item: (item.path, item.line))
    return [item.to_dict() for item in items[:250]]


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
            (re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+(?:[\"`]?[A-Za-z_]\w*[\"`]?\.)?[\"`]?([A-Za-z_]\w*)[\"`]?", re.IGNORECASE), "function"),
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
                    r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z0-9_<>,\[\]\s?.]+\s+([A-Za-z_]\w*)\s*\(",
                    re.MULTILINE,
                ),
                "method",
            ),
        ]
    elif file.language in {"go", "rust", "java", "kotlin", "php", "ruby"}:
        patterns = [
            (re.compile(r"\bclass\s+([A-Za-z_]\w*)"), "class"),
            (re.compile(r"\bfunction\s+([A-Za-z_]\w*)"), "function"),
            (re.compile(r"\bdef\s+([A-Za-z_]\w*)"), "function"),
        ]
    else:
        return []

    symbols = []
    seen: set[tuple[str, int, str]] = set()
    for pattern, kind in patterns:
        for match in pattern.finditer(text):
            name = match.group(1)
            line = _line_number(text, match.start())
            key = (name, line, kind)
            if key in seen:
                continue
            seen.add(key)
            symbols.append({
                "name": name,
                "qualified_name": f"{file.path}::{name}",
                "kind": kind,
                "language": file.language,
                "defined_in": file.path,
                "line": line,
                "evidence": {"file": file.path, "line": line},
            })
    return sorted(symbols, key=lambda item: (item["defined_in"], item["line"], item["name"]))


def _layers_for_file(file: ProjectFile) -> list[str]:
    rel = file.path.lower()
    base = os.path.basename(rel)
    layers = set(file.roles)
    if "controller" in rel:
        layers.add("controller")
    if "service" in rel:
        layers.add("service")
    if "repository" in rel or "repositories" in rel or "repo" in base:
        layers.add("repository")
    if "model" in rel or "entity" in rel or "schema" in rel:
        layers.add("model")
    if "route" in rel or "router" in rel:
        layers.add("route")
    if rel.startswith("scripts/"):
        layers.add("script")
    if rel.startswith("docs/") or file.language == "markdown":
        layers.add("documentation")
    if not layers:
        layers.add("code" if file.language in {"python", "javascript", "typescript", "csharp", "go", "rust", "dart", "swift", "objectivec", "c", "cpp", "scala", "vue", "svelte", "elixir", "erlang", "lua", "r", "julia", "perl", "matlab"} else "asset")
    return sorted(layers)


def _responsibility_for_file(file: ProjectFile, layers: list[str]) -> str:
    if "controller" in layers or "route" in layers:
        return "Defines inbound request or routing behavior."
    if "service" in layers:
        return "Holds application/service orchestration logic."
    if "repository" in layers:
        return "Encapsulates persistence or data access behavior."
    if "model" in layers:
        return "Defines domain, data or schema structures."
    if "test" in layers:
        return "Verifies project behavior through automated tests."
    if "entrypoint" in layers:
        return "Starts a CLI, runtime or package entrypoint."
    if "config" in layers:
        return "Configures tooling, build, runtime or packaging behavior."
    if "documentation" in layers:
        return "Documents product, architecture, operation or contributor workflow."
    if file.exports:
        return f"Defines exported symbols: {', '.join(file.exports[:5])}."
    return "Participates in the project implementation; inspect imports and symbols for exact usage."


def _module_name_for_path(rel: str) -> str:
    if "/" not in rel:
        return "."
    return rel.split("/", 1)[0]


def _build_symbol_index(cwd: str, files: list[ProjectFile], generated_at: str) -> dict:
    symbols = []
    for file in files:
        text = _read_safe(os.path.join(cwd, file.path))
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


def _candidate_import_targets(import_name: str, source_file: str, known_paths: set[str]) -> list[str]:
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

    suffix_matches = []
    normalized = _strip_known_ext(base).lstrip("/")
    for known in known_paths:
        known_base = _strip_known_ext(known)
        if known_base.endswith(f"/{normalized}") or known_base == normalized:
            suffix_matches.append(known)
    return sorted(suffix_matches)


_CALL_SKIP_NAMES = {
    "if", "for", "while", "switch", "catch", "return", "function", "class", "def",
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
}
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
        if name in _CALL_SKIP_NAMES:
            continue
        calls.append((name, _line_number(text, match.start())))
    return calls


def _nearest_symbol(symbols: list[dict], file: str, line: int) -> dict | None:
    previous = [item for item in symbols if item["defined_in"] == file and item["line"] <= line]
    if not previous:
        return None
    return sorted(previous, key=lambda item: item["line"])[-1]


def _build_call_graph(cwd: str, files: list[ProjectFile], symbol_index: dict, generated_at: str) -> dict:
    known_paths = {file.path for file in files}
    symbols = list(symbol_index.get("symbols") or [])
    symbols_by_name: dict[str, list[dict]] = {}
    for symbol in symbols:
        symbols_by_name.setdefault(symbol["name"], []).append(symbol)

    edges = []
    seen: set[tuple[str, str, str, str]] = set()

    def add_edge(edge: dict) -> None:
        key = (
            str(edge.get("type")),
            str(edge.get("source_file")),
            str(edge.get("target_file")),
            str(edge.get("target_symbol") or edge.get("import")),
        )
        if key in seen:
            return
        seen.add(key)
        edges.append(edge)

    for file in files:
        for imported in file.imports:
            targets = _candidate_import_targets(imported, file.path, known_paths)
            for target in targets[:3]:
                if target == file.path:
                    continue
                add_edge({
                    "type": "imports",
                    "source_file": file.path,
                    "target_file": target,
                    "import": imported,
                    "confidence": 0.82 if imported.startswith(".") else 0.65,
                })

        if file.language in _CALL_GRAPH_LANGUAGES:
            text = _read_safe(os.path.join(cwd, file.path))
            for name, line in _call_expressions(text):
                for target in symbols_by_name.get(name, [])[:3]:
                    if target["defined_in"] == file.path and target["line"] == line:
                        continue
                    caller = _nearest_symbol(symbols, file.path, line)
                    add_edge({
                        "type": "calls",
                        "source_file": file.path,
                        "source_symbol": caller["qualified_name"] if caller else None,
                        "target_file": target["defined_in"],
                        "target_symbol": target["qualified_name"],
                        "line": line,
                        "confidence": 0.58 if caller else 0.48,
                    })

    return {
        "schema": CALL_GRAPH_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_symbol_index": ".simplicio/symbol-index.json",
        "edges": sorted(edges, key=lambda item: (
            item.get("source_file") or "",
            item.get("target_file") or "",
            item.get("type") or "",
            item.get("target_symbol") or item.get("import") or "",
        ))[:1000],
        "counts": {
            "edges": len(edges),
            "imports": len([item for item in edges if item["type"] == "imports"]),
            "calls": len([item for item in edges if item["type"] == "calls"]),
        },
    }


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
        "relationships": list(call_graph.get("edges") or [])[:250],
        "coverage": {
            "files": len(files),
            "modules": len(module_entries),
            "layers": len(layer_entries),
            "symbols": len(symbol_index.get("symbols", []) or []),
            "relationships": len(call_graph.get("edges", []) or []),
            "tests": len(project_map.get("test_files", []) or []),
        },
        "notes": [
            "Generated from deterministic repository inspection.",
            "Relationship confidence below 1.0 means the edge is heuristic and should be reviewed before making broad claims.",
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
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return {"head": "", "dirty": False}
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        if rev.returncode == 0:
            head = rev.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd, capture_output=True, text=True, timeout=3,
        )
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return {"head": head, "dirty": dirty}
    return {"head": head, "dirty": dirty}


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


def build_artifacts(cwd: str, meta: dict | None = None, incremental: bool = False,
                    output_dir: str = ".simplicio") -> dict:
    meta = meta or {}
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    pkg = _parse_json_safe(os.path.join(abs_cwd, "package.json"))
    status_map = _git_status_map(abs_cwd)
    previous_map = _load_previous_map(abs_out)
    cache_dir = os.path.join(abs_out, "cache")
    with FileProcessingCache(cache_dir) as file_cache:
        files = _build_file_inventory(abs_cwd, pkg, status_map, file_cache)
    file_entries = [file.to_dict() for file in files]
    corpus = "\n".join(file.text_preview for file in files[:80])
    changed_files = _detect_changed_files(files, previous_map, status_map, incremental)
    stack = meta.get("stack") or pkg.get("type") or "unknown"
    product_name = meta.get("product_name") or pkg.get("name") or os.path.basename(abs_cwd)
    architecture_signals = _collect_architecture_signals(pkg, corpus, stack)
    generated_at = _now_iso()

    if os.path.exists(os.path.join(abs_cwd, "pnpm-lock.yaml")):
        package_manager = "pnpm"
    elif os.path.exists(os.path.join(abs_cwd, "yarn.lock")):
        package_manager = "yarn"
    else:
        package_manager = "npm"

    web_signal = "react" in architecture_signals or "nextjs" in architecture_signals
    if meta.get("project_mode") == "monorepo":
        system_type = "monorepo"
    else:
        system_type = "web" if web_signal else "library-or-service"

    project_map = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "update_mode": "incremental" if incremental else "full",
        "product": {
            "name": product_name,
            "stack": stack,
            "project_mode": meta.get("project_mode", "root"),
        },
        "files": file_entries,
        "entry_points": [f.path for f in files if "entrypoint" in f.roles],
        "test_files": [f.path for f in files if "test" in f.roles],
        "config_files": [f.path for f in files if "config" in f.roles],
        "modules": _group_modules(files),
        "entities": _collect_entities(files),
        "architecture": {
            "signals": architecture_signals,
            "system_type": system_type,
        },
        "dependencies": {
            "package_manager": package_manager,
            "manifest": "package.json" if pkg.get("name") else None,
            "runtime": sorted((pkg.get("dependencies") or {}).keys()),
            "dev": sorted((pkg.get("devDependencies") or {}).keys()),
        },
        "recent_changes": [
            {"path": file, "status": status_map.get(file, "modified")} for file in changed_files
        ],
        "changed_files": changed_files,
        "integration": {
            "dev_cli_mapper": "read .simplicio/project-map.json, then use .simplicio/precedent-index.json for task-specific examples",
            "contract": "SIMPLICIO_INTEGRATION.md",
            "llm_directives": LLM_DIRECTIVES,
        },
    }

    precedent_index = {
        "schema": PRECEDENT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_project_map": ".simplicio/project-map.json",
        "items": _build_precedent_items(abs_cwd, files),
    }

    symbol_index = _build_symbol_index(abs_cwd, files, generated_at)
    call_graph = _build_call_graph(abs_cwd, files, symbol_index, generated_at)
    architecture_inventory = _build_architecture_inventory(
        abs_cwd,
        project_map,
        files,
        symbol_index,
        call_graph,
        generated_at,
    )

    # Build agent tree from Brown-Hilbert map
    bh_map = _build_brown_hilbert_map(files)
    agent_tree = _build_agent_tree(files, bh_map)

    project_map["agent_tree"] = agent_tree

    return {
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
    }


def _write_json_stable(file: str, data: Any) -> None:
    directory = os.path.dirname(file)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{file}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(data, option=_JSON_WRITE_OPTIONS))
    os.replace(tmp, file)


def write_mapping_artifacts(cwd: str, meta: dict | None = None, incremental: bool = False,
                            output_dir: str = ".simplicio",
                            log: Callable[[str], None] | None = None) -> dict:
    log = log or (lambda _line: None)
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    artifacts = build_artifacts(abs_cwd, meta, incremental, output_dir)
    project_map = artifacts["project_map"]
    precedent_index = artifacts["precedent_index"]
    architecture_inventory = artifacts["architecture_inventory"]
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    project_map_path = os.path.join(abs_out, "project-map.json")
    precedent_path = os.path.join(abs_out, "precedent-index.json")
    architecture_inventory_path = os.path.join(abs_out, "architecture-inventory.json")
    symbol_index_path = os.path.join(abs_out, "symbol-index.json")
    call_graph_path = os.path.join(abs_out, "call-graph.json")
    _write_json_stable(project_map_path, project_map)
    _write_json_stable(precedent_path, precedent_index)
    _write_json_stable(architecture_inventory_path, architecture_inventory)
    _write_json_stable(symbol_index_path, symbol_index)
    _write_json_stable(call_graph_path, call_graph)
    log(f"-> wrote {os.path.relpath(project_map_path, abs_cwd)} "
        f"({len(project_map['files'])} files, {len(project_map['changed_files'])} changed)")
    log(f"-> wrote {os.path.relpath(precedent_path, abs_cwd)} "
        f"({len(precedent_index['items'])} precedents)")
    log(f"-> wrote {os.path.relpath(architecture_inventory_path, abs_cwd)} "
        f"({architecture_inventory['coverage']['modules']} modules, {architecture_inventory['coverage']['layers']} layers)")
    log(f"-> wrote {os.path.relpath(symbol_index_path, abs_cwd)} "
        f"({symbol_index['counts']['symbols']} symbols)")
    log(f"-> wrote {os.path.relpath(call_graph_path, abs_cwd)} "
        f"({call_graph['counts']['edges']} relationships)")
    return {
        "project_map_path": project_map_path,
        "precedent_path": precedent_path,
        "architecture_inventory_path": architecture_inventory_path,
        "symbol_index_path": symbol_index_path,
        "call_graph_path": call_graph_path,
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
    }


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if str(value).startswith(".") and slug:
        return f"dot-{slug}"
    return slug or "root"


def _write_text_stable(file: str, text: str) -> None:
    os.makedirs(os.path.dirname(file), exist_ok=True)
    tmp = f"{file}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")
    os.replace(tmp, file)


def _file_ref(path: str, line: int | None = None) -> str:
    suffix = f":{line}" if line else ""
    return f"`{path}{suffix}`"


def _render_architecture_overview(inventory: dict, symbol_index: dict, call_graph: dict) -> str:
    product = inventory.get("product", {})
    coverage = inventory.get("coverage", {})
    modules = inventory.get("modules", [])
    layers = inventory.get("layers", [])
    lines = [
        f"# {product.get('name') or 'Project'} Architecture Inventory",
        "",
        "Generated from `.simplicio` machine-readable artifacts. Statements below are derived from repository structure, imports, symbols and deterministic heuristics.",
        "",
        "## Coverage",
        "",
        f"- Files: {coverage.get('files', 0)}",
        f"- Modules: {coverage.get('modules', 0)}",
        f"- Layers: {coverage.get('layers', 0)}",
        f"- Symbols: {coverage.get('symbols', 0)}",
        f"- Relationships: {coverage.get('relationships', 0)}",
        f"- Tests: {coverage.get('tests', 0)}",
        "",
        "## Modules",
        "",
    ]
    for module in modules[:40]:
        lines.append(
            f"- `{module['name']}`: {module['file_count']} files; layers: "
            f"{', '.join(module.get('layers') or ['none'])}"
        )
    lines.extend(["", "## Layers", ""])
    for layer in layers:
        lines.append(f"- `{layer['name']}`: {layer['file_count']} files across {len(layer.get('modules', []))} modules")

    graph_edges = [
        edge for edge in call_graph.get("edges", [])
        if edge.get("type") == "imports" and edge.get("source_file") and edge.get("target_file")
    ][:20]
    if graph_edges:
        lines.extend(["", "## Dependency Sketch", "", "```mermaid", "graph LR"])
        for edge in graph_edges:
            source = _slugify(edge["source_file"])
            target = _slugify(edge["target_file"])
            lines.append(f'  {source}["{edge["source_file"]}"] --> {target}["{edge["target_file"]}"]')
        lines.append("```")

    if symbol_index.get("symbols"):
        lines.extend(["", "## Top Symbols", ""])
        for symbol in symbol_index["symbols"][:40]:
            lines.append(
                f"- `{symbol['name']}` ({symbol['kind']}) in "
                f"{_file_ref(symbol['defined_in'], symbol.get('line'))}"
            )
    return "\n".join(lines)


def _render_layers_doc(inventory: dict) -> str:
    lines = ["# Architecture Layers", ""]
    for layer in inventory.get("layers", []):
        lines.extend([
            f"## {layer['name']}",
            "",
            f"- Files: {layer['file_count']}",
            f"- Modules: {', '.join(layer.get('modules') or ['none'])}",
            "",
        ])
        for file in layer.get("files", [])[:60]:
            lines.append(f"- {_file_ref(file)}")
        lines.append("")
    return "\n".join(lines)


def _render_call_graph_doc(call_graph: dict) -> str:
    lines = [
        "# Call Graph",
        "",
        "Edges are deterministic or heuristic. Review `confidence` before using a relationship as proof.",
        "",
        "## Relationships",
        "",
    ]
    for edge in call_graph.get("edges", [])[:300]:
        if edge.get("type") == "imports":
            lines.append(
                f"- imports: {_file_ref(edge['source_file'])} -> {_file_ref(edge['target_file'])} "
                f"(confidence {edge['confidence']})"
            )
        else:
            target = edge.get("target_symbol") or edge.get("target_file")
            line = edge.get("line")
            lines.append(
                f"- calls: {_file_ref(edge['source_file'], line)} -> `{target}` "
                f"(confidence {edge['confidence']})"
            )
    return "\n".join(lines)


def _render_module_doc(module: dict, inventory: dict) -> str:
    files_by_path = {item["path"]: item for item in inventory.get("files", [])}
    lines = [
        f"# Module: {module['name']}",
        "",
        module.get("summary") or "Module summary unavailable.",
        "",
        "## Structure",
        "",
        f"- Files: {module['file_count']}",
        f"- Layers: {', '.join(module.get('layers') or ['none'])}",
        f"- Entry points: {', '.join(_file_ref(path) for path in module.get('entry_points', [])) or 'none detected'}",
        f"- Tests: {', '.join(_file_ref(path) for path in module.get('tests', [])) or 'none detected'}",
        "",
        "## Files",
        "",
    ]
    for path in module.get("files", [])[:120]:
        file_entry = files_by_path.get(path, {})
        summary = file_entry.get("summary", "No summary available.")
        layers = ", ".join(file_entry.get("layers") or [])
        lines.append(f"- {_file_ref(path)}: {summary} Layers: {layers or 'none'}")
    if module.get("public_symbols"):
        lines.extend(["", "## Public Symbols", ""])
        for symbol in module["public_symbols"][:80]:
            lines.append(f"- `{symbol}`")
    return "\n".join(lines)


def write_architecture_docs(cwd: str, output_dir: str = ".simplicio",
                            docs_dir: str | None = None) -> dict:
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    inventory_path = os.path.join(abs_out, "architecture-inventory.json")
    if not os.path.exists(inventory_path):
        write_mapping_artifacts(abs_cwd, output_dir=output_dir)

    inventory = _parse_json_safe(inventory_path)
    symbol_index = _parse_json_safe(os.path.join(abs_out, "symbol-index.json"))
    call_graph = _parse_json_safe(os.path.join(abs_out, "call-graph.json"))
    root = os.path.abspath(docs_dir or os.path.join(abs_out, "docs"))
    modules_dir = os.path.join(root, "modules")
    paths = []

    docs = {
        os.path.join(root, "architecture.md"): _render_architecture_overview(inventory, symbol_index, call_graph),
        os.path.join(root, "layers.md"): _render_layers_doc(inventory),
        os.path.join(root, "call-graph.md"): _render_call_graph_doc(call_graph),
    }
    module_index = ["# Modules", ""]
    for module in inventory.get("modules", []):
        module_file = os.path.join(modules_dir, f"{_slugify(module['name'])}.md")
        docs[module_file] = _render_module_doc(module, inventory)
        module_index.append(f"- [{module['name']}](modules/{_slugify(module['name'])}.md)")
    docs[os.path.join(root, "modules.md")] = "\n".join(module_index)

    # Local import avoids a module-level cycle (cli imports mapper at import time).
    from .cli import build_service_flowchart, render_service_flowchart_markdown
    flowchart_model = build_service_flowchart(abs_cwd)
    docs[os.path.join(root, "flowchart.md")] = render_service_flowchart_markdown(flowchart_model)

    for file, text in docs.items():
        _write_text_stable(file, text)
        paths.append(file)

    return {
        "docs_root": root,
        "paths": sorted(paths),
        "counts": {
            "files": len(paths),
            "modules": len(inventory.get("modules", []) or []),
        },
    }


def export_architecture_docs(cwd: str, target_dir: str, output_dir: str = ".simplicio") -> dict:
    if not target_dir:
        raise ValueError("--target is required for export-docs")
    docs = write_architecture_docs(cwd, output_dir=output_dir)
    source = docs["docs_root"]
    target = os.path.abspath(target_dir)
    os.makedirs(target, exist_ok=True)
    copied = []
    for current, _dirs, files in os.walk(source):
        for name in files:
            if not name.endswith(".md"):
                continue
            src = os.path.join(current, name)
            rel = os.path.relpath(src, source)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = f"{dst}.tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            copied.append(dst)
    return {
        "target": target,
        "paths": sorted(copied),
        "counts": {"files": len(copied)},
    }

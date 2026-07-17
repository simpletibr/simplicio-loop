"""Discovery and read layer of the project mapper: filesystem walk,
text/import/symbol regex parsing, per-file role/importance tagging,
and precedent-snippet extraction. Split from the former monolithic
``mapper.py`` (issue #159) -- pure move, no behavior change. See
``simplicio_mapper/mapper/__init__.py`` for the re-exported public API.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any

import orjson

from .. import _native
from ..cache import FileProcessingCache
from ..models import CodeEntity, PrecedentItem, ProjectFile

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

def _content_for(cwd: str, rel: str, contents: dict[str, str] | None = None) -> str:
    if contents is not None and rel in contents:
        return contents[rel]
    text = _read_safe(os.path.join(cwd, rel))
    if contents is not None:
        contents[rel] = text
    return text

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

def _is_internal_worktree_dir(parent: str, name: str) -> bool:
    """True when ``name`` is a nested worktree container directory (e.g.
    ``.claude/worktrees/<agent>/...``) that duplicates the primary checkout
    and must be excluded from the mapped file universe (issue #234).

    Scoped narrowly to ``worktrees`` directories living directly under a
    ``.claude`` directory so legitimate root-level configuration --
    ``.claude/settings.json``, ``.claude/skills/*.md`` -- is never touched.
    Symlinks/junctions are handled by the caller's ``follow_symlinks=False``,
    not here.
    """
    if name != "worktrees":
        return False
    # Normalize separators explicitly (rather than os.path.basename, which
    # is platform-dependent) so the check behaves identically regardless of
    # which OS produced `parent` -- tests exercise both "/" and "\\" forms.
    normalized = parent.replace("\\", "/").rstrip("/")
    parent_name = normalized.rsplit("/", 1)[-1] if normalized else ""
    return parent_name == ".claude"

def _should_skip_dir(entry: os.DirEntry[str]) -> bool:
    if entry.name in SKIP_DIRS:
        return True
    if _is_internal_worktree_dir(os.path.dirname(entry.path), entry.name):
        return True
    if entry.name == "bin":
        try:
            parent = os.path.dirname(entry.path)
            return any(name.endswith(".csproj") for name in os.listdir(parent))
        except OSError:
            return False
    if entry.name == "worktrees" and os.path.basename(os.path.dirname(entry.path)) == ".claude":
        # Nested worktrees under .claude/worktrees/<name>/ are full checkouts
        # of an agent's own working copy, not project source (issue #234).
        # Skipping the "worktrees" directory itself (rather than ".claude")
        # keeps legitimate root config like .claude/settings.json and
        # .claude/skills/*.md in scope.
        return True
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

def _git_status_map(cwd: str, degraded: dict[str, Any] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=3,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        if degraded is not None:
            degraded["git_timeout"] = True
        return out
    except (OSError, subprocess.SubprocessError):
        if degraded is not None:
            degraded["git_status_unavailable"] = True
        return out
    if result.returncode != 0:
        if degraded is not None:
            degraded["git_status_unavailable"] = True
        return out
    for line in (result.stdout or "").split("\n"):
        if not line.strip():
            continue
        status = line[:2].strip() or "modified"
        raw = line[3:].strip()
        file = raw.split(" -> ")[-1] if " -> " in raw else raw
        out[_normalize_rel(file)] = status
    return out

def _collect_text_files(cwd: str, skipped: list[str] | None = None) -> list[str]:
    files = []
    for file in _walk(cwd):
        ext = os.path.splitext(file)[1].lower()
        if ext not in TEXT_EXTS:
            continue
        try:
            if os.path.getsize(file) > 250_000:
                if skipped is not None:
                    skipped.append(_normalize_rel(os.path.relpath(file, cwd)))
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
    elif language == "rust":
        patterns.append(re.compile(r"^\s*use\s+([^;]+);", re.MULTILINE))
        patterns.append(re.compile(r"^\s*extern\s+crate\s+([A-Za-z_][\w]*)", re.MULTILINE))
    elif language == "java":
        patterns.append(re.compile(r"^\s*import\s+(?:static\s+)?([A-Za-z_][\w.*]*)\s*;", re.MULTILINE))
    elif language == "kotlin":
        patterns.append(re.compile(r"^\s*import\s+([A-Za-z_][\w.*]*)", re.MULTILINE))
    elif language == "php":
        patterns.append(re.compile(r"^\s*use\s+([A-Za-z_\\][A-Za-z0-9_\\]*)\s*;", re.MULTILINE))
        patterns.append(
            re.compile(
                r"^\s*(?:require|require_once|include|include_once)\s*\(?\s*['\"]([^'\"]+)['\"]\s*\)?",
                re.MULTILINE,
            )
        )
    elif language == "ruby":
        patterns.append(re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.MULTILINE))
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

def _cached_parse_file(
    cwd: str,
    abs_path: str,
    rel: str,
    stat: os.stat_result,
    cache: FileProcessingCache | None,
    contents: dict[str, str] | None = None,
) -> dict:
    cached = cache.get_processed_file(rel, stat.st_size, stat.st_mtime_ns) if cache else None
    if cached is not None:
        if contents is not None and rel not in contents:
            contents[rel] = _content_for(cwd, rel, contents)
        return cached

    text = _content_for(cwd, rel, contents)
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
    contents: dict[str, str] | None = None,
    skipped_large_files: list[str] | None = None,
) -> list[ProjectFile]:
    inventory: list[ProjectFile] = []
    for abs_path in _collect_text_files(cwd, skipped=skipped_large_files):
        rel = _normalize_rel(os.path.relpath(abs_path, cwd))
        try:
            stat = os.stat(abs_path)
        except OSError:
            continue
        parsed = _cached_parse_file(cwd, abs_path, rel, stat, cache, contents=contents)
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

def _build_precedent_items(
    cwd: str,
    files: list[ProjectFile],
    contents: dict[str, str] | None = None,
    per_file_limit: int = 3,
    max_items: int = 250,
) -> list[dict]:
    grouped: list[tuple[ProjectFile, list[PrecedentItem]]] = []
    for file in sorted(files, key=lambda item: (-item.importance, item.path)):
        lines = _content_for(cwd, file.path, contents).split("\n")
        is_test = "test" in file.roles
        file_items: list[PrecedentItem] = []
        used_lines: list[int] = []
        for i, line in enumerate(lines):
            change_type = None
            for rx, fixed_type in _PRECEDENT_PATTERNS:
                if rx.search(line):
                    change_type = fixed_type if fixed_type is not None else ("test" if is_test else "feature")
                    break
            if change_type is None:
                continue
            if any(abs(i - used) < 5 for used in used_lines):
                continue
            snippet = _extract_snippet(lines, i)
            if _RE_PLACEHOLDER.search(snippet):
                continue
            tags = list(dict.fromkeys(
                [r for r in file.roles if r]
                + ([file.language] if file.language else [])
                + _token_words(file.path)
            ))[:10]
            file_items.append(PrecedentItem(
                id=_sha256(f"{file.path}:{i + 1}:{line}")[:16],
                path=file.path,
                line=i + 1,
                language=file.language,
                change_type=change_type,
                tags=tags,
                summary=f"{change_type} precedent in {file.path}",
                snippet=snippet,
                rank=len(file_items) + 1,
            ))
            used_lines.append(i)
            if len(file_items) >= per_file_limit:
                break
        if file_items:
            grouped.append((file, file_items))

    items: list[PrecedentItem] = []
    for rank in range(per_file_limit):
        for _file, file_items in grouped:
            if rank < len(file_items):
                items.append(file_items[rank])
                if len(items) >= max_items:
                    return [item.to_dict() for item in items]
    return [item.to_dict() for item in items]

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

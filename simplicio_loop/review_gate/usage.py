"""Check that new public symbols are referenced outside tests."""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Collection, Mapping, Sequence

from .diffs import FileChange, kind_of
from .model import CheckResult, ERROR, FAIL, PASS, SKIPPED

SKIP_DIRS = frozenset({".git", ".simplicio-loop", "venv", ".venv", "node_modules", "__pycache__", ".pytest_cache",
                       ".mypy_cache", "build", "dist"})
CONFIG_SUFFIXES = (".toml", ".cfg", ".ini", ".yml", ".yaml", ".json")
NON_PRODUCTION_DIRS = frozenset({"tests", "test", "docs"})
NO_IMPORTER_NEEDED = ("__init__.py", "__main__.py")
# these decorators only change how a definition behaves; any other one registers it somewhere (route, command, fixture)
NEUTRAL_DECORATORS = frozenset({"property", "staticmethod", "classmethod", "cached_property", "setter", "getter", "deleter",
                                "overload", "abstractmethod", "dataclass", "wraps", "lru_cache", "cache", "final"})


@dataclass(frozen=True)
class Symbol:
    """A public definition: module level, or the body of a public class (then `owner` is that class's (name, line))."""
    name: str
    lineno: int
    span: tuple[int, int]  # first to last line of the definition
    owner: tuple[str, int] | None = None
    registered: bool = False  # a decorator hands it to a framework, so nobody has to call it

    @property
    def label(self) -> str:
        return f"{self.owner[0]}.{self.name}" if self.owner else self.name

    @property
    def what(self) -> str:
        return "membro" if self.owner else "simbolo"


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := _dotted(node.value)):
        return f"{base}.{node.attr}"
    return None


def _registered(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", ()):
        dotted = _dotted(decorator.func if isinstance(decorator, ast.Call) else decorator)
        if dotted is None or not (dotted.rpartition(".")[2] in NEUTRAL_DECORATORS or dotted.startswith("functools.")):
            return True
    return False


def _collect(body: Sequence[ast.AST], owner: tuple[str, int] | None, found: list[Symbol]) -> None:
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names, span = [t.id for t in targets if isinstance(t, ast.Name)], (node.lineno, node.end_lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):  # never into a function's body
            names, span = [node.name], (node.lineno, node.end_lineno)
        else:  # if / try / with / for ...: what they hold is still module (or class) level
            inner = [c for c in ast.iter_child_nodes(node) if isinstance(c, (ast.stmt, ast.excepthandler, ast.match_case))]
            _collect(inner, owner, found)
            continue
        found.extend(Symbol(n, node.lineno, span, owner, _registered(node)) for n in names if not n.startswith("_"))
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            _collect(node.body, (node.name, node.lineno), found)


def public_names(source: str) -> dict[str, int]:
    """Public symbol -> line (1-indexed): module-level and class-body definitions, never locals of a function.

    Raises SyntaxError if the source is invalid."""
    found: list[Symbol] = []
    _collect(ast.parse(source).body, None, found)
    return {s.name: s.lineno for s in found}


@dataclass
class FileRefs:
    """What one production file imports, names and cites."""
    rel: str
    module: str  # dotted path of the file, as an import would spell it
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[tuple[str, str]] = field(default_factory=list)  # (module, name) of `from module import name`
    modules: list[tuple[str, str]] = field(default_factory=list)  # (spelling here, dotted module) of what may hold a module
    attrs: list[tuple[int, str, str | None]] = field(default_factory=list)  # (line, attribute, dotted base)
    keywords: list[tuple[int, str]] = field(default_factory=list)
    names: list[tuple[int, str]] = field(default_factory=list)  # names read
    strings: list[tuple[int, str]] = field(default_factory=list)  # string constants, but docstrings and `__all__`


def _scan(rel: str, source: str) -> FileRefs:
    tree = ast.parse(source)
    parts = PurePosixPath(rel).with_suffix("").parts
    package = parts[:-1]
    refs = FileRefs(rel, ".".join(package if parts[-1] == "__init__" else parts))
    _collect(tree.body, None, refs.symbols)
    skip: set[int] = set()  # string constants that are docstrings or part of an `__all__` say nothing about use
    for node in ast.walk(tree):  # parents come before their children
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                skip.add(id(node.body[0].value))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                skip.update(id(c) for c in ast.walk(node) if isinstance(c, ast.Constant))
        elif isinstance(node, ast.ImportFrom):
            kept = package[:max(len(package) - node.level + 1, 0)] if node.level else ()
            base = ".".join([*kept, *(node.module.split(".") if node.module else ())])
            for alias in node.names:
                refs.imports.append((base, alias.name))
                refs.modules.append((alias.asname or alias.name, f"{base}.{alias.name}" if base else alias.name))
        elif isinstance(node, ast.Import):
            refs.modules.extend((alias.asname or alias.name, alias.name) for alias in node.names)
        elif isinstance(node, ast.Attribute):
            refs.attrs.append((node.lineno, node.attr, _dotted(node.value)))
        elif isinstance(node, ast.keyword) and node.arg:
            refs.keywords.append((node.lineno, node.arg))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            refs.names.append((node.lineno, node.id))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            refs.strings.append((node.lineno, node.value))
    return refs


def _same_module(imported: str, module: str) -> bool:
    """`imported` is how an import spells a module; src layouts and scripts dirs leave a prefix, so a dotted suffix counts."""
    return module == imported or module.endswith("." + imported)


def _refers(refs: FileRefs, module: str, symbol: Symbol, spans: Sequence[tuple[int, int]], local: bool) -> bool:
    """Does this file use `symbol` of `module`? `spans` are the lines of its own definitions, which never count."""
    name = symbol.name

    def outside(line: int) -> bool:
        return not any(first <= line <= last for first, last in spans)

    if any(outside(n) and (text == name or text.endswith((f":{name}", f".{name}"))) for n, text in refs.strings):
        return True  # entry points, getattr, plugin tables
    if symbol.owner:  # a member is reached as `obj.member`, or by keyword when it is a field
        return (any(outside(n) and attr == name for n, attr, _ in refs.attrs)
                or any(outside(n) and key == name for n, key in refs.keywords))
    if local:
        return (any(outside(n) and read == name for n, read in refs.names)
                or any(outside(n) and attr == name for n, attr, _ in refs.attrs))
    if any(_same_module(imported, module) and imported_name == name for imported, imported_name in refs.imports):
        return True
    spelled = {text for text, dotted in refs.modules if _same_module(dotted, module)}
    return any(attr == name and base in spelled for _, attr, base in refs.attrs)


class RefIndex:
    """The production python files under `root` that mention a needle, parsed once, and its config files.

    Any reference to a symbol or a module spells its name, so a file without every needle cannot refer to it and is not
    parsed. `homes` are the changed files, already scanned. Paths are relative to `root`."""

    def __init__(self, root: Path, needles: Collection[str], homes: Mapping[str, FileRefs]):
        self.files: dict[str, FileRefs] = dict(homes)
        self._config_paths: list[Path] = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]  # judged below `root`: `root` itself may sit in `.simplicio-loop`
            where = Path(folder).relative_to(root).as_posix()
            for name in names:
                rel = name if where == "." else f"{where}/{name}"
                if name.endswith(".py") and kind_of(rel) == "code":
                    try:
                        text = (root / rel).read_text(encoding="utf-8")
                        if any(needle in text for needle in needles):
                            self.files[rel] = _scan(rel, text)
                    except (OSError, SyntaxError, ValueError):
                        continue
                elif name.endswith(CONFIG_SUFFIXES) and not NON_PRODUCTION_DIRS.intersection(rel.split("/")[:-1]):
                    self._config_paths.append(root / rel)

    @cached_property
    def _configs(self) -> list[str]:
        texts = []
        for path in self._config_paths:
            try:
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        return texts

    def has_importer(self, rel: str) -> bool:
        module = self.files[rel].module
        return any(other.rel != rel and (any(_same_module(m, module) for m, _ in other.imports)
                                         or any(_same_module(dotted, module) for _, dotted in other.modules))
                   for other in self.files.values())

    def is_used(self, rel: str, symbol: Symbol) -> bool:
        if symbol.registered:
            return True
        home = self.files[rel]
        own = [s.span for s in home.symbols if s.name == symbol.name]
        if any(_refers(refs, home.module, symbol, own if refs is home else [], refs is home) for refs in self.files.values()):
            return True
        word = re.compile(rf"(?<!\w){re.escape(symbol.name)}(?!\w)")
        return any(word.search(text) for text in self._configs)


def check_usage(
    root: Path,
    changes: Sequence[FileChange],
    base_public: Mapping[str, frozenset[str]],
) -> CheckResult:
    """Verify new public symbols have references outside tests.

    Args:
        root: Repository root (HEAD). It may itself sit inside `.simplicio-loop/review-gate/...`.
        changes: File changes from the PR.
        base_public: Mapping of path -> public symbols in the base branch.
    """
    code_changes = [c for c in changes if c.kind == "code"]
    if not code_changes:
        return CheckResult("usage", SKIPPED, ("sem codigo de producao alterado",))

    entries: list[tuple[FileChange, FileRefs, list[Symbol]]] = []
    for change in code_changes:
        try:
            source = (root / change.path).read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            if change.status == "D":
                continue  # deleted files are OK
            return CheckResult("usage", ERROR, (f"nao conseguiu ler {change.path}",))
        except (OSError, UnicodeDecodeError) as exc:
            return CheckResult("usage", ERROR, (f"erro ao ler {change.path}: {exc}",))
        try:
            home = _scan(change.path, source)
        except SyntaxError as exc:
            return CheckResult("usage", ERROR, (f"SyntaxError em {change.path}: {exc}",))
        known = base_public.get(change.path, frozenset())
        entries.append((change, home, [s for s in home.symbols if change.status == "A" or (s.name not in known and s.lineno in change.added)]))

    def new_module(change: FileChange) -> bool:
        return change.status == "A" and PurePosixPath(change.path).name not in NO_IMPORTER_NEEDED

    def judged(fresh: list[Symbol]) -> list[Symbol]:
        classes = {(s.name, s.lineno) for s in fresh}
        return [s for s in fresh if s.owner not in classes]  # a new class stands for its members

    needles = {s.name for _, _, fresh in entries for s in judged(fresh)}
    needles.update(PurePosixPath(c.path).stem for c, h, _ in entries if new_module(c) and not h.symbols)
    index = RefIndex(root, needles, {c.path: h for c, h, _ in entries})
    reasons: list[str] = []
    unused: list[str] = []
    new_symbols = new_modules = 0
    for change, home, fresh in entries:
        new_symbols += len(fresh)
        if new_module(change):
            new_modules += 1
            if not home.symbols and not index.has_importer(change.path):
                unused.append(change.path)
                reasons.append(f"modulo novo `{change.path}` sem importador")
        for symbol in judged(fresh):
            if not index.is_used(change.path, symbol):
                unused.append(f"{change.path}:{symbol.label}")
                reasons.append(f"{symbol.what} novo `{symbol.label}` ({change.path}:{symbol.lineno}) sem chamador fora dos testes")

    measured = {"new_symbols": new_symbols, "new_modules": new_modules, "unused": unused}
    if reasons:
        return CheckResult("usage", FAIL, tuple(reasons), measured)
    return CheckResult("usage", PASS, measured=measured)

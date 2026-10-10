"""Check that a PR covers the criteria (`- [ ]`) of its issue, and fail a partial PR that does not say so.

A criterion is COVERED when the diff gives evidence for it; the first rule that holds wins, and the evidence
(`test:<file>::<name>`, `code:<file>`, `docs:<file>`, `path:<token>`, `symbol:<token>`) goes in `measured`.

 (b) It cites paths or symbols, and every cited one shows up in the diff. Cited = between backticks, a bare file
     with a known extension (with or without directories), a snake_case / CamelCase identifier, or `name()`.
     A path must be a changed file (or a directory that contains one); a symbol must be a whole word in the added
     lines of a changed file, or the name of a changed file.
 (d) It only asks for tests ("add tests") and the PR adds or changes a test file.
 (a) At least 50% of its content words (and at least 2, when it has 2 or more) are found TOGETHER in ONE unit:
       - a new/changed test: its name and body (a test file without `def test_*` in the added lines counts as one);
       - a changed production file (`code`/`other`): its path and the definition lines it adds (`def`, `class`,
         `function`, `fn`, `const`, top-level `NAME =` ..., name and signature, never the bodies);
       - a changed doc: its path and its added text.
     Words never add up across units, so a generic criterion is not covered by "a little of everything".
A test is a unit only when it runs and can fail (`vacuity.py`): a test with no assert, with only constant true asserts
(`assert True`), with a `pass` body or with a skip / xfail marker is no evidence, whatever its name says. Its words are those
of its name, docstring, identifiers and strings (comments are not).

Content words: lowercase, accents removed, split on `_`, `-`, digits and camelCase, 3+ letters, without Portuguese
or English stopwords and generic verbs ("add", "criar", "deve"...); a trailing plural "s" is dropped. Two words
match when equal, or when both have 5+ letters and share a prefix of at least max(5, shorter - 2) letters
("authentication"/"authenticate", "limita"/"limit"; not "report"/"repository"). Words about tests ("test",
"teste", "testar"...) are not content: a criterion that has them can only be covered by tests (rule (d), or (a)/(b)
against test files alone). A criterion with no content word and no test word cannot be verified: not covered.

The PR may leave criteria uncovered only as "Parte de #N" (this issue) with a "Falta:" list that has one `- [ ]`
item per uncovered criterion, and without a closing keyword for the issue (that would close it on merge). The items
are matched by identity: each uncovered criterion needs an item of its own that holds its text or enough of its words
("item 1" or an empty item names nothing). Production that is not Python (js, sh, yml, toml: kind `other`) is never
evidence, because red/green and mutation do not read it.

Documentation is evidence only for a documentation criterion: one that names docs, ADR, README, CHANGELOG or documentation
(`documentar`, `documentation`...), or cites a documentation file. A criterion that asks for behavior is not covered by a doc.
`no_evidence` (a failed check, whatever the issue says): the PR changes non-Python production (`.sh`, `.js`, `.yml`, `.toml`...)
and no usable test, or it changes no test and no Python production and a criterion stays uncovered. (An empty diff is `empty_diff`,
rejected by `gate.run_gate` before any check.)
"""
from __future__ import annotations

import math
import re
import textwrap
import unicodedata
from pathlib import PurePosixPath
from typing import Collection, Mapping, Sequence

from . import vacuity
from .diffs import FileChange, is_pytest_infra
from .model import CheckResult, PASS, FAIL, SKIPPED

_STOPWORDS_PT = frozenset("""
    a ao aos as ate com como da das de dele deles dela delas depois do dos e ela elas ele eles em entre essa essas
    esse esses esta estas este estes isso isto la mais mas mesmo na nas nem no nos nao num numa o os ou para pela
    pelas pelo pelos por qual quais quando que quem se sem seu seus sua suas sao tambem tem um uma uns umas ser
    sobre ja so alem cada ainda onde dentro fora apos antes durante
""".split())
_STOPWORDS_EN = frozenset("""
    a about after all also an and any are as at be been before but by can did do does for from had has have how if
    in into is it its may more most no nor not of on or other our out over same should so some such than that the
    their them then there these they this those to too under until up very was we were what when where which while
    who why will with would you your
""".split())
_GENERIC_VERBS = frozenset("""
    add added adding adicionar adiciona adicionado adicionada allow allows permitir permite ensure ensures garantir
    garante implement implements implemented implementar implementa implementado implementada create creates created
    criar cria criado criada make makes fazer faz write writes escrever escreve deve devem dever deveria must need
    needs precisa precisam ter tenha haver existir exist exists usar use uses used suportar support supports
    update updates atualizar atualiza
""".split())
_TEST_WORDS = frozenset("test tests teste testes testar testa testado testada tested testing cobertura coverage".split())
_STOP = _STOPWORDS_PT | _STOPWORDS_EN | _GENERIC_VERBS | _TEST_WORDS

_EXT = r"(?:py|pyi|md|rst|txt|json|toml|ya?ml|cfg|ini|sql|sh|js|jsx|ts|tsx|html|css|go|rs|rb|java|kt|php|cs)"
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_BARE_TOKEN = re.compile(
    r"(?<![\w`/.-])(?:"
    r"(?:[\w.\-]+/)*[\w\-]+\.%s\b"  # a file with a known extension, with or without directories
    r"|[a-z][a-z0-9]*(?:_[a-z0-9]+)+"  # snake_case
    r"|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+"  # CamelCase
    r"|[A-Za-z_]\w*\(\)"  # name()
    r")(?![\w`])" % _EXT
)
_PATH_END = re.compile(r"\.%s$" % _EXT)
_DEF_LINE = re.compile(
    r"^\s*(?:export\s+(?:default\s+)?)?(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
    r"(?:def|class|function|fn|func|struct|enum|trait|interface|type|const|let|var)\s+(?P<rest>.+)$"
)
_ASSIGN_LINE = re.compile(r"^(?P<rest>[A-Za-z_]\w*)\s*(?::[^=\n]+)?=(?!=)")  # top-level only: no indentation
_TEST_DEF = re.compile(r"^[ \t]*(?:async[ \t]+)?def[ \t]+(test\w*)[ \t]*\(", re.M)
_PARTE_DE = re.compile(r"Parte\s+de\s+(?:[\w.\-]+/[\w.\-]+)?#(\d+)", re.I)
_CLOSING = re.compile(
    r"\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved|fecha|fechar|fechado|resolvido|resolvida)"
    r"\s*:?\s+(?:[\w.\-]+/[\w.\-]+)?#(\d+)",
    re.I,
)
_EVIDENCE_CAP = 5
_DOC_CRITERION = re.compile(r"\b(?:docs?|adrs?|readme|changelog|documentation|documenta\w*|document(?:ed|ing)?)\b", re.I)
_DOC_SUFFIXES = (".md", ".rst", ".txt", ".toon")
# Non-Python production, which the gate cannot run. The pytest configuration (`pyproject.toml`, `tox.ini`...) is T2 and not listed here.
_OTHER_CODE_SUFFIXES = frozenset(
    ".sh .bash .zsh .js .jsx .mjs .cjs .ts .tsx .yml .yaml .toml .go .rs .rb .java .kt .php .cs .c .cc .cpp .h .hpp .sql"
    " .json .lock .csv .tsv .ndjson .xml".split())  # the last row: generated or data-only files, which prove nothing


def criteria(issue_body: str) -> list[str]:
    """The unchecked criteria of an issue body: the text after `- [ ]` (also `*`/`+` bullets and `1.`)."""
    result = []
    for line in issue_body.splitlines():
        if match := re.match(r"^\s*(?:[-*+]|\d+[.)])\s*\[\s*\]\s*(.+)$", line):
            result.append(match.group(1).strip())
    return result


def closes(pr_body: str, issue: int) -> bool:
    """Whether the PR body has a closing keyword for `issue` (the thing that closes it on merge).

    Recognizes close/closes/closed, fix/fixes/fixed, resolve/resolves/resolved and PT-BR fecha/fechar/fechado,
    resolvido/resolvida (any case, whole word), with `#N` or `owner/repo#N`. "Parte de #N" is not a keyword.
    Any occurrence counts: "closes #5, closes #123" closes 123, and a "Parte de" next to it does not undo it.
    """
    return any(int(m.group(1)) == issue for m in _CLOSING.finditer(pr_body))


def _partial_of(pr_body: str, issue: int) -> bool:
    return any(int(m.group(1)) == issue for m in _PARTE_DE.finditer(pr_body))


def check_coverage(
    issue: int | None,
    issue_body: str,
    changes: Sequence[FileChange],
    added_text: Mapping[str, str],
    pr_body: str,
    sources: Mapping[str, str] | None = None,
) -> CheckResult:
    """Verify PR coverage matches issue criteria.

    Args:
        issue: Issue number, or None if no issue.
        issue_body: Body of the issue.
        changes: File changes from the PR.
        added_text: Mapping of path -> text of added lines.
        pr_body: Body of the PR.
        sources: Mapping of path -> whole text (at head) of the test files; the gate passes it so a test is judged by its own
            function. Without it a test is judged by the added lines.

    Returns:
        CheckResult with status PASS/FAIL/SKIPPED.
    """
    units = _Evidence(changes, added_text, sources)
    other = units.other_without_test()
    if other:
        return CheckResult("coverage", FAIL, (
            "no_evidence: producao que nao e Python sem teste que rode e possa falhar (o portao nao le nem roda): " + ", ".join(other[:5]),
        ), {"reason_code": "no_evidence", "other": other})

    if issue is None:
        return CheckResult("coverage", SKIPPED, ("PR sem issue",))

    crit = criteria(issue_body)
    if not crit:
        return CheckResult("coverage", SKIPPED, ("issue sem criterios",))

    evidence: dict[str, list[str]] = {}
    uncovered: list[str] = []
    for text in crit:
        found = units.for_criterion(text)
        if found:
            evidence[text] = found
        else:
            uncovered.append(text)
    measured = {
        "criteria": len(crit),
        "covered": len(crit) - len(uncovered),
        "uncovered": uncovered,
        "partial": False,
        "evidence": evidence,
    }
    if not uncovered:
        return CheckResult("coverage", PASS, measured=measured)

    reasons = tuple(f"criterio sem cobertura: {text}" for text in uncovered)
    if not units.runs_something():
        reasons = ("no_evidence: o PR nao altera teste nem codigo Python; so teste que roda e passa, ou codigo, prova um comportamento",
                   *reasons)
        measured["reason_code"] = "no_evidence"
    elif not units.has_production() and any(not _asks_for_test(text) for text in uncovered):
        reasons = ("no_evidence: o PR so altera testes, nenhum codigo Python de producao; um teste sozinho passa no head sem que o PR "
                   "implemente nada e so prova um criterio que pede teste", *reasons)
        measured["reason_code"] = "no_evidence"
    if closes(pr_body, issue):
        return CheckResult("coverage", FAIL, (
            "PR parcial sem 'Parte de #' ou com palavra de fechamento",
            *reasons,
        ), measured=measured)
    if not _partial_of(pr_body, issue):
        return CheckResult("coverage", FAIL, reasons, measured=measured)

    falta_match = re.search(r"(?:Falta|Faltando|Pendente|Pendentes|Missing)\s*:\s*(.*?)(?=\n\n|\Z)", pr_body,
                            re.IGNORECASE | re.DOTALL)
    if not falta_match:
        return CheckResult("coverage", FAIL, ("PR parcial sem lista do que falta", *reasons), measured=measured)
    falta_items = re.findall(r"^\s*[-*+]\s*\[\s*\][ \t]*(.*)$", falta_match.group(1), re.MULTILINE)
    if len(falta_items) < len(uncovered):
        return CheckResult("coverage", FAIL, (
            f"lista 'Falta' tem {len(falta_items)} items mas ha {len(uncovered)} criterios descobertos",
            *reasons,
        ), measured=measured)
    ambiguous = _ambiguous(uncovered, falta_items)
    if ambiguous:  # an item names ONE criterion: the own words of several of them in one item name none
        return CheckResult("coverage", FAIL, tuple(f"lista 'Falta': item names several criteria (ambiguous): {text}" for text in ambiguous),
                           measured=measured)
    unnamed = _unnamed(uncovered, falta_items)
    if unnamed:  # by identity, not by count: "item 1", "item 2" or empty items name nothing
        return CheckResult("coverage", FAIL, tuple(f"lista 'Falta' nao nomeia o criterio: {text}" for text in unnamed), measured=measured)
    return CheckResult("coverage", PASS, measured={**measured, "partial": True})


def _squash(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", _strip_accents(text).lower()))


def _names(item: str, criterion: str, distinct: Collection[str] = ()) -> bool:
    """Whether a Falta item is about this criterion: it holds its text, or enough of its content words together, and, when
    the criterion has words no other uncovered criterion uses (`distinct`), at least one of those: the words every
    criterion shares ("report", "gate", "check") name the topic of the issue, not this criterion."""
    if not _squash(item):
        return False
    if _squash(criterion) in _squash(item):
        return True
    words = sorted(set(_words(criterion)))
    pool = set(_words(item))
    return bool(words) and _hits(words, pool) >= _needed(len(words)) and (not distinct or _hits(sorted(distinct), pool) >= 1)


def _distinctive(criterion: str, others: Sequence[str]) -> set[str]:
    """Content words of `criterion` that none of the `others` has."""
    rest = {w for other in others for w in _words(other)}
    return {w for w in _words(criterion) if not any(_same(w, r) for r in rest)}


def _ambiguous(uncovered: Sequence[str], items: Sequence[str]) -> list[str]:
    """The items that name more than one uncovered criterion by its own words. A criterion with no word of its own cannot be
    told apart, so it never makes an item ambiguous."""
    distinct = [_distinctive(c, [*uncovered[:n], *uncovered[n + 1:]]) for n, c in enumerate(uncovered)]
    return [item for item in items
            if sum(1 for c, own in zip(uncovered, distinct) if own and _names(item, c, own)) > 1]


def _unnamed(uncovered: Sequence[str], items: Sequence[str]) -> list[str]:
    """The uncovered criteria that no item of its own names (an item stands for one criterion at most)."""
    free, missing = list(items), []
    for n, criterion in enumerate(uncovered):
        distinct = _distinctive(criterion, [*uncovered[:n], *uncovered[n + 1:]])
        match = next((i for i, item in enumerate(free) if _names(item, criterion, distinct)), None)
        if match is None:
            missing.append(criterion)
        else:
            del free[match]
    return missing


# --- words ------------------------------------------------------------------------------------------------------


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _words(text: str) -> list[str]:
    """Content words of `text` (see the module docstring), in order, repeated words kept."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", _strip_accents(text))  # camelCase -> camel Case
    out = []
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) < 3 or word in _STOP:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 5:
        return False
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common >= max(5, shorter - 2)


def _hits(words: Sequence[str], pool: set[str]) -> int:
    return sum(1 for w in words if any(_same(w, p) for p in pool))


def _needed(n: int) -> int:
    """Content words of a criterion that must be found together in one unit."""
    return 1 if n <= 1 else max(2, math.ceil(n / 2))


# --- evidence ---------------------------------------------------------------------------------------------------


def _is_conftest(path: str) -> bool:
    return PurePosixPath(path).name == "conftest.py"


def _definition_words(text: str) -> list[str]:
    """Words of the definition lines (name and signature) among the added lines of a production file."""
    out: list[str] = []
    for line in text.splitlines():
        match = _DEF_LINE.match(line) or _ASSIGN_LINE.match(line)
        if match:
            out.extend(_words(match.group("rest")))
    return out


def _test_units(path: str, text: str, added: Collection[int], source: str | None) -> list[tuple[str, str, bool]]:
    """(label, words text, usable) of each test the PR adds or changes. `usable` is False for a test that cannot fail or that
    nobody runs (`vacuity.py`). With the whole file (`source`) a test is one function that overlaps an added line; without it
    the added lines are parsed alone, and when they do not parse, the text is split at each `def test*` (all usable: nothing to judge)."""
    if source is not None:
        try:
            funcs = [f for f in vacuity.analyze(source) if set(added).intersection(range(f.first, f.last + 1))]
        except SyntaxError:
            funcs = None
        if funcs is not None:
            return [(f"{path}::{f.qualname}", f.terms, f.usable) for f in funcs]
    try:
        alone = textwrap.dedent(text)
        funcs = vacuity.analyze(alone)
        if funcs:
            return [(f"{path}::{f.qualname}", f.terms, f.usable) for f in funcs]
        return [(path, text, vacuity.has_check(alone))]  # lines of an existing test: no `def test*` among them
    except SyntaxError:
        pass
    found = list(_TEST_DEF.finditer(text))
    if not found:
        return [(path, text, True)]
    ends = [m.start() for m in found[1:]] + [len(text)]
    return [(f"{path}::{m.group(1)}", text[m.start():end], True) for m, end in zip(found, ends)]


def _cited_tokens(criterion: str) -> list[str]:
    tokens = [t.strip() for t in _BACKTICKED.findall(criterion)]
    tokens.extend(m.group(0) for m in _BARE_TOKEN.finditer(_BACKTICKED.sub(" ", criterion)))
    return [t for t in tokens if t]


def _is_doc_criterion(criterion: str, cited: Sequence[str]) -> bool:
    """Whether the criterion asks for documentation: it names docs / ADR / README / documentation, or cites a doc file."""
    return bool(_DOC_CRITERION.search(_strip_accents(criterion))) or any(t.lower().endswith(_DOC_SUFFIXES) for t in cited)


def _is_path(token: str) -> bool:
    return "/" in token or bool(_PATH_END.search(token))


def _path_matches(token: str, path: str) -> bool:
    if token.endswith("/"):  # a directory that contains a changed file
        return path.startswith(token) or f"/{token}" in f"/{path}"
    return path == token or path.endswith("/" + token)


def _asks_for_test(criterion: str) -> bool:
    """Whether the criterion itself asks for a test (teste, testar, test, cobertura, coverage...)."""
    return any(w in _TEST_WORDS for w in re.findall(r"[a-z]+", _strip_accents(criterion).lower()))


class _Evidence:
    """The units of a PR (tests, production files, docs) that a criterion can be matched against."""

    def __init__(self, changes: Sequence[FileChange], added_text: Mapping[str, str], sources: Mapping[str, str] | None = None) -> None:
        self.changes = list(changes)
        self.added = dict(added_text)
        self.tests: list[tuple[str, set[str]]] = []  # (label, words) of the tests that run and can fail
        self.code: list[tuple[str, set[str]]] = []
        self.docs: list[tuple[str, set[str]]] = []
        self.test_files: list[str] = []  # test files with at least one usable test
        for ch in self.changes:
            if ch.status == "D":
                continue
            text = self.added.get(ch.path, "")
            path_words = set(_words(ch.path))
            if ch.kind == "test":
                if _is_conftest(ch.path) or is_pytest_infra(ch.path) or not text.strip():
                    continue
                units = [u for u in _test_units(ch.path, text, ch.added, (sources or {}).get(ch.path)) if u[2]]
                if units:
                    self.test_files.append(ch.path)
                    self.tests.extend((f"test:{label}", set(_words(body))) for label, body, _ in units)
            elif ch.kind == "docs":
                self.docs.append((f"docs:{ch.path}", path_words | set(_words(text))))
            elif ch.kind == "code":  # production that is not Python (js, sh, yml, toml) is no evidence: nothing here reads it
                self.code.append((f"code:{ch.path}", path_words | set(_definition_words(text))))

    def for_criterion(self, criterion: str) -> list[str]:
        """Evidence labels for the criterion; empty when it is not covered."""
        needs_test = _asks_for_test(criterion)
        cited = _cited_tokens(criterion)
        # documentation is evidence of a documentation criterion only; a test file with no usable test is not evidence of anything
        docs_ok = _is_doc_criterion(criterion, cited)
        # a test is evidence of a behavior criterion only next to Python production: tests alone run green on the head, they
        # do not show that the PR implements anything (`assert callable(add)` passes on a PR that adds nothing)
        tests_ok = needs_test or self.has_production()
        scope = [c for c in self.changes if c.kind == "test" and c.path in self.test_files] if needs_test \
            else [c for c in self.changes if c.kind == "code" or (tests_ok and c.path in self.test_files) or (docs_ok and c.kind == "docs")]
        if cited and all(self._in_diff(tok, scope) for tok in cited):
            return [f"{'path' if _is_path(tok) else 'symbol'}:{tok}" for tok in cited][:_EVIDENCE_CAP]
        prose = criterion
        for tok in cited:
            if _is_path(tok):  # path fragments ("src", "py") are not content words
                prose = prose.replace(tok, " ")
        words = sorted(set(_words(prose)))
        if not words:
            return [f"test:{p}" for p in self.test_files][:_EVIDENCE_CAP] if needs_test else []
        need = _needed(len(words))
        units = self.tests if needs_test else [*(self.tests if tests_ok else []), *self.code, *(self.docs if docs_ok else [])]
        return [label for label, pool in units if _hits(words, pool) >= need][:_EVIDENCE_CAP]

    def has_production(self) -> bool:
        """Whether the PR adds or changes Python production."""
        return any(c.kind == "code" and c.status in ("A", "M") for c in self.changes)

    def runs_something(self) -> bool:
        """Whether the PR changes a usable test or Python production (docs and non-Python files prove no behavior)."""
        return bool(self.test_files) or self.has_production()

    def other_without_test(self) -> list[str]:
        """Non-Python production the PR adds or changes when it has no usable test: nothing in the gate runs or reads it."""
        if self.test_files:
            return []
        return sorted(c.path for c in self.changes if c.kind == "other" and c.status in ("A", "M") and not is_pytest_infra(c.path)
                      and PurePosixPath(c.path).suffix.lower() in _OTHER_CODE_SUFFIXES)

    def _in_diff(self, token: str, scope: Sequence[FileChange]) -> bool:
        tok = token.strip("\"'").removesuffix("()").removeprefix("./")
        if not tok:
            return False
        if _is_path(tok):
            return any(_path_matches(tok, ch.path) for ch in scope)
        name = tok.rsplit(".", 1)[-1]
        if len(name) < 3:
            return False
        if any(name == PurePosixPath(ch.path).stem for ch in scope):
            return True
        word = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])")
        return any(word.search(self.added.get(ch.path, "")) for ch in scope)

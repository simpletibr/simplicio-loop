"""Regex-only goal scope classifier for ``simplicio-py run``.

The classifier is intentionally small and deterministic.  It gives the future
``simplicio-py run --scope auto`` entrypoint enough structure to decide whether a
goal should use the existing task pipeline, scratch scaffolder, or a higher
level orchestrator once feature and sprint modes are wired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCOPES = ("task", "feature", "sprint", "scratch")
AUTO_CONFIDENCE_THRESHOLD = 0.70

_FILE_RE = re.compile(
    r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|vue|svelte|go|rs|java|kt|cs|cpp|cc|h|hpp|"
    r"rb|php|swift|dart|sql|md|yml|yaml|json|toml|sh|html|css|scss)\b",
    re.IGNORECASE,
)
_ISSUE_RE = re.compile(r"(?:#\d+|\bissues?\s+\d+\b)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9_./#-]+", re.IGNORECASE)

_READ_ONLY_CUES = (
    "what does",
    "explain",
    "how does",
    "why does",
    "what is",
    "show me",
    "list ",
    "o que faz",
    "explique",
    "como funciona",
    "por que",
    "o que e",
    "o que eh",
)

_TASK_VERBS = (
    "add",
    "remove",
    "delete",
    "rename",
    "refactor",
    "fix",
    "patch",
    "update",
    "change",
    "replace",
    "hide",
    "show",
    "validate",
    "implement",
    "wire",
    "extract",
    "split",
    "rewrite",
    "tweak",
    "adjust",
    "introduce",
    "map",
    "inventory",
    "align",
    "document",
    "improve",
    "corrija",
    "corrigir",
    "adicione",
    "adicionar",
    "remova",
    "remover",
    "renomeie",
    "renomear",
    "atualize",
    "atualizar",
    "altere",
    "alterar",
    "ajuste",
    "ajustar",
    "crie",
    "criar",
    "veja",
    "ver",
    "alinhe",
    "alinhar",
    "mapeie",
    "mapear",
    "documente",
    "documentar",
    "melhore",
    "melhorar",
)
_TASK_NOUNS = (
    "component",
    "endpoint",
    "route",
    "handler",
    "service",
    "controller",
    "middleware",
    "guard",
    "model",
    "schema",
    "migration",
    "fixture",
    "test",
    "spec",
    "validator",
    "selector",
    "store",
    "hook",
    "function",
    "method",
    "class",
    "button",
    "form",
    "input",
    "page",
    "componente",
    "funcao",
    "classe",
    "tela",
    "rota",
    "campo",
    "botao",
    "formulario",
)
_NARROW_CUES = ("only", "just", "single", "one file", "apenas", "somente", "so ", "um arquivo")
_TEST_CUES = ("test", "spec", "pytest", "jest", "vitest", "teste")

_FEATURE_VERBS = (
    "build",
    "implement",
    "create",
    "ship",
    "develop",
    "deliver",
    "add",
    "desenvolva",
    "desenvolver",
    "construa",
    "construir",
    "implemente",
    "implementar",
    "entregue",
)
_FEATURE_NOUNS = (
    "login",
    "jwt",
    "logout",
    "auth",
    "feature",
    "flow",
    "workflow",
    "billing",
    "checkout",
    "payment",
    "crud",
    "dashboard",
    "reports",
    "module",
    "frontend",
    "backend",
    "full stack",
    "end-to-end",
    "end to end",
    "funcionalidade",
    "fluxo",
    "pagamento",
    "relatorios",
)
_BROAD_CUES = (
    "across",
    "multiple files",
    "front and back",
    "frontend and backend",
    "whole flow",
    "full flow",
    "end-to-end",
    "end to end",
    "varios arquivos",
    "varios modulos",
)
_REAL_STACK_EVIDENCE_CUES = {
    "browser": ("playwright", "e2e"),
    "ui": ("web", "frontend", "telas", "screens", "interface", "browser"),
    "api": ("api", "backend", "azure functions", ".net"),
    "database": ("postgres", "postgresql", "database", "banco", "db"),
}

_SPRINT_CUES = (
    "sprint",
    "milestone",
    "release",
    "roadmap",
    "epic",
    "backlog",
    "dod",
    "definition of done",
    ".specs/sprints",
    "all issues",
    "all tasks",
    "all endpoints",
    "all screens",
    "every issue",
    "entire repo",
    "cross-repo",
    "todas as issues",
    "todos os issues",
    "todas as tarefas",
    "todos os endpoints",
    "todas as telas",
    "todos os projetos",
    "remaining endpoints",
    "remaining routes",
    "missing endpoints",
    "missing routes",
    "endpoints restantes",
    "rotas restantes",
    "lacunas restantes",
    "endpoints faltantes",
    "rotas faltantes",
    "lacunas faltantes",
)
_FINISH_CUES = ("finish", "close", "complete", "ship", "terminar", "fechar", "concluir", "finalizar")

_SCRATCH_CUES = (
    "from scratch",
    "greenfield",
    "new project",
    "new app",
    "new application",
    "new repo",
    "new repository",
    "scaffold",
    "bootstrap",
    "starter",
    "repo novo",
    "novo projeto",
    "nova app",
    "novo app",
    "aplicacao nova",
)
_STACK_CUES = (
    "fastapi",
    "django",
    "flask",
    "react",
    "nextjs",
    "next.js",
    "vue",
    "svelte",
    "angular",
    "node",
    "express",
    "rails",
    "ktor",
    "android",
    "cli",
)
_PROJECT_NOUNS = ("project", "app", "application", "repo", "service", "api", "projeto", "aplicacao")


@dataclass
class IntentResult:
    scope: str
    confidence: float
    signals: list[str]


def classify_goal(text: str, explicit_scope: str | None = None) -> IntentResult:
    """Classify a user goal into a ``simplicio-py run`` execution scope."""

    scope = (explicit_scope or "auto").strip().lower()
    if scope != "auto":
        if scope not in SCOPES:
            raise ValueError(f"invalid scope: {explicit_scope}")
        return IntentResult(scope, 1.0, [f"explicit_scope:{scope}"])

    if not text or not text.strip():
        return IntentResult("task", 0.0, [])

    lower = _fold(text)
    read_only = _first_phrase(lower, _READ_ONLY_CUES)
    if read_only:
        return IntentResult("task", 0.20, [f"read_only:{read_only}"])

    scores = {name: 0 for name in SCOPES}
    signals: list[str] = []

    files = _FILE_RE.findall(text)
    unique_files = list(dict.fromkeys(files))
    if unique_files:
        for path in unique_files[:3]:
            signals.append(f"file:{path}")
        if len(unique_files) == 1:
            scores["task"] += 4
        else:
            scores["task"] += 2
            scores["feature"] += 2
            signals.append("feature:multiple_files")

    verb = _first_token(lower, _TASK_VERBS)
    if verb:
        scores["task"] += 2
        signals.append(f"verb:{verb}")

    noun = _first_phrase(lower, _TASK_NOUNS)
    if noun:
        scores["task"] += 1
        signals.append(f"noun:{noun}")

    narrow = _first_phrase(lower, _NARROW_CUES)
    if narrow:
        scores["task"] += 1
        signals.append(f"narrow:{narrow.strip()}")

    test = _first_phrase(lower, _TEST_CUES)
    if test:
        scores["task"] += 1
        signals.append(f"test:{test}")

    feature_verb = _first_token(lower, _FEATURE_VERBS)
    if feature_verb:
        scores["feature"] += 2
        signals.append(f"feature_verb:{feature_verb}")

    feature_noun = _first_phrase(lower, _FEATURE_NOUNS)
    if feature_noun:
        scores["feature"] += 2
        signals.append(f"feature:{feature_noun}")

    broad = _first_phrase(lower, _BROAD_CUES)
    if broad:
        scores["feature"] += 2
        signals.append(f"broad:{broad}")

    if _looks_like_real_stack_evidence(lower):
        scores["feature"] += 5
        signals.append("feature:real_stack_evidence")

    if not unique_files and (feature_verb or feature_noun):
        scores["feature"] += 1
        signals.append("feature:no_target_file")

    sprint = _first_phrase(lower, _SPRINT_CUES)
    if sprint:
        scores["sprint"] += 4
        signals.append(f"sprint:{sprint}")

    if any(
        phrase in lower
        for phrase in (
            "todos os endpoints",
            "todas as telas",
            "todos os projetos",
            "all endpoints",
            "all screens",
            "web com api",
            "api e ai-agents",
        )
    ):
        scores["sprint"] += 2
        signals.append("sprint:full_inventory")

    if any(
        phrase in lower
        for phrase in (
            "remaining endpoints",
            "remaining routes",
            "missing endpoints",
            "missing routes",
            "endpoints restantes",
            "rotas restantes",
            "lacunas restantes",
            "endpoints faltantes",
            "rotas faltantes",
            "lacunas faltantes",
        )
    ):
        scores["sprint"] += 5
        signals.append("sprint:remaining_endpoint_inventory")

    issue_refs = _ISSUE_RE.findall(text)
    if len(issue_refs) >= 3:
        scores["sprint"] += 3
        signals.append(f"sprint:issue_refs:{len(issue_refs)}")

    finish = _first_token(lower, _FINISH_CUES)
    if finish and (sprint or len(issue_refs) >= 2):
        scores["sprint"] += 2
        signals.append(f"finish:{finish}")

    scratch = _first_phrase(lower, _SCRATCH_CUES)
    if scratch:
        scores["scratch"] += 4
        signals.append(f"scratch:{scratch}")

    stack = _first_phrase(lower, _STACK_CUES)
    if stack:
        scores["scratch"] += 1
        signals.append(f"stack:{stack}")

    project = _first_phrase(lower, _PROJECT_NOUNS)
    if project and scratch:
        scores["scratch"] += 1
        signals.append(f"project:{project}")

    scope = _choose_scope(scores, unique_files, broad is not None)
    confidence = _confidence(scope, scores)
    return IntentResult(scope, confidence, signals)


def _choose_scope(scores: dict[str, int], files: list[str], has_broad_cue: bool) -> str:
    if len(files) == 1 and not has_broad_cue and scores["task"] >= 5:
        return "task"
    if len(files) > 1 and scores["feature"] >= scores["task"]:
        return "feature"

    order = {"sprint": 0, "scratch": 1, "task": 2, "feature": 3}
    return sorted(SCOPES, key=lambda name: (-scores[name], order[name]))[0]


def _confidence(scope: str, scores: dict[str, int]) -> float:
    score = scores[scope]
    if score <= 0:
        return 0.0

    thresholds = {"task": 5, "feature": 4, "sprint": 5, "scratch": 5}
    threshold = thresholds[scope]
    if score < threshold:
        return round(min(0.69, score / threshold * 0.65), 2)

    other_scores = [value for name, value in scores.items() if name != scope]
    margin = score - max(other_scores, default=0)
    return round(min(0.98, 0.70 + (score - threshold) * 0.05 + margin * 0.03), 2)


def _fold(text: str) -> str:
    return (
        text.lower()
        .replace("é", "e")
        .replace("ê", "e")
        .replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _first_token(text: str, words: tuple[str, ...]) -> str | None:
    tokens = set(_TOKEN_RE.findall(text))
    return next((word for word in words if word in tokens), None)


def _first_phrase(text: str, phrases: tuple[str, ...]) -> str | None:
    return next((phrase for phrase in phrases if phrase in text), None)


def _looks_like_real_stack_evidence(text: str) -> bool:
    return all(any(cue in text for cue in cues) for cues in _REAL_STACK_EVIDENCE_CUES.values())

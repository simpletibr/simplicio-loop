"""detect.py — heuristic: is this prompt a small/medium code-edit task?

Used by the UserPromptSubmit hook (.claude/hooks/simplicio-userpromptsubmit.sh)
to print a PROMPT_HINT when the user asks for a code edit, nudging the agent to
invoke the simplicio-cli skill instead of editing by hand.

No LLM call. Pure regex/keyword. Cheap to run on every prompt.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from .intent import classify_goal

_EDIT_VERBS = (
    # English
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
    "inject",
    "extract",
    "split",
    "rewrite",
    "tweak",
    "adjust",
    "introduce",
    "expose",
    "map",
    "inventory",
    "align",
    "document",
    "improve",
    "use",
    "run",
    "execute",
    "connect",
    "test",
    "prove",
    "evidence",
    # Portuguese
    "adicione",
    "adicionar",
    "remova",
    "remover",
    "renomeie",
    "renomear",
    "corrija",
    "corrigir",
    "atualize",
    "atualizar",
    "altere",
    "alterar",
    "esconda",
    "esconder",
    "mostre",
    "mostrar",
    "valide",
    "validar",
    "implemente",
    "implementar",
    "troque",
    "trocar",
    "ajuste",
    "ajustar",
    "ocultar",
    "exiba",
    "exibir",
    "criar",
    "crie",
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
    "use",
    "usar",
    "rode",
    "rodar",
    "execute",
    "executar",
    "teste",
    "testar",
    "conecte",
    "conectar",
    "prove",
    "provar",
    "evidencie",
    "evidenciar",
)

_FILE_EXT_RE = re.compile(
    r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|vue|svelte|go|rs|java|kt|cs|cpp|cc|h|hpp|"
    r"rb|php|swift|dart|sql|md|yml|yaml|json|toml|sh|html|css|scss)\b",
    re.IGNORECASE,
)

_CODE_NOUNS = (
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
    "reducer",
    "action",
    "hook",
    "directive",
    "pipe",
    "module",
    "function",
    "method",
    "class",
    "prop",
    "field",
    "column",
    "button",
    "form",
    "input",
    "dropdown",
    "modal",
    "page",
    "api",
    "apis",
    "database",
    "postgres",
    "postgresql",
    "playwright",
    "e2e",
    "componente",
    "função",
    "funcao",
    "classe",
    "tela",
    "rota",
    "campo",
    "botão",
    "botao",
    "formulário",
    "formulario",
    "banco",
    "dados",
)

_NEGATIVE_CUES = (
    "what does",
    "explain",
    "how does",
    "why does",
    "what is",
    "o que faz",
    "explique",
    "como funciona",
    "por que",
    "o que é",
    "show me the",
    "list ",
    "list the",
)


@dataclass
class DetectResult:
    is_code_task: bool
    score: int
    signals: list
    hint: str
    scope: str = "task"


def detect(prompt: str) -> DetectResult:
    if not prompt or not prompt.strip():
        return DetectResult(False, 0, [], "")

    lower = prompt.lower()
    signals: list = []
    score = 0

    for cue in _NEGATIVE_CUES:
        if lower.startswith(cue) or f" {cue} " in lower:
            return DetectResult(False, 0, [f"negative_cue:{cue!r}"], "")

    tokens = re.findall(r"[a-záàâãéêíóôõúç]+", lower)
    verbs = [t for t in tokens if t in _EDIT_VERBS]
    if verbs:
        score += 2
        signals.append(f"verb:{verbs[0]}")

    file_match = _FILE_EXT_RE.search(prompt)
    if file_match:
        score += 2
        signals.append(f"file:{file_match.group(0)}")

    nouns = [n for n in _CODE_NOUNS if n in lower]
    if nouns:
        score += 1
        signals.append(f"noun:{nouns[0]}")

    if any(
        s in lower for s in ("$simplicio", "/simplicio", "use simplicio", "rode o simplicio", "via simplicio")
    ):
        score += 5
        signals.append("explicit_invocation")

    intent = classify_goal(prompt)
    if intent.scope in {"feature", "sprint"} and intent.confidence >= 0.70:
        score += 2
        for signal in intent.signals:
            if signal.startswith(("feature:", "sprint:")) and signal not in signals:
                signals.append(signal)

    is_code = score >= 3
    hint = _render_hint(prompt, signals, intent.scope) if is_code else ""
    return DetectResult(is_code, score, signals, hint, intent.scope)


def _render_hint(prompt: str, signals: list, scope: str = "task") -> str:
    target_hint = next((s.split(":", 1)[1] for s in signals if s.startswith("file:")), None)
    target_line = f"target = {target_hint}" if target_hint else "target = <ask user or infer via Explore>"
    if scope == "sprint":
        scale_line = (
            "This prompt looks like sprint-scale code work. Use `simplicio-py run --scope sprint`\n"
            "or a local sprint plan before editing by hand, then verify each slice."
        )
    elif scope == "feature":
        scale_line = (
            "This prompt looks like feature-scale code work. Use `simplicio-py run --scope feature`\n"
            "or a focused local plan before editing by hand, then verify the full flow."
        )
    else:
        scale_line = (
            "This prompt looks like a small/medium code edit. Before editing by hand,\n"
            "invoke the simplicio-cli skill (it stacks precedent + skill-router + 6-layer\n"
            "prompt + test + verify-loop and measurably boosts pass-rate)."
        )
    return (
        "[SIMPLICIO_PROMPT_HINT]\n"
        f"{scale_line}\n"
        f"  goal = {prompt.strip()[:120]}\n"
        f"  {target_line}\n"
        f"  scope = {scope}\n"
        f"  signals = {', '.join(signals)}\n"
        "[/SIMPLICIO_PROMPT_HINT]"
    )


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="simplicio-py detect")
    ap.add_argument("--prompt", help="prompt text (default: read from stdin)")
    ap.add_argument("--quiet", action="store_true", help="suppress hint on stderr")
    ap.add_argument("--json", action="store_true", help="emit JSON result on stdout")
    args = ap.parse_args(argv)

    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    result = detect(prompt)

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "is_code_task": result.is_code_task,
                    "score": result.score,
                    "scope": result.scope,
                    "signals": result.signals,
                }
            )
        )

    if result.is_code_task and not args.quiet:
        print(result.hint, file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

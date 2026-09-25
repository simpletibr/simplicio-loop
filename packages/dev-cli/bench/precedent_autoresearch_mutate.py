#!/usr/bin/env python3
"""precedent_autoresearch_mutate.py — mutate-cmd for the #90 autoresearch run.

Asks a REAL LLM (`claude -p`, claude-cli provider mode — no API key needed, see
`simplicio/providers.py`) to tighten ONLY the wording of the human-readable scaffolding
strings inside `simplicio/precedent.py::build_precedent_block()` (the instructional
sentences, the "# {path}:{line} (...)" comment prefix, the "tags:" label) — never the
data itself (summary/snippet/tags content), never the function signature, imports, or
control flow. The gate (existing pytest + ruff) and the eval's own content-preservation
check are what actually enforce this; this script's job is only to produce a candidate
and reject it early if it isn't even valid Python.

Per the autoresearch worker contract: mutate-cmd receives AUTORESEARCH_ITERATION /
AUTORESEARCH_TARGET / AUTORESEARCH_PLATEAU / AUTORESEARCH_BEST_SCORE in its environment,
mutates `--target` IN PLACE, and its own exit code matters (nonzero -> the worker skips
gate/eval for that iteration and reverts).
"""
import ast
import os
import subprocess
import sys

TARGET = os.environ.get("AUTORESEARCH_TARGET", "simplicio/precedent.py")
PLATEAU = os.environ.get("AUTORESEARCH_PLATEAU", "0") == "1"
ITERATION = os.environ.get("AUTORESEARCH_ITERATION", "?")

PROMPT_TEMPLATE = """You are optimizing ONE Python source file for prompt-token economy.

The file below implements `build_precedent_block()`, a function that renders a block of
text later embedded into an LLM prompt (so every token in its OUTPUT costs money at scale).

STRICT RULES — violating any of these makes the change worthless (it will be rejected):
1. Change ONLY the literal wording of human-readable scaffolding strings that this function
   builds and returns: instructional sentences, comment-style headers like
   "# {{path}}:{{line}} (...)", and labels like "tags:". Make them SHORTER, not different in
   meaning.
2. NEVER remove or alter the exact substring pattern "{{path}}:{{line}}" for any candidate —
   downstream tests assert on it literally.
3. NEVER remove, truncate, or reword the actual DATA fields (summary text, tags list, code
   snippet) — only the labels/prose AROUND them.
4. NEVER change the function signature, imports, control flow, variable names, or any
   non-string-literal code.
5. Keep it 100% valid Python 3. Keep the "[PRECEDENT]" marker as the literal first line of
   any returned block.
6. Output ONLY the complete new file content — no markdown code fences, no commentary, no
   explanation before or after.
{plateau_hint}
--- FILE: {target} ---
{source}
--- END FILE ---
"""

PLATEAU_HINT = (
    "\nThe last several attempts made no measurable improvement. Try a MORE aggressive "
    "wording cut this time (e.g. drop entire redundant instructional sentences), while "
    "still obeying every rule above.\n"
)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_path = os.path.join(root, TARGET)
    with open(target_path, encoding="utf-8") as f:
        source = f.read()

    prompt = PROMPT_TEMPLATE.format(
        target=TARGET,
        source=source,
        plateau_hint=PLATEAU_HINT if PLATEAU else "",
    )

    try:
        result = subprocess.run(
            # --tools "" disables all tool use: without it the nested session may try to
            # Edit the file itself, get blocked by this sandbox's nested-permission model,
            # and print an apology sentence instead of the requested plain-text file content.
            # `prompt` MUST precede `--tools` here: --tools is variadic and would otherwise
            # swallow the prompt string as one of its own values instead of the CLI treating
            # it as the positional prompt argument.
            ["claude", "-p", "--print", prompt, "--tools", ""],
            capture_output=True,
            text=True,
            timeout=150,
            cwd=root,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print("mutate: claude -p invocation failed: %r" % exc, file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        print("mutate: claude -p exited %d: %s" % (result.returncode, result.stderr[-2000:]),
              file=sys.stderr)
        sys.exit(1)

    candidate = result.stdout.strip()
    # Strip accidental markdown fences even though the prompt forbids them.
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        print("mutate: candidate is not valid Python, rejecting early: %r" % exc,
              file=sys.stderr)
        sys.exit(1)

    if "[PRECEDENT]" not in candidate or "def build_precedent_block" not in candidate:
        print("mutate: candidate dropped required marker/function, rejecting early",
              file=sys.stderr)
        sys.exit(1)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(candidate if candidate.endswith("\n") else candidate + "\n")

    print("mutate: iteration %s wrote candidate (%d chars, was %d)"
          % (ITERATION, len(candidate), len(source)))


if __name__ == "__main__":
    main()

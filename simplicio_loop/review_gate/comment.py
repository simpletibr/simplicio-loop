"""The PR comment of the automatic review: verdict first, then roles, numbers and the cause of every non-green check."""
from __future__ import annotations

import re
from typing import Sequence

from .identity import Agent
from .model import GateReport

APPROVED = "REVISÃO AUTOMÁTICA: APROVADA"
REJECTED = "REVISÃO AUTOMÁTICA: REPROVADA"
_APPROVAL_LINE = re.compile(r"^REVIS[ÃA]O AUTOM[ÁA]TICA: APROVADA \(n[íi]vel ([0-2])\)\s*$", re.IGNORECASE)


def parse_level(body: str) -> int | None:
    """The level of an approval comment (its first non-quoted line), None when it is not an approval."""
    for line in body.splitlines():
        if line.startswith(">"):
            continue
        found = _APPROVAL_LINE.match(line.strip())
        return int(found.group(1)) if found else None
    return None


def _agent(label: str, agent: Agent | None) -> str:
    return f"- {label}: nenhum" if agent is None else f"- {label}: {agent.agent_id} ({agent.role}, {agent.model}, {agent.host})"


def _numbers(measured: dict) -> str:
    parts = []
    if "killed" in measured and "total" in measured:
        parts.append(f"mutantes mortos {measured['killed']}/{measured['total']}")
    if "red" in measured:
        parts.append(f"{len(measured['red'])} de {measured.get('tests', '?')} testes vermelhos em main")
    if "new_symbols" in measured:
        parts.append(f"{measured['new_symbols']} simbolos novos, {len(measured.get('unused', []))} sem chamador")
    if "criteria" in measured:
        parts.append(f"criterios cobertos {measured.get('covered', '?')}/{measured['criteria']}")
    if "elapsed_s" in measured:
        parts.append(f"{measured['elapsed_s']:.1f} s")
    return "; ".join(parts)


def render(report: GateReport, author: Agent, reviewer: Agent, independent: Agent | None, commands: Sequence[str]) -> str:
    head = APPROVED if report.approved else REJECTED
    lines = [f"{head} (nível {report.level.number})", "", f"PR #{report.pr}, head `{report.head[:7]}`, portao em {report.elapsed_s:.1f} s.", "",
             "Papeis:", _agent("autor", author), _agent("revisor automatico", reviewer),
             _agent("revisor independente", independent), "", "Checagens:"]
    for check in report.checks:
        numbers = _numbers(dict(check.measured))
        lines.append(f"- {check.name}: {check.status}" + (f" ({numbers})" if numbers else ""))
        lines += [f"  - {reason}" for reason in check.reasons]
    if report.partial:
        lines += ["", "PR PARCIAL: criterios da issue sem cobertura. Use `Parte de #" + str(report.issue) +
                  "`, liste o que falta e nao use palavra de fechamento."]
    if commands:
        lines += ["", "Comandos rodados:", *[f"- `{c}`" for c in commands]]
    return "\n".join(lines) + "\n"

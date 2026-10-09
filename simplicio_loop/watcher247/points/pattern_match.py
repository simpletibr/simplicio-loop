"""pattern_match (intake): the issue against the bug patterns simplicio-learn keeps in patterns.jsonl.

Same store and schema as `scripts/loop_journal.py suggest` (fingerprint, root_cause, symptom_pattern, fix_summary,
sibling_files, hit_count, last_seen), read-only here: simplicio-learn owns the writes. A pattern hits when its
fingerprint prefix or its symptom_pattern (a regex; a plain substring if invalid) is in the issue text. The
largest hit_count is recorded; above 1 the module keeps breaking, so it is flagged for structural attention.
"""
import asyncio
import json
import re

from .. import verify
from .recall import applies
from .registry import PointContext, PointResult, register

NAME = "pattern_match"
STORE = (".simplicio-loop", "orchestrator", "patterns.jsonl")
FINGERPRINT_PREFIX = 12


def _patterns(ctx: PointContext) -> list[dict]:
    try:
        lines = ctx.clone.joinpath(*STORE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _symptom(symptom: str, text: str) -> bool:
    if not symptom:
        return False
    try:
        return re.search(symptom, text, re.IGNORECASE) is not None
    except re.error:
        return symptom.lower() in text


def _hit(row: dict, text: str) -> bool:
    fingerprint = str(row.get("fingerprint") or "")[:FINGERPRINT_PREFIX].lower()
    return (len(fingerprint) == FINGERPRINT_PREFIX and fingerprint in text) or _symptom(
        str(row.get("symptom_pattern") or ""), text)


def _hit_count(row: dict) -> int:
    count = row.get("hit_count")
    return count if isinstance(count, int) else 0


def _match(ctx: PointContext) -> PointResult:
    rows = _patterns(ctx)
    text = f"{ctx.issue.get('title') or ''}\n{ctx.issue.get('body') or ''}".lower()
    matches = [{"fingerprint": str(row.get("fingerprint") or "")[:FINGERPRINT_PREFIX],
                "root_cause": row.get("root_cause"), "fix_summary": row.get("fix_summary"),
                "sibling_files": row.get("sibling_files"), "hit_count": _hit_count(row),
                "last_seen": row.get("last_seen")} for row in rows if _hit(row, text)]
    hit_count = max((match["hit_count"] for match in matches), default=0)
    evidence = {"matches": matches, "hit_count": hit_count, "structural_attention": hit_count > 1}
    if not rows:
        evidence["label"] = verify.UNVERIFIED
    return PointResult(NAME, "ok", evidence)


async def pattern_match(ctx: PointContext) -> PointResult:
    return await asyncio.to_thread(_match, ctx)


register(NAME, "intake", pattern_match, applies=applies)

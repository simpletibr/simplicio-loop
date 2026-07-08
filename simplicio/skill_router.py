"""
skill_router.py — LAYER 4.5. Picks THE skill that matches the task.
Does NOT inject all of them (noise). Ranks by meaning, takes top-1.

Skill source: by default scans <root>/.mapper/skills/*.md or
SIMPLICIO_SKILLS_DIR. Each skill = md file whose first line is the description.
Reuses the same embedding cache.
"""

import glob
import os

import numpy as np

from .cache import EmbeddingCache


def _skills_dir(root: str) -> str:
    return os.environ.get("SIMPLICIO_SKILLS_DIR", os.path.join(root, ".mapper", "skills"))


def _load_skills(root: str) -> list[dict[str, str]]:
    d = _skills_dir(root)
    out = []
    for fp in glob.glob(os.path.join(d, "*.md")):
        try:
            txt = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        desc = next((line.strip("# ").strip() for line in txt.splitlines() if line.strip()), "")
        out.append({"name": os.path.basename(fp), "desc": desc, "body": txt})
    return out


def build_skill_block(root: str, task: str, threshold: float = 0.15) -> str:
    skills = _load_skills(root)
    if not skills:
        return ""  # no skills -> layer disappears, no noise
    from .precedent import _embedder

    embedder = _embedder()
    cache = EmbeddingCache(root)
    descs = [s["desc"] for s in skills]
    missing = cache.get_missing(descs)
    if missing:
        cache.add(missing, embedder.encode(missing, show_progress_bar=False))
        cache.save()
    vd = cache.lookup(descs)
    vt = embedder.encode([task])[0]
    vt_norm = float(np.linalg.norm(vt))
    scores = []
    for v in vd:
        denom = vt_norm * float(np.linalg.norm(v))
        scores.append(float(np.dot(vt, v) / denom) if denom else 0.0)
    i = int(np.argmax(scores))
    if scores[i] < threshold:
        return ""  # nothing matches enough -> don't force an irrelevant skill
    s = skills[i]
    return (
        f"[RELEVANT SKILL]\nThe mapper has a method that matches this task "
        f"(match {scores[i]:.2f}). Follow it:\n# {s['name']}\n{s['body'][:1200]}"
    )

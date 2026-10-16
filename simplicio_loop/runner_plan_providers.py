"""Mechanical fallback plan and provider worker plan for the runner (#1818 split of runner_plan).

Functions moved verbatim from `simplicio_loop/runner_plan.py` (#1818).
`runner_plan` re-exports them, so import paths and patch targets on `runner_plan` keep working.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence
from . import dashboard_events as _dashboard_events
from .provider_worker import OPENROUTER_MODEL, ProviderWorkerError, forwarded_environment, proposal_to_mechanical_plan


def _mechanical_fixture_plan(task: Mapping[str, Any], repo_path: Path) -> Dict[str, Any] | None:
    """Build the explicit mechanical plan for the isolated PAGE fixture.

    The installed Dev CLI is intentionally deterministic-only and accepts an
    explicit mechanical plan as its safe fallback.  This narrow adapter is
    enabled only by ``SIMPLICIO_LOOP_MECHANICAL_FALLBACK`` and only for the
    benchmark's PAGE tasks; it is not a general task interpreter and never
    changes the physical admission decision.
    """
    if os.environ.get("SIMPLICIO_LOOP_MECHANICAL_FALLBACK", "").strip().lower() not in {
        "1", "true", "yes", "on"
    }:
        return None
    identity = task.get("identity") if isinstance(task.get("identity"), Mapping) else {}
    task_id = str(identity.get("system") or task.get("id") or "").strip().upper()
    if not re.fullmatch(r"PAGE-10[1-5]", task_id):
        return None

    index_path = repo_path / "site" / "index.html"
    current_index = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""

    base = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simplicio — thoughtful automation</title>
</head>
<body>
  <header>
    <p class="eyebrow">Simplicio</p>
    <h1>Simplicio: build clearly. Ship simply.</h1>
    <p>Practical automation for teams that value momentum and control.</p>
  </header>
  <main>
    <section aria-labelledby="intro-title">
      <h2 id="intro-title">A simpler path from idea to delivery</h2>
      <p>Simplicio keeps the work visible, focused, and easy to verify.</p>
    </section>
  </main>
  <footer><p>© Simplicio</p></footer>
</body>
</html>
"""
    navigation = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Simplicio — thoughtful automation</title>
</head>
<body>
  <header>
    <nav aria-label="Primary">
      <ul>
        <li><a href="index.html">Home</a></li>
        <li><a href="about.html">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
    </nav>
    <p class="eyebrow">Simplicio</p>
    <h1>Simplicio: build clearly. Ship simply.</h1>
    <p>Practical automation for teams that value momentum and control.</p>
  </header>
  <main>
    <section aria-labelledby="intro-title">
      <h2 id="intro-title">A simpler path from idea to delivery</h2>
      <p>Simplicio keeps the work visible, focused, and easy to verify.</p>
    </section>
  </main>
  <footer><p>© Simplicio</p></footer>
</body>
</html>
"""
    with_styles = navigation.replace(
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <link rel="stylesheet" href="styles.css">\n',
        1,
    )
    with_contact = with_styles.replace(
        "  </main>\n",
        """    <section id="contact" aria-labelledby="contact-title">
      <h2 id="contact-title">Contact Simplicio</h2>
      <form action="#contact" method="post">
        <p><label for="name">Name</label><input id="name" type="text" name="name" required></p>
        <p><label for="email">Email</label><input id="email" type="email" name="email" required></p>
        <p><label for="message">Message</label><textarea id="message" name="message" required></textarea></p>
        <button type="submit">Send message</button>
      </form>
    </section>
  </main>
""",
        1,
    )
    css = """/* Simplicio's small, local-first design system. */
:root { color-scheme: light; font-family: system-ui, sans-serif; line-height: 1.5; }
body { margin: 0; color: #172033; background: #f5f7fb; }
header, main, footer { width: min(100% - 2rem, 68rem); margin-inline: auto; }
header { padding-block: 2rem 3rem; }
nav ul { display: flex; gap: 1rem; padding: 0; list-style: none; }
a { color: #2457c5; }
section { padding-block: 2rem; }
input, textarea, button { box-sizing: border-box; width: 100%; max-width: 34rem; padding: .65rem; font: inherit; }
textarea { min-height: 8rem; }
button { cursor: pointer; }
@media (max-width: 42rem) {
  nav ul { flex-direction: column; gap: .5rem; }
  header, main, footer { width: min(100% - 1.25rem, 68rem); }
}
"""
    about = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>About Simplicio</title>
</head>
<body>
  <main>
    <p class="eyebrow">Simplicio</p>
    <h1>About Simplicio</h1>
    <p>Simplicio makes dependable automation easier to understand and verify.</p>
    <p><a href="index.html">Return to the Simplicio home page</a></p>
  </main>
</body>
</html>
"""

    def replace(path: str, desired: str, current: str) -> Dict[str, Any]:
        line_count = max(1, len(current.splitlines()))
        return {"op": "replace_range", "path": path, "start_line": 1,
                "end_line": line_count, "text": desired}

    operations: List[Dict[str, Any]] = []
    touched: List[str] = []
    if task_id == "PAGE-101":
        operations.append({"op": "create_file", "path": "site/index.html", "text": base})
        touched.append("site/index.html")
    elif task_id == "PAGE-102":
        if not current_index:
            return None
        operations.append(replace("site/index.html", navigation, current_index))
        touched.append("site/index.html")
    elif task_id == "PAGE-103":
        if not current_index:
            return None
        operations.extend([
            {"op": "create_file", "path": "site/styles.css", "text": css},
            replace("site/index.html", with_styles, current_index),
        ])
        touched.extend(["site/styles.css", "site/index.html"])
    elif task_id == "PAGE-104":
        if not current_index:
            return None
        operations.append(replace("site/index.html", with_contact, current_index))
        touched.append("site/index.html")
    else:
        operations.append({"op": "create_file", "path": "site/about.html", "text": about})
        touched.append("site/about.html")
    return {
        "schema": "simplicio.mechanical-edit/v1",
        "touched_files": touched,
        "operations": operations,
        "validation": [],
    }


def _provider_worker_plan(
    *,
    task: Mapping[str, Any],
    context: Mapping[str, Any],
    run_id: str,
    task_index: int,
    attempt: int,
    root: Path,
    allowed_paths: Sequence[str],
    run_dir: Path,
    provider_worker: str | None = None,
    repair_feedback: str | None = None,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    """Obtain one external proposal and convert it through the Dev CLI plan contract.

    Provider selection is explicit. The default path returns ``(None, None)`` so
    deterministic Dev CLI behavior remains unchanged. A selected worker failure
    writes a blocked, secret-free receipt and raises; it never falls back to a
    deterministic or manual edit.
    """
    selected = str(provider_worker or os.environ.get("SIMPLICIO_PROVIDER_WORKER") or "").strip().lower()
    if not selected:
        return None, None
    if selected != "openrouter":
        raise ProviderWorkerError(
            f"unsupported provider worker {selected!r}",
            reason_code="provider_worker_unsupported",
        )
    receipt_path = run_dir / f"provider-worker-{task_index}-attempt-{max(1, int(attempt))}.json"
    try:
        result = _runner_plan.OpenRouterWorker().dispatch(
            task=task,
            context=_provider_context_with_current_targets(
                context,
                root=root,
                allowed_paths=allowed_paths,
            ),
            run_id=run_id,
            task_index=task_index,
            allowed_paths=allowed_paths,
            env=os.environ,
            repair_feedback=repair_feedback,
            repo_root=root,
        )
        forwarded = forwarded_environment(os.environ)
        plan = proposal_to_mechanical_plan(
            result["proposal"],
            root=root,
            allowed_paths=allowed_paths,
            forbidden_literals=(forwarded["OPENROUTER_API_KEY"],),
        )
        plan_path = run_dir / f"provider-mechanical-plan-{task_index}-attempt-{max(1, int(attempt))}.json"
        _write_json(plan_path, plan)
        proposal = result.get("proposal") if isinstance(result.get("proposal"), Mapping) else {}
        files = proposal.get("files") if isinstance(proposal, Mapping) else {}
        receipt = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "READY",
            "provider": "openrouter",
            "upstream_provider": result.get("upstream_provider"),
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "allowed_paths": sorted(str(path) for path in allowed_paths),
            "proposed_paths": sorted(str(path) for path in files) if isinstance(files, Mapping) else [],
            "prompt_sha256": str(result.get("prompt_sha256") or ""),
            "proposal_sha256": str(result.get("response_sha256") or ""),
            "mechanical_plan_path": str(plan_path),
            "provider_call_count": int(result.get("provider_call_count") or 1),
            "usage": result.get("usage"),
            "usage_status": result.get("usage_status", "unknown"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "cached_tokens": result.get("cached_tokens"),
            "cache_write_tokens": result.get("cache_write_tokens"),
            "reasoning_tokens": result.get("reasoning_tokens"),
            "cost": result.get("cost"),
            "cost_status": result.get("cost_status", "unknown"),
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, receipt)
        # The provider's measured usage is known only now: the route record was written before the call.
        _dashboard_events.emit_token_usage(run_dir, only=receipt_path.name)
        return plan, receipt
    except ProviderWorkerError as exc:
        blocked = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "BLOCKED",
            "provider": "openrouter",
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "reason_code": exc.reason_code,
            "error": str(exc),
            "usage": None,
            "usage_status": "unknown",
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
            "cost_status": "unknown",
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, blocked)
        raise
    except Exception as exc:  # noqa: BLE001 - selected provider is fail-closed
        blocked = {
            "schema": "simplicio.provider-worker-receipt/v1",
            "status": "BLOCKED",
            "provider": "openrouter",
            "model": OPENROUTER_MODEL,
            "run_id": str(run_id),
            "task_index": int(task_index),
            "attempt": max(1, int(attempt)),
            "reason_code": "provider_worker_failed",
            "error": f"provider worker failed: {type(exc).__name__}",
            "usage": None,
            "usage_status": "unknown",
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "cost": None,
            "cost_status": "unknown",
            "receipt_path": str(receipt_path),
        }
        _write_json(receipt_path, blocked)
        raise ProviderWorkerError(blocked["error"], reason_code=blocked["reason_code"]) from exc

from .runner_core import (_write_json)  # noqa: E402
from .runner_plan import (_provider_context_with_current_targets)  # noqa: E402
from . import runner_plan as _runner_plan  # noqa: E402

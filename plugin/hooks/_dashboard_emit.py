"""Fail-open bridge from the hooks to ``scripts/dashboard_events.py`` (issue #1398).

``loop_stop``, ``action_gate`` and ``user_prompt_submit`` call ``emit(kind, ...)``. It loads the
emitter next to the hooks (``../scripts``, the source and plugin layouts) or from the project
(``./scripts``), resolves the active run and appends one ``simplicio.dashboard-event/v1`` event.
With the kill switch ``SIMPLICIO_DASHBOARD_EVENTS=0``, no emitter or no resolvable run it does
nothing, and it never raises: a hook's own decision is never affected.
"""
import importlib.util
import os
import sys

_MODULE = []


def _module():
    if _MODULE:
        return _MODULE[0]
    found = None
    existing = sys.modules.get("dashboard_events")
    if existing is not None and hasattr(existing, "emit_from_hook"):
        found = existing
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        for scripts_dir in (os.path.join(os.path.dirname(here), "scripts"),
                            os.path.join(os.getcwd(), "scripts")):
            path = os.path.join(scripts_dir, "dashboard_events.py")
            if not os.path.isfile(path):
                continue
            try:
                spec = importlib.util.spec_from_file_location("dashboard_events", path)
                module = importlib.util.module_from_spec(spec)
                sys.modules["dashboard_events"] = module
                spec.loader.exec_module(module)
                found = module
                break
            except Exception:
                sys.modules.pop("dashboard_events", None)
    _MODULE.append(found)
    return found


def emit(kind, **spec):
    """Append one hook event to the active run; returns the envelope or None. Never raises."""
    try:
        if str(os.environ.get("SIMPLICIO_DASHBOARD_EVENTS", "")).strip().lower() in (
                "0", "false", "no", "off", "disabled"):
            return None
        module = _module()
        return module.emit_from_hook(kind, **spec) if module is not None else None
    except Exception:
        return None

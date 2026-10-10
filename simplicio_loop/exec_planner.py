"""CLI exec planners for claude, codex, grok, gemini, agy and opencode, run as plan-only planners (issues 1431, 1432).

The planner never mutates the repo. It returns a plan JSON (``{"operations": [...]}``) that the dev-cli applies
(``simplicio-loop turbo --apply -``). Every argv therefore uses the CLI's most restrictive non-interactive mode.
Flags marked VERIFIED were checked against ``<cli> --help`` on the host (agy 1.3.2, opencode 1.18.30). gemini is not
installed here, so its flags are DOC-BASED (vendor docs) and unverified.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import time

from . import input_ceiling, model_roles, plan_scope, structured_output

DEFAULT_FAMILIES = ["claude", "codex", "grok", "gemini"]
KILL_GRACE_SEC = 3.0

# opencode's built-in `plan` agent denies edits but allows bash and webfetch. This config is written to a temp file and
# passed through OPENCODE_CONFIG so the planner cannot run commands or fetch URLs.
OPENCODE_DENY_CONFIG = {"permission": {"bash": "deny", "webfetch": "deny", "edit": "deny"}}

PLAN_ONLY_PREAMBLE = (
    "You are a planner only. Do NOT edit files and do NOT run commands. Reply with exactly one JSON object "
    '{"operations": [...]} describing the edits. The dev-cli applies it afterwards '
    "(`simplicio-loop turbo --apply -`). Task:\n\n"
)


class ExecPlannerError(Exception):
    """Base error for exec planner failures."""


class ScopeRejected(ValueError):
    """The answer broke the closed plan contract or the task scope; ``violations`` are the deterministic reasons."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__(plan_scope.retry_message(self.violations))


class PlannerResult:
    """Result of running a planner via CLI exec."""

    def __init__(self, reason_code, family, role, model, effort, plan=None, error=None, execution_ms=0.0, raw=None,
                 structured=("", ""), violations=(), surface=("", "")):
        self.reason_code = reason_code
        self.family = family
        self.role = role
        self.model = model
        self.effort = effort
        self.plan = plan
        self.error = error
        self.execution_ms = execution_ms
        self.raw = raw  # the CLI text before the plan is cut out of it, NOT redacted (None: it never answered); redact before it is stored
        self.structured_output, self.structured_reason = structured  # what the argv asked of the CLI; ("", "") when none ran
        self.tool_surface, self.tool_surface_reason = surface  # the tools the argv left the run; ("", "") when none ran
        self.violations = list(violations)  # why plan_scope refused the answer (reason_code bad_plan), else empty

    def is_ok(self):
        return self.reason_code == "ok"

    def to_dict(self):
        return {
            "reason_code": self.reason_code,
            "family": self.family,
            "role": self.role,
            "model": self.model,
            "effort": self.effort,
            "plan": self.plan,
            "error": self.error,
            "execution_ms": self.execution_ms,
            "raw": self.raw,
            "structured_output": self.structured_output,
            "structured_reason": self.structured_reason,
            "tool_surface": self.tool_surface,
            "tool_surface_reason": self.tool_surface_reason,
        }


def _find_cli(name):
    return shutil.which(name)


def _get_families():
    env = os.environ.get("SIMPLICIO_EXEC_FAMILIES", "").strip()
    if env:
        return [f.strip() for f in env.split(",") if f.strip()]
    return DEFAULT_FAMILIES


def _real_model(model):
    return bool(model) and model not in ("default", "auto")


TOOL_NONE = "none"  # the argv switches off the built-in tools, MCP, skills and the saved session
TOOL_READ = "read"  # the argv allows only the read tools of the family (lines omitted from the request)
TOOL_REDUCED = "reduced"  # the CLI has no verified switch for its tools or MCP: the run is not called tool-free

# Each family's minimal surface: (mode, reason). A family in SUPPORTED_FAMILIES without an entry here has no receipt.
_TOOL_SURFACE = {
    "claude": (TOOL_NONE, "flags:--tools,--strict-mcp-config,--disable-slash-commands,--no-session-persistence"),
    "codex": (TOOL_REDUCED, "read-only sandbox; no verified flag turns off the shell or MCP"),
    "grok": (TOOL_REDUCED, "plan mode; built-in tool names and an MCP switch are not verified"),
    "gemini": (TOOL_REDUCED, "doc-based plan mode; not measured on this host"),
    "agy": (TOOL_REDUCED, "plan mode and sandbox; MCP only through the config subcommand"),
    "opencode": (TOOL_REDUCED, "deny config for bash, webfetch and edit only; read tools and MCP not denied"),
}
# A family's read mode: the tool list its argv passes, and the reason on the receipt.
_READ_MODE = {"claude": ("Read,Grep,Glob", "lines omitted from the request: read tools only, MCP and skills still off")}


def _surface(family, read_tools):
    """(tool list for the argv, receipt mode, receipt reason) of one run of ``family``."""
    if read_tools and family in _READ_MODE:
        tools, reason = _READ_MODE[family]
        return tools, TOOL_READ, reason
    mode, reason = _TOOL_SURFACE[family]
    return "", mode, reason


def tool_surface(family, read_tools=False):
    """The receipt ``(mode, reason)`` of a run of ``family``; ``read`` only when the family has a read mode."""
    _tools, mode, reason = _surface(family, read_tools)
    return mode, reason


def _build_argv_claude(prompt, role, model, effort, cwd, tools):
    # VERIFIED via `claude --help`: -p, --model, --effort, --tools ("" disables all), --disable-slash-commands,
    # --strict-mcp-config, --no-session-persistence, --setting-sources user, --output-format.
    # --bare is not used: measured 2026-10-10, it answers "Not logged in" with the login (OAuth), not an API key.
    argv = ["claude", "-p", prompt]
    if _real_model(model):
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    argv.extend(["--tools", tools, "--disable-slash-commands", "--strict-mcp-config", "--no-session-persistence",
                 "--setting-sources", "user", "--output-format", "json"])
    return argv


def _build_argv_codex(prompt, role, model, effort, cwd, tools):
    # VERIFIED via `codex exec --help`: -s read-only, --ephemeral, --ignore-user-config, --ignore-rules, -C/--cd, -m,
    # -c key=value. --ignore-user-config keeps the user's config.toml (MCP servers, plugins) out of the run.
    # DOC-BASED: the config key `model_reasoning_effort` (--help only says -c takes key=value).
    argv = ["codex", "exec", "-s", "read-only", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--cd", cwd]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["-c", 'model_reasoning_effort="%s"' % effort])
    argv.append("-")
    return argv


def _build_argv_grok(prompt, role, model, effort, cwd, tools):
    # VERIFIED via `grok --help`: -p, -m, --reasoning-effort, --permission-mode plan, --cwd, --output-format json.
    # UNVERIFIED: --disallowed-tools needs the built-in tool names, and no MCP switch is listed, so none is added.
    argv = ["grok", "-p", prompt]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["--reasoning-effort", effort])
    argv.extend(["--permission-mode", "plan", "--cwd", cwd, "--output-format", "json"])
    return argv


def _build_argv_gemini(prompt, role, model, effort, cwd, tools):
    # DOC-BASED (gemini not installed on this host): -p, -m, --approval-mode plan, --output-format json.
    # Gemini CLI has no effort flag, so effort is only recorded in the result.
    argv = ["gemini", "-p", prompt]
    if _real_model(model):
        argv.extend(["-m", model])
    argv.extend(["--approval-mode", "plan", "--output-format", "json"])
    return argv


def _build_argv_agy(prompt, role, model, effort, cwd, tools):
    # VERIFIED with `agy --help` (agy 1.3.2): -p/--print, --mode (accept-edits, plan), --sandbox, --disable-slash-commands,
    # --output-format (text, json, stream-json), --model, --effort (low|medium|high|xhigh|max).
    argv = ["agy", "-p", prompt, "--mode", "plan", "--sandbox", "--disable-slash-commands", "--output-format", "json"]
    if _real_model(model):
        argv.extend(["--model", model])
    if effort:
        argv.extend(["--effort", effort])
    return argv


def _build_argv_opencode(prompt, role, model, effort, cwd, tools):
    # VERIFIED with `opencode run --help` (opencode 1.18.30): the message argument, --format json,
    # -m provider/model, --variant (provider-specific reasoning effort), --agent, --pure (no external plugins).
    # `opencode agent list` shows `plan`.
    # VERIFIED with `opencode debug agent plan`: the built-in `plan` agent allows bash and webfetch, so run_planner
    # also sets OPENCODE_CONFIG to OPENCODE_DENY_CONFIG (bash, webfetch and edit deny); the resolved plan agent then
    # lists those denies. DOC-BASED: OPENCODE_CONFIG as an env var is not listed by --help; it comes from the opencode
    # config docs, and the debug output above is what confirms it takes effect.
    argv = ["opencode", "run", prompt, "--format", "json", "--agent", "plan", "--pure"]
    if _real_model(model):
        argv.extend(["-m", model])
    if effort:
        argv.extend(["--variant", effort])
    return argv


_ARGV_BUILDERS = {
    "claude": _build_argv_claude,
    "codex": _build_argv_codex,
    "grok": _build_argv_grok,
    "gemini": _build_argv_gemini,
    "agy": _build_argv_agy,
    "opencode": _build_argv_opencode,
}
SUPPORTED_FAMILIES = tuple(_ARGV_BUILDERS)

# Quota, rate-limit and auth terms, matched case-insensitively in stderr and stdout. The quota list follows the
# capacity terms in packages/dev-cli/simplicio/providers.py. None of these strings is verified against CLI output.
_QUOTA_TERMS = ("quota", "insufficient_quota", "credit balance", "billing", "usage limit")
_RATE_TERMS = ("rate limit", "rate_limit", "too many requests")
_AUTH_TERMS = ("auth", "unauthorized", "not logged in", "log in", "login", "api key")


def classify_failure(returncode, stderr, stdout):
    """Map a failed CLI run to quota_exhausted, rate_limited or auth_error; None when it is a generic failure."""
    if returncode == 0:
        return None
    text = f"{stderr}\n{stdout}".lower()
    for code, terms in (("quota_exhausted", _QUOTA_TERMS), ("rate_limited", _RATE_TERMS), ("auth_error", _AUTH_TERMS)):
        if any(term in text for term in terms):
            return code
    return None


def build_argv(family, role, prompt, model, cwd, effort="", schema_file="", read_tools=False):
    """Build the plan-only command-line argv for a specific family's CLI exec.

    The CLI's own schema flag (``structured_output.cli_flags``) goes last, before a trailing ``-`` stdin marker.
    ``schema_file`` is the plan schema on disk, for a CLI that reads it from a file (codex).
    ``read_tools``: the request omits lines, so the family's read tools are allowed (``tool_surface``).
    """
    builder = _ARGV_BUILDERS.get(family)
    if not builder:
        raise ExecPlannerError(f"unsupported family: {family}")
    tools, _mode, _reason = _surface(family, read_tools)
    argv = builder(prompt, role, model, effort, cwd, tools)
    try:
        flags = structured_output.cli_flags(family, schema_file)
    except ValueError as e:
        raise ExecPlannerError(str(e)) from e
    at = len(argv) - 1 if argv[-1] == "-" else len(argv)
    argv[at:at] = flags
    return argv


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


async def _kill_process_tree(proc, grace_sec=KILL_GRACE_SEC):
    """SIGTERM the whole process group, then SIGKILL whatever survives the grace period."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    deadline = time.monotonic() + grace_sec
    while time.monotonic() < deadline:
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        if proc.returncode is not None and not _group_alive(pgid):
            return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    await proc.wait()


async def _run_subprocess(argv, stdin_text=None, timeout_sec=60.0, cwd=None, grace_sec=KILL_GRACE_SEC, env=None):
    """Run a subprocess in its own session and return (stdout, stderr, returncode); kill the tree on timeout."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin_text else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_text.encode("utf-8") if stdin_text else None),
            timeout=timeout_sec,
        )
    except asyncio.TimeoutError:
        await _kill_process_tree(proc, grace_sec)
        raise
    return stdout_bytes.decode("utf-8", errors="replace"), stderr_bytes.decode("utf-8", errors="replace"), proc.returncode


# `--output-format json` wraps the answer in an envelope. Measured on this host (claude 2.1.292, grok 1.0.46, agy 1.3.2):
# the model text is `result` (claude), `text` (grok) or `response` (agy, prose around the JSON), and with a schema flag
# the parsed object is `structured_output` (claude, agy) or `structuredOutput` (grok).
_OBJECT_KEYS = ("structured_output", "structuredOutput")
_TEXT_KEYS = ("result", "text", "response")


def _plan_from(obj):
    if isinstance(obj, dict):
        if "operations" in obj or "need" in obj:  # `need`: lines the planner could not see (turbo_window)
            return obj
        for key in _OBJECT_KEYS:
            if isinstance(obj.get(key), dict):
                return _plan_from(obj[key])
        for key in _TEXT_KEYS:
            if isinstance(obj.get(key), str):
                return _find_plan(obj[key])
    return None


def _find_plan(text):
    try:
        plan = _plan_from(json.loads(text))
        if plan:
            return plan
    except (json.JSONDecodeError, ValueError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return _plan_from(json.loads(text[start : end + 1]))
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _answer_text(output):
    """The model's own answer inside the CLI envelope: the parsed object a schema flag fills (re-encoded), else the text
    field, else the output as it is. This is what ``plan_scope`` judges, so prose around the JSON still shows."""
    try:
        obj = json.loads(output)
    except ValueError:
        return output
    while isinstance(obj, dict) and "operations" not in obj and "need" not in obj:
        nested = next((obj[key] for key in _OBJECT_KEYS if isinstance(obj.get(key), dict)), None)
        if nested is None:
            return next((obj[key] for key in _TEXT_KEYS if isinstance(obj.get(key), str)), output)
        obj = nested
    return json.dumps(obj) if isinstance(obj, dict) else output


def _extract_plan_json(output, scope=None, root=None):
    """Extract and validate plan JSON from CLI output.

    With a ``scope`` (``plan_scope.TaskScope``) the answer is also held to the closed plan contract and to that scope
    (``plan_scope.check_response``): extra prose, an extra field, a file outside the scope or over the line limit is a
    ValueError listing the violations. A plan that only asks for lines (``need``, no operations) is a valid answer.
    """
    plan = _find_plan(output)
    if plan is None:
        raise ValueError("plan JSON not found or invalid")
    if scope is not None:
        checked = plan_scope.check_response(_answer_text(output), scope, root or ".")
        if not checked.ok:
            raise ScopeRejected(checked.violations)
    return plan


def _result(code, family, role, model, effort, started, plan=None, error=None, raw=None, structured=("", ""), violations=(),
            surface=("", "")):
    return PlannerResult(code, family, role, model, effort, plan=plan, error=error, execution_ms=(time.monotonic() - started) * 1000,
                         raw=raw, structured=structured, violations=violations, surface=surface)


def _temp_file(prefix, text, directory):
    """Write ``text`` to a new temp file in ``directory`` (default: the system temp dir) and return its path."""
    if directory is not None:
        os.makedirs(directory, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=directory)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    return path


async def run_planner(family, role, prompt, cwd=None, timeout_sec=60.0, grace_sec=KILL_GRACE_SEC, wrap=None, env=None,
                      config_dir=None, scope=None, read_tools=False, *, repo_root):
    """Run the planner CLI for a specific family and role.

    ``repo_root`` is the repo the planner works in: its loop.toml sets the input-token ceiling the prompt must fit.

    ``wrap`` maps the argv to the argv actually spawned (the watcher passes its sandbox); the default is the identity.
    ``env`` is the whole environment of the subprocess; the default inherits the caller's.
    ``config_dir`` is where the opencode deny config and the codex schema file are written (default: the system temp
    dir). A sandbox that mounts a tmpfs on /tmp hides them, so opencode would then run WITHOUT the deny rules: pass a
    directory the sandbox binds. Both files are removed when the run ends.
    ``scope`` (``plan_scope.TaskScope``): the answer must stay inside it, else the result is ``bad_plan`` with ``violations`` (no other family is tried) and its error
    lists the violations (the text for the next attempt).
    ``read_tools``: the request omits lines, so the family's read tools are allowed; the result's ``tool_surface`` says so.
    """
    started = time.monotonic()
    try:
        resolved = model_roles.resolve(family, role)
    except model_roles.ModelRoleError as e:
        return _result("bad_role", family, role, "", "", started, error=str(e))
    model, effort = resolved["model"], resolved["effort"]

    if not _find_cli(family):
        return _result("cli_missing", family, role, model, effort, started, error=f"CLI '{family}' not found")

    try:
        ceiling = input_ceiling.resolve_ceiling(repo_root)
        projection = input_ceiling.Projection.estimated(PLAN_ONLY_PREAMBLE + prompt)
        input_ceiling.enforce_budget(projection, ceiling)
    except input_ceiling.CeilingConfigError as e:
        return _result("ceiling_invalid", family, role, model, effort, started, error=str(e))
    except input_ceiling.InputCeilingExceeded:
        return _result("input_ceiling_exceeded", family, role, model, effort, started, error="prompt exceeds ceiling")

    full_prompt = PLAN_ONLY_PREAMBLE + prompt
    temp_files = []
    try:
        schema_file = ""
        if structured_output.cli_needs_file(family):
            schema_file = _temp_file("simplicio-schema-", structured_output.schema_text(), config_dir)
            temp_files.append(schema_file)
        try:
            argv = build_argv(family, role, full_prompt, model, cwd or ".", effort, schema_file, read_tools=read_tools)
        except ExecPlannerError as e:
            return _result("bad_argv", family, role, model, effort, started, error=str(e))
        receipt = structured_output.cli_receipt(family)
        surface = tool_surface(family, read_tools)

        if wrap is not None:
            argv = wrap(argv)  # a refusing wrapper must not leave a temp file behind: the finally below removes them
        stdin_text = full_prompt if family == "codex" else None
        if family == "opencode":
            config_path = _temp_file("simplicio-opencode-", json.dumps(OPENCODE_DENY_CONFIG), config_dir)
            temp_files.append(config_path)
            env = {**(os.environ if env is None else env), "OPENCODE_CONFIG": config_path}
        try:
            stdout, stderr, returncode = await _run_subprocess(
                argv, stdin_text=stdin_text, timeout_sec=timeout_sec, cwd=cwd, grace_sec=grace_sec, env=env
            )
        except asyncio.TimeoutError:
            return _result("timeout", family, role, model, effort, started, error="timeout", structured=receipt, surface=surface)
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass

    failure = classify_failure(returncode, stderr, stdout)
    if failure:
        return _result(failure, family, role, model, effort, started, error=f"exit {returncode}: {failure}",
                       raw=f"{stdout}\n--- stderr ---\n{stderr}", structured=receipt, surface=surface)
    if returncode != 0:
        return _result("process_error", family, role, model, effort, started, error=f"exit {returncode}",
                       raw=f"{stdout}\n--- stderr ---\n{stderr}", structured=receipt, surface=surface)
    try:
        plan = _extract_plan_json(stdout, scope, cwd)
    except ScopeRejected as e:  # still bad_plan, but with the violations: another family would get the same prompt and scope
        return _result("bad_plan", family, role, model, effort, started, error=str(e), raw=stdout, structured=receipt,
                       violations=e.violations, surface=surface)
    except ValueError as e:
        return _result("bad_plan", family, role, model, effort, started, error=str(e), raw=stdout, structured=receipt,
                       surface=surface)
    return _result("ok", family, role, model, effort, started, plan=plan, raw=stdout, structured=receipt, surface=surface)


async def run_planner_with_fallback(role, prompt, cwd=None, timeout_sec=60.0, families=None, grace_sec=KILL_GRACE_SEC,
                                    wrap=None, env_for=None, config_dir=None, scope=None, read_tools=False, *, repo_root):
    """Try to run planner with each family in order, falling back on non-fatal errors.

    ``wrap``, ``env_for(family)``, ``scope`` and ``read_tools`` are passed to run_planner (the argv wrapper, the per-family
    environment, the task scope the answer must stay in and whether the read tools are allowed).
    """
    last_result = None
    for family in families or _get_families():
        result = await run_planner(family, role, prompt, cwd, timeout_sec, grace_sec, wrap=wrap,
                                   env=env_for(family) if env_for else None, config_dir=config_dir, scope=scope,
                                   read_tools=read_tools, repo_root=repo_root)
        if result.reason_code in ("bad_role", "bad_argv") or result.violations or result.is_ok():
            return result
        last_result = result
    return last_result or PlannerResult("no_families", "", role, "", "", error="no families")

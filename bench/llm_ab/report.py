"""Build a single self-contained REPORT.html page (pt-BR) from one
results.json (see run.py for its shape: one agentic run per arm, one
``totals``/``commands``/``llm_calls`` list per task). Charts are small
matplotlib PNGs, base64-inlined; run with a Python that has matplotlib
installed (it is not a package dependency of the benchmark itself -- only of
the report step).
"""
from __future__ import annotations

import base64
import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import aggregate as agg  # noqa: E402
import cost as bench_cost  # noqa: E402
import verdict as bench_verdict  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ARM_COLORS = {
    "normal": "#4C72B0",
    "simplicio": "#DD8452",
}
COLOR_CACHED = "#8FB2E0"
COLOR_COMPLETION = "#64B5A0"
COLOR_REASONING = "#C44E52"


def fig_to_base64(fig, dpi=110) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def html_escape(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt(n, decimals=4) -> str:
    if n is None:
        return "-"
    return f"{n:.{decimals}f}"


def build_charts(arms: dict) -> dict:
    charts = {}
    plt.rcParams.update({"font.size": 8})
    arm_names = list(arms)

    # Chart 1: total wall time per arm.
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    walls = [arms[a].get("total_wall_s") or 0 for a in arm_names]
    ax.bar(arm_names, walls, color=[ARM_COLORS.get(a, "#888") for a in arm_names])
    ax.set_ylabel("s (parede)")
    ax.set_title("Tempo total por braço")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    charts["wall_per_arm"] = fig_to_base64(fig)

    # Chart 2: stacked tokens per arm.
    fig, ax = plt.subplots(figsize=(3.6, 2.4))
    categories = [
        ("prompt_uncached", "prompt", "#9099A8"),
        ("cached", "cache", COLOR_CACHED),
        ("completion_non_reasoning", "compl.", COLOR_COMPLETION),
        ("reasoning", "raciocínio", COLOR_REASONING),
    ]
    bottoms = [0] * len(arm_names)
    for key, label, color in categories:
        vals = [agg.token_totals(arms[a])[key] for a in arm_names]
        ax.bar(arm_names, vals, bottom=bottoms, label=label, color=color)
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_ylabel("tokens")
    ax.set_title("Tokens totais (empilhado)")
    ax.legend(fontsize=6, loc="upper right")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    charts["tokens_stacked"] = fig_to_base64(fig)

    # Chart 3: cost per arm.
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    costs = [agg.token_totals(arms[a])["cost_usd"] for a in arm_names]
    ax.bar(arm_names, costs, color=[ARM_COLORS.get(a, "#888") for a in arm_names])
    ax.set_ylabel("USD")
    ax.set_title("Custo total por braço")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    charts["cost_per_arm"] = fig_to_base64(fig)

    return charts


def build_arm_table_rows(arms: dict, task_kind: str | None = None) -> str:
    """One comparison row per metric, one column per arm, plus an
    "Economia com simplicio" column (normal - simplicio, value and % of
    normal; negative = simplicio spent more). ``task_kind`` scopes every
    figure to that kind's tasks (create vs edit, same session)."""
    arm_names = list(arms)
    with_savings = "normal" in arms and "simplicio" in arms

    def scoped(arm_data):
        tasks = arm_data.get("tasks", [])
        if task_kind is not None:
            tasks = [t for t in tasks if t.get("kind") == task_kind]
        return {"tasks": tasks}

    metrics = []  # (label, {arm: raw number or text}, formatter or None for text)
    raw = {name: scoped(arms[name]) for name in arm_names}
    toks = {name: agg.token_totals(raw[name]) for name in arm_names}
    success = {name: "%d/%d" % agg.success_summary(raw[name]) for name in arm_names}
    metrics.append(("Tarefas concluídas", success, None))
    metrics.append(("Tempo (s)", {n: agg.task_wall(raw[n]) for n in arm_names}, lambda v: fmt(v, 1)))
    metrics.append(("Turnos de LLM", {n: agg.turns_stats(raw[n])[0] for n in arm_names}, lambda v: fmt(v, 0)))
    metrics.append(("Comandos executados", {
        n: sum((t.get("totals") or {}).get("n_commands") or 0 for t in raw[n]["tasks"]) for n in arm_names
    }, lambda v: fmt(v, 0)))
    metrics.append(("... dos quais simplicio-*", {n: agg.simplicio_command_count(raw[n]) for n in arm_names}, None))
    metrics.append(("CPU total (comandos, s)", {n: agg.cpu_ram(raw[n])[0] for n in arm_names}, lambda v: fmt(v, 2)))
    metrics.append(("Pico RAM (MB)", {n: agg.cpu_ram(raw[n])[1] for n in arm_names}, None))
    metrics.append(("Tokens prompt (não cacheado)", {n: toks[n]["prompt_uncached"] for n in arm_names}, lambda v: fmt(v, 0)))
    metrics.append(("Tokens prompt (cacheado)", {n: toks[n]["cached"] for n in arm_names}, None))
    metrics.append(("Tokens completion", {n: toks[n]["completion_non_reasoning"] for n in arm_names}, lambda v: fmt(v, 0)))
    metrics.append(("Tokens de raciocínio", {n: toks[n]["reasoning"] for n in arm_names}, lambda v: fmt(v, 0)))
    metrics.append(("Custo (USD)", {n: toks[n]["cost_usd"] for n in arm_names}, lambda v: "$" + fmt(v, 5)))
    metrics.append(("Invocações do checker pelo próprio agente", {n: agg.check_run_count(raw[n]) for n in arm_names}, None))

    header = "<tr><th>Métrica</th>" + "".join(f"<th>{html_escape(a)}</th>" for a in arm_names)
    header += "<th>Economia com simplicio</th></tr>\n" if with_savings else "</tr>\n"
    rows = []
    for label, values, formatter in metrics:
        cells = "".join(
            f"<td>{formatter(values[n]) if formatter and isinstance(values[n], (int, float)) else html_escape(values[n])}</td>"
            for n in arm_names
        )
        if with_savings:
            if formatter and isinstance(values["normal"], (int, float)) and isinstance(values["simplicio"], (int, float)):
                saved = agg.savings(values["normal"], values["simplicio"])
                pct = "n/a" if saved["pct"] is None else f"{saved['pct']:.1f}%"
                cells += f"<td>{formatter(saved['value'])} ({pct})</td>"
            else:
                cells += "<td></td>"
        rows.append(f"<tr><td>{label}</td>{cells}</tr>\n")
    return header + "".join(rows)


def build_timeline_table(arms: dict) -> str:
    """Per-arm, per-task command timeline: every bash-tool command the
    agent ran, in order, with its exit code and wall/CPU time."""
    rows = ""
    for arm_name, data in arms.items():
        for task in data.get("tasks", []):
            for cmd in task.get("commands", []):
                marker = " ★" if cmd.get("is_simplicio") else ""
                rows += (
                    f"<tr><td>{html_escape(arm_name)}</td><td>{task.get('index')}</td>"
                    f"<td><code>{html_escape(cmd.get('command'))}{marker}</code></td>"
                    f"<td>{html_escape(cmd.get('returncode'))}</td>"
                    f"<td>{fmt(cmd.get('wall_s'), 2)}</td><td>{fmt(cmd.get('cpu_s'), 2)}</td></tr>\n"
                )
    if not rows:
        return "<tr><td colspan='6'>nenhum comando registrado</td></tr>\n"
    return rows


def build_pricing_table(pricing_rows: list[dict]) -> str:
    """Render the fetched OpenRouter pricing (per-token USD, ``cost.py``'s
    ``pricing_table``). Empty when the pricing fetch failed."""
    if not pricing_rows:
        return "<tr><td colspan='7'>preço não disponível (falha ao consultar /api/v1/models)</td></tr>\n"
    rows = ""
    for row in pricing_rows:
        rows += (
            f"<tr><td>{html_escape(row.get('model'))}</td>"
            f"<td>{fmt(row.get('prompt'), 10)}</td>"
            f"<td>{fmt(row.get('completion'), 10)}</td>"
            f"<td>{fmt(row.get('input_cache_read'), 10)}</td>"
            f"<td>{fmt(row.get('input_cache_write'), 10)}</td>"
            f"<td>{fmt(row.get('internal_reasoning'), 10)}</td>"
            f"<td>{html_escape(row.get('fetched_at'))}</td></tr>\n"
        )
    return rows


def build_cost_table(cost_rows: list[dict]) -> str:
    """Render ``cost.py``'s ``cost_table``: settled-billed vs token-computed
    cost per arm/task-kind (issue #1335's cross-check), with the
    cache-savings breakdown and how many tasks in that bucket were flagged
    for a >10% divergence between the two."""
    if not cost_rows:
        return "<tr><td colspan='10'>sem dados de custo</td></tr>\n"
    rows = ""
    for row in cost_rows:
        flags = row.get("cost_flag_count") or 0
        flag_cell = f"<b>{flags}</b>" if flags else "0"
        rows += (
            f"<tr><td>{html_escape(row.get('arm'))}</td><td>{html_escape(row.get('kind'))}</td>"
            f"<td>${fmt(row.get('reported_cost_usd'), 6)}</td>"
            f"<td>${fmt(row.get('computed_cost_usd'), 6)}</td>"
            f"<td>${fmt(row.get('uncached_input_usd'), 6)}</td>"
            f"<td>${fmt(row.get('cached_input_usd'), 6)}</td>"
            f"<td>${fmt(row.get('output_usd'), 6)}</td>"
            f"<td>${fmt(row.get('cache_savings_usd'), 6)}</td>"
            f"<td>{fmt(row.get('cache_hit_pct'), 1)}%</td>"
            f"<td>{flag_cell}/{row.get('task_count') or 0}</td></tr>\n"
        )
    return rows


def build_per_call_cache_table(arms: dict) -> str:
    """Per-LLM-call prompt-cache breakdown (issue #1336): every
    ``llm_calls`` entry already carries its own ``prompt_tokens``/
    ``cached_tokens`` (OpenCode's own ``step_finish`` event, see
    ``opencode_agent.parse_run_events``) -- rendering one row per call, in
    order, lets a prefix break (a call whose cache hit % drops after a run
    of high-hit calls) be bisected to the exact turn instead of only seeing
    the task-level average the other tables show. The first call of a task
    (``turn == 1``, the largest -- it carries the system + skill prompt) is
    labeled distinctly from the rest, since this is specifically the call
    issue #1336's stable-workdir/session-pinning fixes target."""
    rows = ""
    for arm_name, data in arms.items():
        for task in data.get("tasks", []):
            for call in task.get("llm_calls") or []:
                if not call.get("ok", True):
                    continue
                prompt = call.get("prompt_tokens") or 0
                cached = call.get("cached_tokens") or 0
                hit_pct = (cached / prompt * 100.0) if prompt else 0.0
                turn = call.get("turn")
                label = "primeira chamada" if turn == 1 else "demais"
                rows += (
                    f"<tr><td>{html_escape(arm_name)}</td><td>{html_escape(task.get('index'))}</td>"
                    f"<td>{html_escape(turn)}</td><td>{html_escape(label)}</td>"
                    f"<td>{prompt}</td><td>{cached}</td>"
                    f"<td>{fmt(hit_pct, 1)}%</td></tr>\n"
                )
    if not rows:
        return "<tr><td colspan='7'>sem chamadas de LLM registradas</td></tr>\n"
    return rows


def first_cold_call(arms: dict, arm: str = "simplicio") -> dict | None:
    """Per-call prompt-cache gate (issue #1342, deepseek-harness
    ``request-cache.e2e.ts`` pattern): every LLM call of ``arm`` after the
    first one of its task must read some prompt cache. Returns the first
    call that did not (``cached_tokens == 0``), with the previous call's
    prompt size so the report can name the prefix change, or ``None``."""
    data = arms.get(arm) or {}
    for task in data.get("tasks", []):
        previous = None
        for call in task.get("llm_calls") or []:
            if not call.get("ok", True):
                continue
            if previous is not None and not (call.get("cached_tokens") or 0):
                prompt = call.get("prompt_tokens") or 0
                prev_prompt = previous.get("prompt_tokens") or 0
                cause = (
                    "prefixo encolheu (compactação/reescrita do prompt)" if prompt < prev_prompt
                    else "prefixo mudou antes do fim da chamada anterior (conteúdo volátil no topo ou troca de provedor)"
                )
                return {
                    "arm": arm, "task": task.get("index"), "turn": call.get("turn"),
                    "prompt_tokens": prompt, "previous_prompt_tokens": prev_prompt,
                    "cause": cause,
                }
            previous = call
    return None


def run_prefix_cache_miss(calls: list[dict]) -> dict | None:
    """DeepSeek harness ``request-cache.e2e.ts`` rule, over one run.

    The first recorded call may miss. Every later call must report
    ``cached_tokens > 0``. ``calls`` is the simplicio arm in order, across
    every task, not reset per task.
    """
    seen = [call for call in calls if call.get("ok", True)]
    for call in seen[1:]:
        if not (call.get("cached_tokens") or 0):
            return {
                "turn": call.get("turn"),
                "prompt_tokens": call.get("prompt_tokens") or 0,
                "cached_tokens": 0,
            }
    return None


def build_cold_call_note(arms: dict) -> str:
    cold = first_cold_call(arms)
    if cold is None:
        return "<p>Gate de cache por chamada: OK (toda chamada do simplicio após a 1ª leu cache).</p>"
    return (
        "<p><b>Gate de cache por chamada: FALHOU</b> — primeira chamada fria: "
        f"tarefa {html_escape(cold['task'])}, turno {html_escape(cold['turn'])} "
        f"({cold['prompt_tokens']} tokens de prompt; anterior {cold['previous_prompt_tokens']}). "
        f"Causa provável: {html_escape(cold['cause'])}.</p>"
    )


EFFORT_COLUMNS = ("default", "low", "medium", "high")


def build_effort_table(arms: dict) -> str:
    """Per-arm count of LLM calls at each reasoning-effort value (issue
    #1310 follow-up: ``agg.effort_counts``). Since issue #1325 moved both
    arms onto the real OpenCode CLI, every call reports ``reasoning_effort =
    None`` (bucketed as ``default``) -- OpenCode's ``--variant`` flag only
    picks a reasoning effort for the WHOLE ``opencode run`` invocation, not
    per internal LLM step, so this table is expected to show 100% ``default``
    for both arms; it is kept (not dropped) because it is real, non-empty
    data that documents this limitation rather than hiding it -- see
    STANDARD.md § OpenCode."""
    arm_names = list(arms)
    header = "<tr><th>braço</th>" + "".join(f"<th>{html_escape(c)}</th>" for c in EFFORT_COLUMNS) + "</tr>\n"
    rows = ""
    for name in arm_names:
        counts = agg.effort_counts(arms[name])
        cells = "".join(f"<td>{counts.get(c, 0)}</td>" for c in EFFORT_COLUMNS)
        rows += f"<tr><td>{html_escape(name)}</td>{cells}</tr>\n"
    if not rows:
        rows = f"<tr><td colspan='{1 + len(EFFORT_COLUMNS)}'>sem chamadas de LLM registradas</td></tr>\n"
    return header + rows


def build_history_table(current: dict, history: list[dict]) -> str:
    if not history:
        return "<tr><td colspan='3'>sem execuções anteriores nesta pasta de resultados</td></tr>\n"
    rows = ""
    for prev in history:
        deltas = agg.diff_history(current, prev)
        date = (prev.get("meta") or {}).get("date", "?")
        if not deltas:
            rows += f"<tr><td>{html_escape(date)}</td><td colspan='2'>formato incompatível, ignorado</td></tr>\n"
            continue
        for arm_name, d in deltas.items():
            delta = d.get("total_wall_s_delta")
            delta_s = f"{delta:+.1f}s" if isinstance(delta, (int, float)) else "n/d"
            rows += f"<tr><td>{html_escape(date)}</td><td>{html_escape(arm_name)}</td><td>{delta_s}</td></tr>\n"
    return rows


def build_kind_sections(arms: dict, is_batch: bool) -> str:
    """Create-only / edit-only tables. A batch run is one agent session for
    every task, so its LLM calls cannot be split per task -- say so instead
    of rendering an empty edit table; a task set with no task of a kind
    says so too."""
    if is_batch:
        return ("<p>Modo batch: criação e edição acontecem em <b>uma única sessão</b>, "
                "então turnos, tempo e custo não são separáveis por tarefa. Os números "
                "somente criação / somente edição estão no relatório sequencial do mesmo "
                "conjunto (ex.: <code>REPORT-t4.html</code>) e no resumo de "
                "<code>REPORT.html</code>.</p>")
    labels = {"create": ("Somente criação (mesma sessão)", "criação"),
              "edit": ("Somente edição (mesma sessão)", "edição")}
    present = {t.get("kind") for a in arms.values() for t in a.get("tasks", [])}
    out = []
    for kind, (title, noun) in labels.items():
        if kind in present:
            out.append(f"<h3>{html_escape(title)}</h3>"
                       f"<table class='compare'>{build_arm_table_rows(arms, task_kind=kind)}</table>")
        else:
            out.append(f"<p>Este conjunto não tem tarefa de {noun}.</p>")
    return "".join(out)


def build(results: dict, results_dir: str, current_path: str | None = None) -> str:
    meta = results.get("meta", {})
    arms = results.get("arms", {})
    charts = build_charts(arms)
    verdict_text = bench_verdict.compute_verdict(results)
    task_count = meta.get("task_count")
    history = agg.load_history(results_dir, exclude_path=current_path, task_count=task_count)

    versions_html = "".join(
        f"<span class='pill'>{html_escape(k)} {html_escape(v)}</span> "
        for k, v in (meta.get("pip_versions") or {}).items()
    )

    kind_sections = build_kind_sections(arms, bool(meta.get("batch")))

    # Recomputed fresh from this run's own `meta.pricing`, never trusted
    # straight off the stored `results["cost_report"]` (issue #1335): an
    # OLDER result's stored cost_table predates `computed_cost_usd`/
    # `cost_flag_count`, so trusting it verbatim silently drops the
    # cross-check on a `--reports-only` re-render. `cost.cost_table` is
    # pure over `results`/`pricing`, so recomputing it here is free and
    # always current -- it never edits the stored results file.
    pricing = meta.get("pricing") or {}
    pricing_rows_html = build_pricing_table(bench_cost.pricing_table(pricing))
    cost_rows_html = build_cost_table(bench_cost.cost_table(results, pricing))
    is_batch = bool(meta.get("batch"))
    mode_label = "batch (todas as tarefas em uma sessão)" if is_batch else "sequencial (uma sessão por tarefa)"
    effort_policy_label = meta.get("effort_policy") or "opencode-managed"
    effort_table_html = build_effort_table(arms)
    per_call_cache_html = build_per_call_cache_table(arms)
    cold_call_note_html = build_cold_call_note(arms)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Benchmark A/B: agente com vs sem a skill simplicio-loop</title>
<style>
  :root {{ --bg: #ffffff; --fg: #1a1a1a; --muted: #666; --border: #ddd; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--fg); margin: 0; padding: 16px 20px;
    font-size: 13px; max-width: 1150px; margin: 0 auto;
  }}
  h1 {{ font-size: 18px; margin: 4px 0 2px; }}
  h2 {{ font-size: 14px; margin: 16px 0 6px; border-bottom: 1px solid var(--border); padding-bottom: 3px; }}
  h3 {{ font-size: 12.5px; margin: 10px 0 4px; color: var(--muted); }}
  .meta {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
  .pill {{ display: inline-block; background: #f0f0f0; border-radius: 10px; padding: 1px 8px; margin: 2px 2px 2px 0; font-size: 11px; }}
  .verdict {{ background: #f6f8fa; border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; font-size: 12px; margin: 6px 0 10px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-bottom: 8px; }}
  table.compare th, table.compare td {{ border: 1px solid var(--border); padding: 3px 8px; text-align: right; }}
  table.compare th:first-child, table.compare td:first-child {{ text-align: left; }}
  table.compare th {{ background: #fafafa; }}
  table.timeline th, table.timeline td, table.history th, table.history td {{
    border: 1px solid var(--border); padding: 3px 8px; text-align: left; font-size: 11.5px;
  }}
  table.timeline th, table.history th {{ background: #fafafa; }}
  .charts {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0; }}
  .charts img {{ border: 1px solid var(--border); border-radius: 4px; max-width: 32%; }}
  footer {{ color: var(--muted); font-size: 10.5px; margin-top: 10px; }}
  code {{ font-size: 11px; }}
</style>
</head>
<body>
  <h1>Benchmark A/B: mesmo agente, com vs sem a skill simplicio-loop</h1>
  <div class="meta">
    Modelo: <b>{html_escape(meta.get('model', '?'))}</b> &nbsp;·&nbsp;
    Data: {html_escape(meta.get('date', '?'))} &nbsp;·&nbsp;
    Commit (main): <code>{html_escape((meta.get('main_commit') or '?').split()[0] if meta.get('main_commit') else '?')}</code>
    &nbsp;·&nbsp; Modo: <b>{html_escape(mode_label)}</b>
    &nbsp;·&nbsp; Política de esforço: <code>{html_escape(effort_policy_label)}</code>
  </div>
  <div class="meta">{versions_html}</div>
  <div class="verdict"><b>Veredito:</b> {html_escape(verdict_text)}</div>

  <h2>Comparação geral (agente normal vs agente com a skill simplicio-loop)</h2>
  <table class="compare">{build_arm_table_rows(arms)}</table>

  <h2>Esforço de raciocínio por chamada de LLM (plan alto / execute baixo / review médio)</h2>
  <table class="compare">{effort_table_html}</table>

  <h2>Somente criação e somente edição (tarefas da mesma sessão)</h2>
  {kind_sections}

  <h2>Preço por token (OpenRouter, ao vivo)</h2>
  <table class="compare">
    <tr><th>modelo</th><th>prompt</th><th>completion</th><th>cache read</th>
        <th>cache write</th><th>raciocínio interno</th><th>obtido em</th></tr>
    {pricing_rows_html}
  </table>

  <h2>Custo real: cobrado (delta assentado) vs calculado pelos tokens (cache-aware)</h2>
  <p class="meta">Cobrado = delta assentado da chave OpenRouter (issue #1335: assentado é
    ``GET /api/v1/key`` sem variar por 3 leituras seguidas, nunca o primeiro movimento) ou,
    quando o uso nunca assenta, o próprio custo calculado (``cost_source =
    computed-from-tokens``). Sinalizados = tarefas cujo custo cobrado divergiu do calculado
    em mais de 10%.</p>
  <table class="compare">
    <tr><th>braço</th><th>tipo</th><th>cobrado</th><th>calculado</th>
        <th>entrada não cacheada</th><th>entrada cacheada</th><th>saída</th>
        <th>economia de cache</th><th>hit % de cache</th><th>sinalizados</th></tr>
    {cost_rows_html}
  </table>

  {cold_call_note_html}

  <h2>Cache por chamada de LLM (bisecção de quebras de prefixo, issue #1336)</h2>
  <p class="meta">Uma linha por chamada real ao provedor (evento ``step_finish`` do OpenCode).
    "primeira chamada" (turno 1) carrega o prompt de sistema + skill inteiro e é o alvo direto
    das correções de caminho estável / ``session_id`` do OpenRouter; "demais" são os turnos
    seguintes da mesma tarefa.</p>
  <table class="compare">
    <tr><th>braço</th><th>tarefa</th><th>turno</th><th>chamada</th>
        <th>tokens de prompt</th><th>tokens cacheados</th><th>hit % de cache</th></tr>
    {per_call_cache_html}
  </table>

  <h2>Gráficos</h2>
  <div class="charts">
    <img src="data:image/png;base64,{charts['wall_per_arm']}" alt="tempo total por braço">
    <img src="data:image/png;base64,{charts['tokens_stacked']}" alt="tokens empilhados">
    <img src="data:image/png;base64,{charts['cost_per_arm']}" alt="custo por braço">
  </div>

  <h2>Linha do tempo de comandos (por braço, por tarefa)</h2>
  <table class="timeline">
    <tr><th>braço</th><th>tarefa</th><th>comando</th><th>rc</th><th>parede (s)</th><th>CPU (s)</th></tr>
    {build_timeline_table(arms)}
  </table>
  <p class="meta">★ = comando simplicio-loop/mapper/dev-cli/fast.</p>

  <h2>Histórico (comparação com execuções anteriores)</h2>
  <table class="history">
    <tr><th>execução anterior</th><th>braço</th><th>Δ tempo total</th></tr>
    {build_history_table(results, history)}
  </table>

  <footer>
    Gerado automaticamente a partir de results.json (dados reais, sem números fabricados).
    Nenhuma chave de API foi impressa ou registrada neste relatório.
  </footer>
</body>
</html>
"""
    return html


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", required=True, help="path to the results.json to render")
    ap.add_argument("--out", required=True, help="path to write REPORT.html")
    args = ap.parse_args()

    with open(args.results) as f:
        results = json.load(f)
    results_dir = os.path.dirname(os.path.abspath(args.results))
    html = build(results, results_dir, current_path=args.results)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

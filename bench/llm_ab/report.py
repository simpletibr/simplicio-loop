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
    """One comparison table row per metric, one column per arm. When
    ``task_kind`` is given, figures are scoped to just that kind's tasks
    (create vs edit split)."""
    arm_names = list(arms)
    rows = []

    def row(label, values):
        cells = "".join(f"<td>{v}</td>" for v in values)
        return f"<tr><td>{label}</td>{cells}</tr>\n"

    def scoped_tasks(arm_data):
        tasks = arm_data.get("tasks", [])
        if task_kind is None:
            return tasks
        return [t for t in tasks if t.get("kind") == task_kind]

    def scoped_arm(arm_data):
        return {"tasks": scoped_tasks(arm_data)}

    success_vals, turns_vals, wall_vals, cpu_vals, rss_vals = [], [], [], [], []
    prompt_vals, cached_vals, compl_vals, reason_vals, cost_vals = [], [], [], [], []
    cmd_vals, simplicio_cmd_vals, check_vals = [], [], []
    for name in arm_names:
        scoped = scoped_arm(arms[name])
        n_success, n_tasks = agg.success_summary(scoped)
        success_vals.append(f"{n_success}/{n_tasks}")
        total_turns, _first_try, _n = agg.turns_stats(scoped)
        turns_vals.append(total_turns)
        cpu_total, peak_rss = agg.cpu_ram(scoped)
        cpu_vals.append(fmt(cpu_total, 2))
        rss_vals.append(fmt(peak_rss, 1))
        tok = agg.token_totals(scoped)
        prompt_vals.append(tok["prompt_uncached"])
        cached_vals.append(tok["cached"])
        compl_vals.append(tok["completion_non_reasoning"])
        reason_vals.append(tok["reasoning"])
        cost_vals.append(f"${fmt(tok['cost_usd'], 5)}")
        cmd_vals.append(sum((t.get("totals") or {}).get("n_commands") or 0 for t in scoped["tasks"]))
        simplicio_cmd_vals.append(agg.simplicio_command_count(scoped))
        check_vals.append(agg.check_run_count(scoped))
        if task_kind is None:
            wall_vals.append(fmt(arms[name].get("total_wall_s"), 1))

    rows.append(row("Tarefas concluídas", success_vals))
    if task_kind is None:
        rows.append(row("Tempo total (parede, s)", wall_vals))
    rows.append(row("Turnos de LLM", turns_vals))
    rows.append(row("Comandos executados", cmd_vals))
    rows.append(row("... dos quais simplicio-*", simplicio_cmd_vals))
    rows.append(row("CPU total (comandos, s)", cpu_vals))
    rows.append(row("Pico RAM (MB)", rss_vals))
    rows.append(row("Tokens prompt (não cacheado)", prompt_vals))
    rows.append(row("Tokens prompt (cacheado)", cached_vals))
    rows.append(row("Tokens completion", compl_vals))
    rows.append(row("Tokens de raciocínio", reason_vals))
    rows.append(row("Custo (USD)", cost_vals))
    rows.append(row("Invocações do checker pelo próprio agente", check_vals))
    header = "<tr><th>Métrica</th>" + "".join(f"<th>{html_escape(a)}</th>" for a in arm_names) + "</tr>\n"
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
    """Render ``cost.py``'s ``cost_table``: reported vs computed cost per
    arm/task-kind, with the cache-savings breakdown."""
    if not cost_rows:
        return "<tr><td colspan='9'>sem dados de custo</td></tr>\n"
    rows = ""
    for row in cost_rows:
        rows += (
            f"<tr><td>{html_escape(row.get('arm'))}</td><td>{html_escape(row.get('kind'))}</td>"
            f"<td>${fmt(row.get('reported_cost_usd'), 6)}</td>"
            f"<td>${fmt(row.get('computed_cost_usd'), 6)}</td>"
            f"<td>${fmt(row.get('uncached_input_usd'), 6)}</td>"
            f"<td>${fmt(row.get('cached_input_usd'), 6)}</td>"
            f"<td>${fmt(row.get('output_usd'), 6)}</td>"
            f"<td>${fmt(row.get('cache_savings_usd'), 6)}</td>"
            f"<td>{fmt(row.get('cache_hit_pct'), 1)}%</td></tr>\n"
        )
    return rows


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

    kinds = sorted({t.get("kind") for a in arms.values() for t in a.get("tasks", []) if t.get("kind")})
    kind_labels = {"create": "Tarefas de criação", "edit": "Tarefas de edição"}
    kind_sections = "".join(
        f"<h3>{html_escape(kind_labels.get(k, k))}</h3>"
        f"<table class='compare'>{build_arm_table_rows(arms, task_kind=k)}</table>"
        for k in kinds
    )

    cost_report = results.get("cost_report") or {}
    pricing_rows_html = build_pricing_table(cost_report.get("pricing_table") or [])
    cost_rows_html = build_cost_table(cost_report.get("cost_table") or [])

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
  </div>
  <div class="meta">{versions_html}</div>
  <div class="verdict"><b>Veredito:</b> {html_escape(verdict_text)}</div>

  <h2>Comparação geral (agente normal vs agente com a skill simplicio-loop)</h2>
  <table class="compare">{build_arm_table_rows(arms)}</table>

  <h2>Por tipo de tarefa (criação vs edição)</h2>
  {kind_sections}

  <h2>Preço por token (OpenRouter, ao vivo)</h2>
  <table class="compare">
    <tr><th>modelo</th><th>prompt</th><th>completion</th><th>cache read</th>
        <th>cache write</th><th>raciocínio interno</th><th>obtido em</th></tr>
    {pricing_rows_html}
  </table>

  <h2>Custo real: reportado vs calculado (cache-aware)</h2>
  <table class="compare">
    <tr><th>braço</th><th>tipo</th><th>reportado</th><th>calculado</th>
        <th>entrada não cacheada</th><th>entrada cacheada</th><th>saída</th>
        <th>economia de cache</th><th>hit % de cache</th></tr>
    {cost_rows_html}
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

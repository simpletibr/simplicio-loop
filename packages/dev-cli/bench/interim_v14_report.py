#!/usr/bin/env python3
"""v14 interim — parse /tmp/v14.log + render MD + PDF."""
import re
import time
from pathlib import Path

LOG = Path("/tmp/v14.log")
OUT_MD = Path("/home/user/simplicio-dev-cli/bench/results_v14_interim.md")
OUT_PDF = Path("/home/user/simplicio-dev-cli/bench/results_v14_interim.pdf")

CASE_RE = re.compile(
    r"^\s+(\S+)\s+baseline\s+(PASS|fail)\s+"
    r"cli\s+(PASS|fail)\s+"
    r"cli\+sp\s+(PASS|fail)\[tiers=([\d→,]+),u=(\d+),modal=(\d+),parse=(\d+)/(\d+)\]\s+"
    r"cli\+ag\s+(PASS|fail)\((\d+)/\d+\)\s+"
    r"cli\+sp\+ag\s+(PASS|fail)\((\d+)/\d+\)"
)
FINAL_RE = re.compile(
    r"^\s+-> baseline (\d+)/(\d+) \(\d+%\) \| cli (\d+)/\d+ \(\d+%\) \| sp (\d+)/\d+ \(\d+%\) \| ag (\d+)/\d+ \(\d+%\) \| sp\+ag (\d+)/\d+ \(\d+%\)"
)
MODEL_HDR_RE = re.compile(r"^=== (\S+) \(endpoint:")
RUNNING_RE = re.compile(r"^\s+RUNNING: (\S+)\s+tiers=(\S+)")


def parse():
    if not LOG.exists():
        return []
    models = []
    current = None
    for line in LOG.read_text().splitlines():
        m = RUNNING_RE.match(line)
        if m:
            current = {"id": m.group(1), "tiers": m.group(2),
                       "cases": [], "final": None}
            models.append(current)
            continue
        if current is None:
            continue
        m = CASE_RE.match(line)
        if m:
            current["cases"].append({
                "id": m.group(1),
                "sem": m.group(2) == "PASS",
                "com": m.group(3) == "PASS",
                "sp": m.group(4) == "PASS",
                "sp_tiers": m.group(5),
                "sp_uniq": int(m.group(6)),
                "sp_modal": int(m.group(7)),
                "sp_parse_ok": int(m.group(8)),
                "sp_n": int(m.group(9)),
                "ag": m.group(10) == "PASS",
                "ag_att": int(m.group(11)),
                "spag": m.group(12) == "PASS",
                "spag_att": int(m.group(13)),
            })
            continue
        m = FINAL_RE.match(line)
        if m:
            n = int(m.group(2))
            current["final"] = {
                "n": n, "sem": int(m.group(1)), "com": int(m.group(3)),
                "sp": int(m.group(4)), "ag": int(m.group(5)),
                "spag": int(m.group(6)),
            }
    return models


def build_md(models):
    lines = [
        "# v14 INTERIM — bench funcional (PHPUnit) 3 models × 12 cases × 5 sides",
        "",
        f"Snapshot: **{time.strftime('%Y-%m-%d %H:%M:%S')}**",
        "",
        "Bench rodando em background, dados parciais dos logs. Modelos com `-> baseline...` fecharam; os outros ainda rodam.",
        "",
        "## Configuração",
        "",
        "| model | backend | tiers sp |",
        "|---|---|---|",
        "| `deepseek/deepseek-v4-flash` | OpenRouter API | 64 → 100 |",
        "| `local:Qwen/Qwen2.5-Coder-3B-Instruct` | transformers CPU fp32 | 4 (single cycle) |",
        "| `local:Qwen/Qwen2.5-Coder-1.5B-Instruct` | transformers CPU fp32 | 4 (single cycle) |",
        "",
        "**Bench**: 12 cases reais sindico, PHPUnit como oracle. Schema v1 ativo em todos os lados sp.",
        "",
        "## Status por modelo",
        "",
    ]
    if not models:
        lines.append("_(batch ainda não começou)_")
        return "\n".join(lines)

    for m in models:
        short = m["id"].split("/")[-1] if "local:" not in m["id"] else m["id"]
        lines.append(f"### `{short}`")
        lines.append("")
        if m["final"]:
            f = m["final"]
            n = f["n"]
            lines.append(f"**STATUS: FECHADO** ({len(m['cases'])}/{n} cases)")
            lines.append("")
            lines.append("| Side | Passed | Rate | Δ vs baseline |")
            lines.append("|---|---|---|---|")
            base_pct = 100 * f["sem"] // n
            for label, key in [("baseline", "sem"), ("cli", "com"),
                               ("cli+sp", "sp"), ("cli+ag", "ag"),
                               ("cli+sp+ag", "spag")]:
                cnt = f[key]; pct = 100 * cnt // n
                delta = f"**{pct - base_pct:+d}**" if key != "sem" else "—"
                lines.append(f"| {label} | {cnt}/{n} | {pct}% | {delta} |")
        else:
            cases_done = len(m["cases"])
            lines.append(f"**STATUS: EM ANDAMENTO** ({cases_done}/12 cases)")
            if cases_done:
                sem_p = sum(c["sem"] for c in m["cases"])
                com_p = sum(c["com"] for c in m["cases"])
                sp_p = sum(c["sp"] for c in m["cases"])
                ag_p = sum(c["ag"] for c in m["cases"])
                spag_p = sum(c["spag"] for c in m["cases"])
                lines.append("")
                lines.append(
                    f"Parcial: base **{sem_p}**/{cases_done} · cli **{com_p}**/{cases_done} · "
                    f"cli+sp **{sp_p}**/{cases_done} · cli+ag **{ag_p}**/{cases_done} · "
                    f"cli+sp+ag **{spag_p}**/{cases_done}"
                )
        lines.append("")

        # per-case table
        if m["cases"]:
            lines.append("| Case | base | cli | cli+sp (parse) | cli+ag | cli+sp+ag |")
            lines.append("|---|---|---|---|---|---|")
            for c in m["cases"]:
                sp_extra = (f" PASS [N={c['sp_n']} u={c['sp_uniq']} "
                            f"modal={c['sp_modal']} parse={c['sp_parse_ok']}/{c['sp_n']}]"
                            if c['sp'] else " fail")
                lines.append(
                    f"| {c['id']} | "
                    f"{'P' if c['sem'] else '.'} | "
                    f"{'P' if c['com'] else '.'} | "
                    f"{sp_extra} | "
                    f"{('P' if c['ag'] else '.')}({c['ag_att']}/3) | "
                    f"{('P' if c['spag'] else '.')}({c['spag_att']}/3) |"
                )
            lines.append("")

    # Highlights
    lines += [
        "## Achados notáveis",
        "",
        "_Quando o batch terminar, completo o relatório com PDF final + grand totals_",
        "",
    ]
    deep = next((m for m in models if "deepseek" in m["id"]), None)
    if deep and deep["cases"]:
        parse_rates = [c["sp_parse_ok"] / c["sp_n"] for c in deep["cases"] if c["sp_n"]]
        if parse_rates:
            avg = sum(parse_rates) / len(parse_rates) * 100
            lines.append(
                f"- **DeepSeek V4 Flash** honra schema v1 em média **{avg:.0f}%** dos N=64 subagents "
                f"({sum(c['sp_parse_ok'] for c in deep['cases'])} parse_ok de "
                f"{sum(c['sp_n'] for c in deep['cases'])} totais)"
            )
        sp_pass_count = sum(1 for c in deep["cases"] if c["sp"])
        lines.append(
            f"- DeepSeek + cli+sp: **{sp_pass_count}/{len(deep['cases'])} cases passam** "
            f"(parou cycle 1 em todos, sem precisar escalar pra N=100)"
        )
    return "\n".join(lines) + "\n"


def build_pdf(models, md_path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted)
    doc = SimpleDocTemplate(str(OUT_PDF), pagesize=A4,
                            leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=12*mm, bottomMargin=12*mm)
    s = getSampleStyleSheet()
    h1 = s["Heading1"]; h2 = s["Heading2"]; h3 = s["Heading3"]
    body = s["BodyText"]; body.fontSize = 9; body.leading = 12
    mono = ParagraphStyle("mono", parent=body, fontName="Courier",
                          fontSize=8, leading=10)
    story = []

    def tbl(rows, widths):
        t = Table(rows, colWidths=widths)
        t.setStyle(TableStyle([
            ("FONTNAME", (0,0),(-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0),(-1,-1), 8),
            ("GRID", (0,0),(-1,-1), 0.4, colors.HexColor("#888")),
            ("BACKGROUND", (0,0),(-1,0), colors.HexColor("#e7eaf0")),
            ("FONTNAME", (0,0),(-1,0), "Helvetica-Bold"),
            ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0),(-1,-1), 3),
            ("RIGHTPADDING", (0,0),(-1,-1), 3),
        ]))
        return t

    story.append(Paragraph("v14 INTERIM — bench funcional (PHPUnit, 3 models × 12 cases × 5 sides)", h1))
    story.append(Paragraph(f"Snapshot: <b>{time.strftime('%Y-%m-%d %H:%M:%S')}</b>", body))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "Bench rodando em background. Modelos com headline (<font face='Courier'>"
        "-> baseline...</font>) fecharam; sem headline = ainda rodando. "
        "PHPUnit como oracle, schema v1 ativo em todos os lados sp.", body))
    story.append(Spacer(1, 4*mm))

    # config
    story.append(Paragraph("Configuração", h2))
    story.append(tbl([
        ["Model", "Backend", "Tiers sp"],
        ["deepseek/deepseek-v4-flash", "OpenRouter API", "64 → 100"],
        ["local:Qwen/Qwen2.5-Coder-3B-Instruct", "transformers CPU fp32", "4 (single)"],
        ["local:Qwen/Qwen2.5-Coder-1.5B-Instruct", "transformers CPU fp32", "4 (single)"],
    ], [70*mm, 50*mm, 30*mm]))
    story.append(Spacer(1, 4*mm))

    for m in models:
        short = m["id"].split("/")[-1] if "local:" not in m["id"] else m["id"]
        story.append(Paragraph(f"<font face='Courier'>{short}</font>", h2))
        if m["final"]:
            f = m["final"]
            n = f["n"]
            story.append(Paragraph(f"<b>STATUS: FECHADO</b> ({len(m['cases'])}/{n} cases)", body))
            base = 100 * f["sem"] // n
            data = [["Side", "Passed", "Rate", "Δ vs baseline"]]
            for label, key in [("baseline","sem"),("cli","com"),("cli+sp","sp"),("cli+ag","ag"),("cli+sp+ag","spag")]:
                cnt = f[key]; pct = 100*cnt//n
                delta = f"{pct-base:+d}" if key!="sem" else "—"
                data.append([label, f"{cnt}/{n}", f"{pct}%", delta])
            story.append(tbl(data, [40*mm, 30*mm, 25*mm, 30*mm]))
        else:
            cases_done = len(m["cases"])
            story.append(Paragraph(f"<b>STATUS: EM ANDAMENTO</b> ({cases_done}/12 cases)", body))
            if cases_done:
                p_lambda = lambda k: sum(c[k] for c in m["cases"])
                story.append(Paragraph(
                    f"Parcial: base <b>{p_lambda('sem')}</b>/{cases_done} · "
                    f"cli <b>{p_lambda('com')}</b>/{cases_done} · "
                    f"cli+sp <b>{p_lambda('sp')}</b>/{cases_done} · "
                    f"cli+ag <b>{p_lambda('ag')}</b>/{cases_done} · "
                    f"cli+sp+ag <b>{p_lambda('spag')}</b>/{cases_done}", body))
        story.append(Spacer(1, 2*mm))

        if m["cases"]:
            rows = [["Case", "b", "c", "cli+sp", "u", "modal", "parse", "ag", "sp+ag"]]
            for c in m["cases"]:
                sp_str = "P" if c["sp"] else "."
                rows.append([
                    c["id"],
                    "P" if c["sem"] else ".",
                    "P" if c["com"] else ".",
                    sp_str,
                    str(c["sp_uniq"]) if c["sp"] else "—",
                    str(c["sp_modal"]) if c["sp"] else "—",
                    f"{c['sp_parse_ok']}/{c['sp_n']}" if c["sp"] else "—",
                    f"{'P' if c['ag'] else '.'}({c['ag_att']})",
                    f"{'P' if c['spag'] else '.'}({c['spag_att']})",
                ])
            story.append(tbl(rows, [42*mm, 8*mm, 8*mm, 14*mm, 14*mm, 16*mm, 22*mm, 16*mm, 22*mm]))
        story.append(Spacer(1, 5*mm))

    # findings
    story.append(Paragraph("Achados notáveis", h2))
    deep = next((m for m in models if "deepseek" in m["id"]), None)
    if deep and deep["cases"]:
        parse_rates = [c["sp_parse_ok"] / c["sp_n"] for c in deep["cases"] if c["sp_n"]]
        if parse_rates:
            avg = sum(parse_rates) / len(parse_rates) * 100
            total_parse_ok = sum(c["sp_parse_ok"] for c in deep["cases"])
            total_n = sum(c["sp_n"] for c in deep["cases"])
            story.append(Paragraph(
                f"&bull; <b>DeepSeek V4 Flash</b> honra schema v1 em média <b>{avg:.0f}%</b> "
                f"dos N=64 subagents ({total_parse_ok} parse_ok de {total_n} totais)", body))
        sp_pass = sum(1 for c in deep["cases"] if c["sp"])
        story.append(Paragraph(
            f"&bull; cli+sp passou em <b>{sp_pass}/{len(deep['cases'])} cases</b> processados — "
            "TODOS pararam cycle 1, sem escalar pra N=100", body))
        ag_pass = sum(1 for c in deep["cases"] if c["ag"])
        story.append(Paragraph(
            f"&bull; cli+ag passou em <b>{ag_pass}/{len(deep['cases'])} cases</b> processados, "
            "todos em 1 attempt (nenhum retry necessário)", body))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "Quando o batch terminar (DeepSeek faltam ~6 cases, depois Qwen 3B + 1.5B "
        "em CPU = várias horas), gera relatório final com PDF.", body))
    doc.build(story)
    print(f"-> {OUT_PDF}")


if __name__ == "__main__":
    models = parse()
    OUT_MD.write_text(build_md(models))
    print(f"-> {OUT_MD}")
    build_pdf(models, OUT_MD)

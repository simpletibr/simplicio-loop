#!/usr/bin/env python3
"""Gera uma composição hyperframes 0.7.x DINÂMICA (HTML→MP4 determinístico) por idioma.

Movimento real via GSAP: transições whip, contadores cinéticos, DAG animado, partículas,
pipeline em cascata, lock que bate, órbita de runtimes. Lê:
  video/storyboard.master.json  (visual/efeitos/timing)
  video/lang/<lang>.json        (caption/narração por cena)
Escreve video/hyperframes/<lang>/index.html.

Contrato hyperframes 0.7.x (espelhado de scripts/video_evidence.py):
  #root[data-composition-id="main"][data-start][data-duration][data-width][data-height]
  .clip#sN[data-start][data-duration][data-track-index]  (gated pelo framework)
  timeline GSAP pausada em window.__timelines["main"]; cada exit tem hard-kill tl.set(opacity:0)

Uso:
    python3 video/build_composition.py            # todos
    python3 video/build_composition.py pt-BR      # subconjunto
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LANG_DIR = HERE / "lang"
OUT_DIR = HERE / "hyperframes"
LANGS = ["en", "zh-CN", "es", "pt-BR"]
W, H = 1920, 1080


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def g(x):
    return "%g" % float(x)


# ---------- per-scene rich visuals: returns (inner_html, gsap_lines) ----------
def scene_hook(sid, t, d, cap, chip):
    html = (
        '<div class="ring" id="ring%d"></div>'
        '<div class="biginf" id="inf%d">&#8734;</div>'
        '<div class="cap big" id="c%d">%s</div>'
        '<div class="chip" id="d%d">%s</div>' % (sid, sid, sid, cap, sid, chip))
    j = [
        anim_in(sid, t),
        'tl.fromTo("#inf%d",{scale:0,rotation:-90,opacity:0},{scale:1,rotation:0,opacity:1,duration:0.9,ease:"back.out(2)"},%s);' % (sid, g(t + 0.1)),
        'tl.to("#inf%d",{rotation:360,duration:%s,ease:"none"},%s);' % (sid, g(d - 0.4), g(t + 0.2)),
        'tl.fromTo("#ring%d",{scale:0.2,opacity:0},{scale:1.4,opacity:0.0,duration:%s,ease:"power1.out",repeat:%d},%s);' % (sid, g(2.2), max(1, int(d // 2)), g(t + 0.2)),
        text_in(sid, t + 0.5),
        chip_in(sid, t + 0.8),
        anim_out(sid, t, d),
    ]
    return html, j


def scene_problem(sid, t, d, cap, chip):
    cards = "".join('<div class="qcard" id="q%d_%d">%s</div>' % (sid, i, lbl)
                    for i, lbl in enumerate(["GitHub Issues", "CI failures", "Jira", "Azure DevOps"]))
    html = (
        '<div class="stack" id="st%d">%s</div>'
        '<div class="costbar"><div class="costfill" id="cf%d"></div>'
        '<div class="costnum" id="cn%d">$0</div></div>'
        '<div class="cap" id="c%d">%s</div>'
        '<div class="chip" id="d%d">%s</div>' % (sid, cards, sid, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t)]
    for i in range(4):
        j.append('tl.fromTo("#q%d_%d",{y:-120,opacity:0},{y:0,opacity:1,duration:0.4,ease:"bounce.out"},%s);'
                 % (sid, i, g(t + 0.2 + i * 0.18)))
    j += [
        'tl.fromTo("#cf%d",{scaleY:0},{scaleY:1,duration:%s,ease:"power1.in",transformOrigin:"bottom"},%s);' % (sid, g(d - 1.5), g(t + 0.6)),
        count(sid, t + 0.6, d - 1.5, 0, 9999, "#cn%d" % sid, prefix="$"),
        text_in(sid, t + 0.4), chip_in(sid, t + 0.9), anim_out(sid, t, d),
    ]
    return html, j


def scene_preflight(sid, t, d, cap, chip):
    rows = ["source auth  gh", "runtime/tools  ready", "STOP path  armed"]
    html = '<div class="checks">' + "".join(
        '<div class="crow" id="r%d_%d"><span class="ck" id="ck%d_%d">&#10003;</span>%s</div>'
        % (sid, i, sid, i, r) for i, r in enumerate(rows)) + "</div>"
    html += '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>' % (sid, cap, sid, chip)
    j = [anim_in(sid, t)]
    for i in range(3):
        j.append('tl.fromTo("#r%d_%d",{x:-80,opacity:0},{x:0,opacity:1,duration:0.4},%s);' % (sid, i, g(t + 0.3 + i * 0.5)))
        j.append('tl.fromTo("#ck%d_%d",{scale:0},{scale:1,duration:0.4,ease:"back.out(3)"},%s);' % (sid, i, g(t + 0.5 + i * 0.5)))
    j += [text_in(sid, t + 0.2), chip_in(sid, t + 2.0), anim_out(sid, t, d)]
    return html, j


def scene_discover(sid, t, d, cap, chip):
    # SVG DAG: 6 nós + 5 arestas com stroke-draw
    nodes = [(180, 120), (360, 60), (360, 200), (560, 110), (560, 240), (740, 170)]
    edges = [(0, 1), (0, 2), (1, 3), (2, 4), (3, 5), (4, 5)]
    svg = ['<svg class="dag" viewBox="0 0 900 320" id="dag%d">' % sid]
    for i, (a, b) in enumerate(edges):
        x1, y1 = nodes[a]; x2, y2 = nodes[b]
        svg.append('<line id="e%d_%d" x1="%d" y1="%d" x2="%d" y2="%d" stroke="#2563EB" stroke-width="3"/>' % (sid, i, x1, y1, x2, y2))
    for i, (x, y) in enumerate(nodes):
        svg.append('<circle id="n%d_%d" cx="%d" cy="%d" r="20" fill="#0B0E14" stroke="#00E08A" stroke-width="3"/>' % (sid, i, x, y))
    svg.append("</svg>")
    html = ("".join(svg) +
            '<div class="stats"><span class="bignum" id="iss%d">0</span> issues &#183; dedup &#183; '
            'fleet <span class="bignum" id="fl%d">0</span></div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t)]
    for i in range(6):
        j.append('tl.fromTo("#n%d_%d",{scale:0,transformOrigin:"center"},{scale:1,duration:0.3,ease:"back.out(3)"},%s);' % (sid, i, g(t + 0.3 + i * 0.12)))
    for i, (a, b) in enumerate(edges):
        x1, y1 = nodes[a]; x2, y2 = nodes[b]
        ln = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        j.append('gsap.set("#e%d_%d",{strokeDasharray:%d,strokeDashoffset:%d});' % (sid, i, int(ln), int(ln)))
        j.append('tl.to("#e%d_%d",{strokeDashoffset:0,duration:0.5,ease:"power1.inOut"},%s);' % (sid, i, g(t + 1.0 + i * 0.1)))
    j += [
        count(sid, t + 0.4, 1.6, 0, 50, "#iss%d" % sid),
        'var fp%d={v:0};tl.to(fp%d,{v:14,duration:1.4,ease:"power1.out",onUpdate:function(){document.getElementById("fl%d").textContent=Math.round(fp%d.v);}},%s);' % (sid, sid, sid, sid, g(t + 1.6)),
        text_in(sid, t + 0.3), chip_in(sid, t + 2.4), anim_out(sid, t, d),
    ]
    return html, j


def scene_cycle(sid, t, d, cap, chip):
    stages = ["read", "orient", "plan", "edit", "RUN", "verify", "PR"]
    chips = "".join('<div class="pstage%s" id="p%d_%d">%s</div>'
                    % (" run" if s == "RUN" else "", sid, i, s) for i, s in enumerate(stages))
    html = ('<div class="pipe">%s</div><div class="stamp" id="stmp%d">WORKS<span>not just compiles</span></div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (chips, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t)]
    for i in range(len(stages)):
        j.append('tl.fromTo("#p%d_%d",{scale:0.6,opacity:0.25,y:20},{scale:1,opacity:1,y:0,duration:0.35,ease:"back.out(2)"},%s);' % (sid, i, g(t + 0.4 + i * 0.5)))
    j += [
        'tl.fromTo("#stmp%d",{scale:2.4,rotation:-12,opacity:0},{scale:1,rotation:-8,opacity:1,duration:0.5,ease:"back.out(2.5)"},%s);' % (sid, g(t + 0.4 + len(stages) * 0.5)),
        text_in(sid, t + 0.2), chip_in(sid, t + 1.0), anim_out(sid, t, d),
    ]
    return html, j


def scene_quality(sid, t, d, cap, chip):
    panels = "".join('<div class="rpanel" id="rp%d_%d"><b>%s</b><span>%s</span></div>'
                     % (sid, i, n, v) for i, (n, v) in enumerate(
                         [("security", "refute"), ("quality", "refute"), ("runtime", "verify")]))
    html = ('<div class="panels">%s</div>'
            '<div class="lock" id="lk%d">&#128274;<span>FAIL-CLOSED</span></div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (panels, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t)]
    for i in range(3):
        j.append('tl.fromTo("#rp%d_%d",{y:50,opacity:0},{y:0,opacity:1,duration:0.4,ease:"power2.out"},%s);' % (sid, i, g(t + 0.3 + i * 0.2)))
    j += [
        'tl.fromTo("#lk%d",{scale:0,rotation:-20},{scale:1,rotation:0,duration:0.45,ease:"back.out(3)"},%s);' % (sid, g(t + 1.4)),
        'tl.to("#lk%d",{x:"+=14",duration:0.06,repeat:6,yoyo:true},%s);' % (sid, g(t + 1.85)),
        text_in(sid, t + 0.2), chip_in(sid, t + 2.0), anim_out(sid, t, d),
    ]
    return html, j


def scene_tokens(sid, t, d, cap, chip):
    parts = "".join('<div class="tok" id="tk%d_%d"></div>' % (sid, i) for i in range(14))
    html = ('<div class="bars"><div class="barbox"><div class="bar b870" id="bA%d"></div><div class="blab">870</div></div>'
            '<div class="arrow">&#8594;</div>'
            '<div class="barbox"><div class="bar b65" id="bB%d"></div><div class="blab">65</div></div></div>'
            '<div class="toks">%s</div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, sid, parts, sid, cap, sid, chip))
    j = [anim_in(sid, t),
         'tl.fromTo("#bA%d",{scaleY:0,transformOrigin:"bottom"},{scaleY:1,duration:0.5},%s);' % (sid, g(t + 0.4)),
         'tl.fromTo("#bB%d",{scaleY:0,transformOrigin:"bottom"},{scaleY:1,duration:0.5},%s);' % (sid, g(t + 0.7))]
    for i in range(14):
        j.append('tl.fromTo("#tk%d_%d",{y:0,opacity:1},{y:-220,opacity:0,duration:%s,ease:"power1.in"},%s);' % (sid, i, g(1.4 + (i % 5) * 0.2), g(t + 1.0 + (i % 7) * 0.12)))
    j += [text_in(sid, t + 0.2), chip_in(sid, t + 2.6), anim_out(sid, t, d)]
    return html, j


def scene_evidence(sid, t, d, cap, chip):
    html = ('<div class="gate"><div class="barrier" id="bar%d"></div>'
            '<div class="promise" id="pr%d">&lt;promise&gt;</div>'
            '<div class="xmark" id="xm%d">&#10007;</div>'
            '<div class="okmark" id="ok%d">&#10003;</div></div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, sid, sid, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t),
         'tl.fromTo("#pr%d",{x:-260,opacity:0},{x:-40,opacity:1,duration:0.6},%s);' % (sid, g(t + 0.4)),
         'tl.to("#pr%d",{x:-130,duration:0.25,ease:"power3.out"},%s);' % (sid, g(t + 1.1)),
         'tl.fromTo("#xm%d",{scale:0},{scale:1,duration:0.3,ease:"back.out(3)"},%s);' % (sid, g(t + 1.35)),
         'tl.to("#xm%d",{opacity:0,duration:0.3},%s);' % (sid, g(t + 2.6)),
         'tl.to("#pr%d",{x:160,opacity:1,duration:0.7,ease:"power2.in"},%s);' % (sid, g(t + 2.8)),
         'tl.fromTo("#ok%d",{scale:0},{scale:1,duration:0.4,ease:"back.out(3)"},%s);' % (sid, g(t + 3.0)),
         text_in(sid, t + 0.2), chip_in(sid, t + 1.0), anim_out(sid, t, d)]
    return html, j


def scene_video(sid, t, d, cap, chip):
    frames = "".join('<div class="frm" id="fr%d_%d">&#9636;</div>' % (sid, i) for i in range(4))
    html = ('<div class="filmstrip" id="film%d">%s</div>'
            '<div class="renderbar"><div class="renderfill" id="rf%d"></div></div>'
            '<div class="prcard" id="pc%d">PR #42 &#127916; MP4</div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, frames, sid, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t),
         'tl.fromTo("#film%d",{x:300,opacity:0},{x:0,opacity:1,duration:0.6,ease:"power2.out"},%s);' % (sid, g(t + 0.3))]
    for i in range(4):
        j.append('tl.fromTo("#fr%d_%d",{scale:0.4,opacity:0},{scale:1,opacity:1,duration:0.3,ease:"back.out(2)"},%s);' % (sid, i, g(t + 0.6 + i * 0.18)))
    j += [
        'tl.fromTo("#rf%d",{scaleX:0,transformOrigin:"left"},{scaleX:1,duration:1.2,ease:"power1.inOut"},%s);' % (sid, g(t + 1.6)),
        'tl.fromTo("#pc%d",{scale:0,opacity:0},{scale:1,opacity:1,duration:0.4,ease:"back.out(2.5)"},%s);' % (sid, g(t + 3.0)),
        text_in(sid, t + 0.2), chip_in(sid, t + 1.0), anim_out(sid, t, d),
    ]
    return html, j


def scene_runtimes(sid, t, d, cap, chip):
    names = ["Claude", "Codex", "Copilot", "Cursor", "Antigravity", "Kiro", "OpenCode", "Gemini", "Aider", "Simplicio Agent", "OpenClaw"]
    nodes = "".join('<div class="rt" id="rt%d_%d" style="--a:%ddeg">%s</div>' % (sid, i, int(360 * i / len(names)), n)
                    for i, n in enumerate(names))
    html = ('<div class="orbit" id="orb%d"><div class="hub">simplicio<br>tasks</div>%s</div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, nodes, sid, cap, sid, chip))
    j = [anim_in(sid, t)]
    for i in range(len(names)):
        j.append('tl.fromTo("#rt%d_%d",{scale:0,opacity:0},{scale:1,opacity:1,duration:0.3,ease:"back.out(2)"},%s);' % (sid, i, g(t + 0.4 + i * 0.07)))
    j += ['tl.to("#orb%d",{rotation:360,duration:%s,ease:"none",transformOrigin:"center"},%s);' % (sid, g(d), g(t)),
          'tl.to("#orb%d .rt",{rotation:-360,duration:%s,ease:"none"},%s);' % (sid, g(d), g(t)),
          text_in(sid, t + 0.2), chip_in(sid, t + 1.2), anim_out(sid, t, d)]
    return html, j


def scene_alwayson(sid, t, d, cap, chip):
    html = ('<div class="biginf pulse" id="inf%d">&#8734;</div>'
            '<div class="newcard" id="nc%d">new work &#8594;</div>'
            '<div class="cap" id="c%d">%s</div><div class="chip" id="d%d">%s</div>'
            % (sid, sid, sid, cap, sid, chip))
    j = [anim_in(sid, t),
         'tl.fromTo("#inf%d",{scale:0.6,opacity:0},{scale:1,opacity:1,duration:0.5,ease:"back.out(2)"},%s);' % (sid, g(t + 0.2)),
         'tl.to("#inf%d",{scale:1.12,duration:0.8,repeat:%d,yoyo:true,ease:"sine.inOut"},%s);' % (sid, max(1, int(d // 1.6)), g(t + 0.7)),
         'tl.fromTo("#nc%d",{x:260,opacity:0},{x:0,opacity:1,duration:0.5,ease:"power2.out"},%s);' % (sid, g(t + d - 3.0)),
         text_in(sid, t + 0.2), chip_in(sid, t + 1.0), anim_out(sid, t, d)]
    return html, j


def scene_cta(sid, t, d, cap, chip):
    cmds = ["pip install simplicio-loop", "bash scripts/install.sh claude", "/simplicio-tasks finish all the open issues"]
    lines = "".join('<div class="cmd" id="cm%d_%d">%s</div>' % (sid, i, c) for i, c in enumerate(cmds))
    badges = "".join('<div class="badge" id="bd%d_%d">%s</div>' % (sid, i, b)
                     for i, b in enumerate(["MIT", "Many runtimes", "Extension points", "Evidence-gated"]))
    html = ('<img class="finlogo" id="fl%d" src="assets/logo.png" alt="logo"/>'
            '<div class="cmds">%s</div><div class="badges">%s</div>'
            '<div class="cap" id="c%d">%s</div>' % (sid, lines, badges, sid, cap))
    j = [anim_in(sid, t),
         'tl.fromTo("#fl%d",{scale:0.5,opacity:0},{scale:1,opacity:1,duration:0.6,ease:"back.out(2)"},%s);' % (sid, g(t + 0.2))]
    for i in range(3):
        j.append('tl.fromTo("#cm%d_%d",{x:-60,opacity:0},{x:0,opacity:1,duration:0.35},%s);' % (sid, i, g(t + 0.7 + i * 0.3)))
    for i in range(4):
        j.append('tl.fromTo("#bd%d_%d",{scale:0,opacity:0},{scale:1,opacity:1,duration:0.3,ease:"back.out(3)"},%s);' % (sid, i, g(t + 1.8 + i * 0.18)))
    j += [text_in(sid, t + 0.4), anim_out(sid, t, d)]
    return html, j


SCENE_FN = {
    "hook": scene_hook, "problem": scene_problem, "preflight": scene_preflight,
    "discover_dag": scene_discover, "cycle": scene_cycle, "quality_safety": scene_quality,
    "token_economy": scene_tokens, "evidence_loop": scene_evidence, "video_evidence": scene_video,
    "runtimes": scene_runtimes, "always_on": scene_alwayson, "cta": scene_cta,
}


# ---------- shared GSAP helpers (whip transitions + hard kill) ----------
def anim_in(sid, t):
    return 'tl.fromTo("#s%d",{opacity:0,x:160},{opacity:1,x:0,duration:0.5,ease:"power3.out"},%s);' % (sid, g(t))


def anim_out(sid, t, d):
    return ('tl.to("#s%d",{opacity:0,x:-160,duration:0.4,ease:"power2.in"},%s);'
            'tl.set("#s%d",{opacity:0},%s);' % (sid, g(t + d - 0.4), sid, g(t + d)))


def text_in(sid, t):
    return 'tl.fromTo("#c%d",{opacity:0,y:24},{opacity:1,y:0,duration:0.5,ease:"power2.out"},%s);' % (sid, g(t))


def chip_in(sid, t):
    return 'tl.fromTo("#d%d",{opacity:0,y:14},{opacity:0.95,y:0,duration:0.5},%s);' % (sid, g(t))


def count(sid, t, dur, a, b, sel, prefix="", suffix=""):
    return ('var cp%s=%s_%d_%d={v:%d};tl.to(cp%s,{v:%d,duration:%s,ease:"power1.out",'
            'onUpdate:function(){document.querySelector("%s").textContent="%s"+Math.round(cp%s.v)+"%s";}},%s);'
            % (sid, "window.cnt", sid, abs(a) + b, a, sid, b, g(dur), sel, prefix, sid, suffix, g(t)))


def build(lang, storyboard):
    data = json.loads((LANG_DIR / ("%s.json" % lang)).read_text(encoding="utf-8"))
    master = {s["id"]: s for s in storyboard["scenes"]}
    clips, gsap, total = [], [], 0.0
    for sc in data["scenes"]:
        sid = sc["id"]
        m = master.get(sid, {})
        key = sc.get("key", m.get("key", ""))
        t = float(sc["start_s"]); d = float(sc["duration_s"]); total = max(total, t + d)
        cap = esc(sc.get("caption", "")); chip = esc(m.get("headline_data", ""))
        inner, j = SCENE_FN.get(key, scene_hook)(sid, t, d, cap, chip)
        clips.append('      <div class="clip scene-%s" id="s%d" data-start="%s" data-duration="%s" '
                     'data-track-index="1">%s</div>' % (key, sid, g(t), g(d), inner))
        gsap.extend(j)

    proj = OUT_DIR / lang
    (proj / "assets").mkdir(parents=True, exist_ok=True)
    logo = REPO / "assets" / "simplicio-loop-logo.png"
    if logo.exists():
        shutil.copy2(logo, proj / "assets" / "logo.png")

    # global background motion (drifting particles) — added to the same paused timeline
    bg_dots = "".join('<div class="pf" id="pf%d" style="left:%d%%;top:%d%%"></div>' % (i, (i * 53) % 100, (i * 37) % 100) for i in range(28))
    bg_anim = "".join('gsap.set("#pf%d",{opacity:0.18});tl.to("#pf%d",{y:-%d,x:%d,duration:%s,ease:"none"},0);'
                      % (i, i, 300 + (i % 5) * 120, (i % 3 - 1) * 60, g(total)) for i in range(28))

    html = (PAGE.replace("__LANG__", lang).replace("__TITLE__", esc(data.get("title", "simplicio-loop")))
            .replace("__W__", str(W)).replace("__H__", str(H)).replace("__DUR__", g(total))
            .replace("__CLIPS__", "\n".join(clips)).replace("__BGDOTS__", bg_dots)
            .replace("__GSAP__", "\n    ".join(gsap)).replace("__BGANIM__", bg_anim))
    (proj / "index.html").write_text(html, encoding="utf-8")
    return proj / "index.html"


PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=__W__, height=__H__"/>
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:__W__px;height:__H__px;overflow:hidden;background:#0B0E14;
  font-family:Arial,Helvetica,sans-serif;color:#E6EDF3}
.bg{position:absolute;inset:0;z-index:0;
  background:
    radial-gradient(1300px 800px at 50% 22%,rgba(124,58,237,.20),transparent 60%),
    radial-gradient(1000px 700px at 82% 92%,rgba(0,224,138,.14),transparent 60%);}
.bg::after{content:"";position:absolute;inset:0;opacity:.5;
  background-image:linear-gradient(rgba(255,255,255,.04) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.04) 1px,transparent 1px);
  background-size:66px 66px,66px 66px}
.pf{position:absolute;width:6px;height:6px;border-radius:50%;background:#00E08A;
  box-shadow:0 0 12px #00E08A;z-index:0}
.clip{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:26px;padding:0 130px;opacity:0;z-index:1;text-align:center}
.cap{font-size:54px;font-weight:700;line-height:1.12;max-width:1500px}
.cap.big{font-size:74px}
.chip{font-family:"Courier New",monospace;font-size:22px;line-height:1.5;max-width:1500px;
  color:#7CF3C0;background:rgba(0,224,138,.07);border:1px solid rgba(0,224,138,.22);
  border-radius:14px;padding:12px 24px;opacity:0}
.scene-problem .chip{color:#FF9A9A;background:rgba(255,92,92,.08);border-color:rgba(255,92,92,.25)}
.scene-runtimes .chip,.scene-discover_dag .chip,.scene-video_evidence .chip{
  color:#9DC1FF;background:rgba(37,99,235,.10);border-color:rgba(37,99,235,.28)}
.bignum{font-family:"Courier New",monospace;font-weight:700;color:#00E08A}
.biginf{font-size:230px;font-weight:800;color:#7C3AED;line-height:1;
  text-shadow:0 0 70px rgba(124,58,237,.7)}
.ring{position:absolute;width:520px;height:520px;border:3px solid rgba(124,58,237,.5);border-radius:50%}
/* problem */
.stack{display:flex;flex-direction:column;gap:12px}
.qcard{font-family:"Courier New",monospace;font-size:30px;padding:14px 30px;border-radius:12px;
  background:rgba(255,92,92,.10);border:1px solid rgba(255,92,92,.35);min-width:520px}
.costbar{position:absolute;right:160px;bottom:200px;width:60px;height:300px;
  background:rgba(255,255,255,.05);border-radius:8px;overflow:hidden;display:flex;align-items:flex-end}
.costfill{width:100%;height:100%;background:linear-gradient(#FF5C5C,#7a0000)}
.costnum{position:absolute;right:120px;bottom:240px;font-family:"Courier New",monospace;
  font-size:46px;color:#FF7A7A;font-weight:700}
/* preflight */
.checks{display:flex;flex-direction:column;gap:18px}
.crow{font-family:"Courier New",monospace;font-size:38px;display:flex;align-items:center;gap:18px}
.ck{display:inline-flex;width:54px;height:54px;align-items:center;justify-content:center;border-radius:50%;
  background:rgba(0,224,138,.15);color:#00E08A;border:2px solid #00E08A;font-size:30px}
/* dag */
.dag{width:900px;height:320px}
.stats{font-family:"Courier New",monospace;font-size:34px}
/* cycle */
.pipe{display:flex;gap:14px;flex-wrap:wrap;justify-content:center}
.pipe>div{font-family:"Courier New",monospace;font-size:28px;padding:14px 22px;border-radius:12px;
  background:rgba(0,224,138,.08);border:1px solid rgba(0,224,138,.3)}
.pipe>.run{background:rgba(124,58,237,.18);border-color:#7C3AED;color:#C9B6FF;font-weight:700}
.stamp{font-size:60px;font-weight:800;color:#00E08A;border:5px solid #00E08A;border-radius:14px;
  padding:8px 26px;transform:rotate(-8deg);display:flex;flex-direction:column;line-height:1}
.stamp span{font-size:20px;font-weight:600;letter-spacing:2px;color:#7CF3C0}
/* quality */
.panels{display:flex;gap:20px}
.rpanel{width:300px;padding:22px;border-radius:14px;background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.12);display:flex;flex-direction:column;gap:10px}
.rpanel b{font-size:28px;color:#9DC1FF}.rpanel span{font-family:"Courier New",monospace;color:#FF9A9A}
.lock{font-size:96px;color:#FF5C5C;display:flex;flex-direction:column;align-items:center;
  text-shadow:0 0 40px rgba(255,92,92,.6)}
.lock span{font-size:26px;font-weight:700;letter-spacing:3px}
/* tokens */
.bars{display:flex;align-items:flex-end;gap:34px}
.barbox{display:flex;flex-direction:column;align-items:center;gap:10px}
.bar{width:90px;background:linear-gradient(#00E08A,#066b45);border-radius:8px}
.b870{height:300px}.b65{height:60px}
.blab{font-family:"Courier New",monospace;font-size:28px}
.arrow{font-size:60px;color:#00E08A}
.toks{position:absolute;left:50%;top:48%;width:0;height:0}
.tok{position:absolute;width:10px;height:10px;border-radius:50%;background:#00E08A;
  box-shadow:0 0 10px #00E08A}
/* evidence */
.gate{position:relative;width:760px;height:200px;display:flex;align-items:center;justify-content:center}
.barrier{position:absolute;left:50%;top:0;width:8px;height:200px;background:#FF5C5C;border-radius:6px;
  box-shadow:0 0 24px rgba(255,92,92,.7)}
.promise{font-family:"Courier New",monospace;font-size:40px;padding:14px 26px;border-radius:12px;
  background:rgba(124,58,237,.18);border:1px solid #7C3AED}
.xmark{position:absolute;left:54%;font-size:90px;color:#FF5C5C;opacity:0}
.okmark{position:absolute;right:40px;font-size:90px;color:#00E08A;opacity:0}
/* video */
.filmstrip{display:flex;gap:14px}
.frm{width:150px;height:96px;border-radius:10px;background:rgba(37,99,235,.14);
  border:1px solid rgba(37,99,235,.4);display:flex;align-items:center;justify-content:center;font-size:46px;color:#9DC1FF}
.renderbar{width:640px;height:18px;background:rgba(255,255,255,.06);border-radius:10px;overflow:hidden}
.renderfill{width:100%;height:100%;background:linear-gradient(90deg,#2563EB,#00E08A);transform-origin:left}
.prcard{font-family:"Courier New",monospace;font-size:30px;padding:12px 24px;border-radius:12px;
  background:rgba(0,224,138,.10);border:1px solid rgba(0,224,138,.35)}
/* runtimes */
.orbit{position:relative;width:560px;height:560px;display:flex;align-items:center;justify-content:center}
.hub{width:150px;height:150px;border-radius:50%;background:rgba(124,58,237,.2);border:2px solid #7C3AED;
  display:flex;align-items:center;justify-content:center;text-align:center;font-weight:700;font-size:24px}
.rt{position:absolute;left:50%;top:50%;font-family:"Courier New",monospace;font-size:22px;
  padding:8px 14px;border-radius:10px;background:rgba(37,99,235,.14);border:1px solid rgba(37,99,235,.4);
  transform:translate(-50%,-50%) rotate(var(--a)) translateX(250px) rotate(calc(-1*var(--a)))}
/* always on */
.biginf.pulse{font-size:200px}
.newcard{font-family:"Courier New",monospace;font-size:30px;padding:12px 26px;border-radius:12px;
  background:rgba(0,224,138,.1);border:1px solid rgba(0,224,138,.35)}
/* cta */
.finlogo{height:120px}
.cmds{display:flex;flex-direction:column;gap:12px}
.cmd{font-family:"Courier New",monospace;font-size:30px;padding:12px 24px;border-radius:10px;
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12)}
.badges{display:flex;gap:14px;flex-wrap:wrap;justify-content:center}
.badge{font-family:"Courier New",monospace;font-size:22px;padding:8px 18px;border-radius:20px;
  background:rgba(124,58,237,.18);border:1px solid #7C3AED;color:#C9B6FF}
.brand{position:absolute;left:46px;bottom:32px;z-index:3;font-family:"Courier New",monospace;font-size:18px;opacity:.55}
.loopmark{position:absolute;right:46px;bottom:26px;z-index:3;font-size:44px;color:#7C3AED;opacity:.85}
.logo{position:absolute;left:42px;top:28px;z-index:3;height:48px;opacity:.92}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="__DUR__" data-width="__W__" data-height="__H__">
  <div class="bg">__BGDOTS__</div>
__CLIPS__
  <img class="logo" src="assets/logo.png" alt="simplicio-loop"/>
  <div class="brand">github.com/simpletibr/simplicio-loop</div>
  <div class="loopmark">&#8734;</div>
</div>
<script>
  window.cnt = window.cnt || {};
  window.__timelines = window.__timelines || {};
  var tl = gsap.timeline({ paused: true });
    __BGANIM__
    __GSAP__
  window.__timelines["main"] = tl;
</script>
</body>
</html>
"""


def main():
    storyboard = json.loads((HERE / "storyboard.master.json").read_text(encoding="utf-8"))
    for lang in (sys.argv[1:] or LANGS):
        if lang not in LANGS:
            print("skip: unknown lang %s" % lang); continue
        out = build(lang, storyboard)
        print("wrote %s" % out.relative_to(REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

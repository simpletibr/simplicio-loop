// Catalog page: renders every Simplicio Live component in every state.
// ?theme=dark|light|contrast forces a theme; ?compare=1 renders each specimen in all three.
import "./components/index.js";
import { SlAlertToast } from "./components/index.js";

const j = (value) => JSON.stringify(value).replace(/&/g, "&amp;").replace(/'/g, "&#39;");
const THEMES = [["dark", "Escuro"], ["light", "Claro"], ["contrast", "Alto contraste"]];

const LANES = [
  { id: "a", label: "lane-a", detail: "wt/loop-1399", stages: { intake: "PASS", mapping: "PASS", planning: "PASS", executing: { state: "RUNNING", duration: "12 min" } } },
  { id: "b", label: "lane-b", detail: "wt/loop-1400", stages: { intake: "PASS", mapping: "PASS", planning: "PASS", executing: { state: "PASS", retries: 2 }, validating: { state: "FAIL", duration: "3 min" } } },
  { id: "c", label: "lane-c", detail: "wt/loop-1398", stages: { intake: "PASS", mapping: "PASS", planning: "PASS", executing: "PASS", validating: "PASS", watching: "UNVERIFIED" } },
  { id: "d", label: "lane-d", detail: "wt/mkt-172", stages: { intake: "PASS", mapping: { state: "STALLED", duration: "41 min" } } },
  { id: "e", label: "lane-e", detail: "wt/mkt-173", stages: { intake: "PASS", mapping: "PASS", planning: "BLOCKED" } },
];

const RECEIPT = {
  schema: "simplicio.completion-receipt/v1", run_id: "run-20261002-1399", ready: false,
  gates: { evidence: { verdict: "PASS", files: 14 }, watcher: { verdict: "UNVERIFIED", reason: "desafio sem resposta" }, oracle: null },
  lanes: ["lane-a", "lane-b"], cost: { tokens: 182340, usd: 0.0 },
};

const DIFF = `diff --git a/simplicio_loop/progress.py b/simplicio_loop/progress.py
--- a/simplicio_loop/progress.py
+++ b/simplicio_loop/progress.py
@@ -30,6 +30,7 @@ PHASE_META = {
     "done": ("✅", "Concluído pelo oracle"),
     "blocked": ("⛔", "Bloqueado"),
     "cancelled": ("🛑", "Cancelado"),
+    "awaiting_decision": ("⏸️", "Aguardando decisão"),
 }
-SPINNER = ("|", "/")
+SPINNER = ("⠋", "⠙", "⠹", "⠸")
 EVENT_KINDS = frozenset((`;

const LOG = [
  { ts: "19:02:11", level: "info", source: "mapper", text: "scan concluído: 1.284 arquivos, geração 0.26.35" },
  { ts: "19:02:14", level: "debug", source: "planner", text: "plano congelado com 6 itens e 14 critérios" },
  { ts: "19:03:40", level: "warn", source: "watcher", text: "desafio aberto há 9 min sem resposta da lane-c" },
  { ts: "19:04:02", level: "error", source: "test_gate", text: "tests/test_progress.py::test_percent_never_100 FAILED (assert 100 <= 99)" },
  { ts: "19:04:05", level: "info", source: "loop", text: "estratégia trocada após 2 tentativas iguais: <img src=x onerror=alert(1)> continua texto" },
  { ts: "19:05:30", level: "info", source: "oracle", text: "aguardando completion-receipt.json com ready: true" },
];

const COMMANDS = [
  { id: "goto:stage-rail", label: "Trilho de fases", group: "Componentes", hint: "sl-stage-rail", keywords: ["fase", "pipeline"] },
  { id: "goto:gate-badge", label: "Selo de gate", group: "Componentes", hint: "sl-gate-badge", keywords: ["evidence", "watcher", "oracle"] },
  { id: "goto:lane-swimlane", label: "Lanes por fase", group: "Componentes", hint: "sl-lane-swimlane", keywords: ["worktree"] },
  { id: "goto:log-viewer", label: "Log com filtro", group: "Componentes", hint: "sl-log-viewer" },
  { id: "goto:calendar", label: "Calendário de publicações", group: "Componentes", hint: "sl-calendar", keywords: ["marketing"] },
  { id: "theme:dark", label: "Usar tema escuro", group: "Tema" },
  { id: "theme:light", label: "Usar tema claro", group: "Tema" },
  { id: "theme:contrast", label: "Usar alto contraste", group: "Tema" },
];

const SPECS = [
  {
    tag: "sl-stage-rail", title: "Trilho de fases",
    about: "As fases do run como um diagrama de via sinalizado. O trecho percorrido acende, a fase atual pulsa e um desvio mostra bloqueio, cancelamento ou espera por decisão. Sem recibo com ready: true o percentual nunca chega a 100.",
    html: `<div class="stack">
<sl-stage-rail phase="executing" status="RUNNING" percent="46"></sl-stage-rail>
<sl-stage-rail phase="validating" status="STALLED" percent="58" reason="Nenhum evento da lane-b há 14 min."></sl-stage-rail>
<sl-stage-rail phase="watching" status="FAIL" percent="71" reason="Watcher reprovou: teste de regressão ausente."></sl-stage-rail>
<sl-stage-rail phase="blocked" at="validating" percent="58" reason="Gate de evidência falhou 3 vezes seguidas."></sl-stage-rail>
<sl-stage-rail phase="awaiting_decision" at="planning" percent="30" reason="Escopo ambíguo: o plano espera a sua resposta."></sl-stage-rail>
<sl-stage-rail phase="done" percent="100"></sl-stage-rail>
<sl-stage-rail phase="done" receipt-ready></sl-stage-rail></div>`,
  },
  {
    tag: "sl-gate-badge", title: "Selo de gate",
    about: "Um gate e o seu estado honesto. Estados que pedem atenção mostram o motivo; com href o selo vira link para a evidência.",
    html: `<div class="row">
<sl-gate-badge gate="evidence" state="PASS" href="#sl-json-tree"></sl-gate-badge>
<sl-gate-badge gate="quality-gate" state="RUNNING"></sl-gate-badge>
<sl-gate-badge gate="DoD" state="FAIL" reason="Cobertura 71%, mínimo 85%"></sl-gate-badge>
<sl-gate-badge gate="watcher" state="UNVERIFIED" reason="Desafio sem resposta"></sl-gate-badge>
<sl-gate-badge gate="oracle" state="STALLED" reason="Sem eventos há 12 min"></sl-gate-badge>
<sl-gate-badge gate="delivery" state="BLOCKED" reason="Lease expirada na lane-b"></sl-gate-badge>
<sl-gate-badge gate="release" state="PENDING"></sl-gate-badge></div>`,
  },
  {
    tag: "sl-lane-swimlane", title: "Lanes por fase",
    about: "Cada lane (worktree) atravessa as fases como uma via. Retentativas e duração aparecem na própria célula.",
    html: `<sl-lane-swimlane label="Lanes do run run-20261002-1399" lanes='${j(LANES)}'></sl-lane-swimlane>`,
  },
  {
    tag: "sl-timeline", title: "Linha do tempo",
    about: "Iterações em ordem, com o estado de cada uma e o que mudou.",
    html: `<sl-timeline label="Iterações da lane-b" items='${j([
      { time: "18:41", title: "Plano congelado", state: "PASS", detail: "6 itens, 14 critérios de aceite." },
      { time: "18:52", title: "Execução, tentativa 1", state: "FAIL", detail: "pytest: 2 falhas em test_progress.py." },
      { time: "19:01", title: "Execução, tentativa 2", state: "PASS" },
      { time: "19:04", title: "Validação", state: "UNVERIFIED", detail: "Evidência sem print da tela." },
      { time: "19:10", title: "Watcher", state: "STALLED", detail: "Aguardando resposta ao desafio." },
      { time: "19:12", title: "Entrega", state: "BLOCKED", detail: "Release exige aprovação humana." },
      { time: "19:13", title: "Revisão adversarial", state: "RUNNING" },
    ])}'></sl-timeline>`,
  },
  {
    tag: "sl-sparkline", title: "Minigráfico",
    about: "Tendência compacta com nome acessível que resume último valor, mínimo e máximo.",
    html: `<div class="row">${["RUNNING", "PASS", "FAIL", "UNVERIFIED", "STALLED", "BLOCKED"].map((s, i) =>
      `<span><span class="cap">${s.toLowerCase()}</span><sl-sparkline state="${s}" label="Duração por iteração" unit="min" values="${[4, 7, 5, 9, 6, 11, 8].map((v) => v + i).join(",")}"></sl-sparkline></span>`).join("")}</div>`,
  },
  {
    tag: "sl-donut", title: "Rosca de proporções",
    about: "Proporções com legenda legível: o anel nunca é a única fonte do número.",
    html: `<div class="pair">
<sl-donut label="Gates do run" segments='${j([
      { label: "Aprovados", value: 9, state: "PASS" }, { label: "Em execução", value: 2, state: "RUNNING" },
      { label: "Falharam", value: 1, state: "FAIL" }, { label: "Não verificados", value: 2, state: "UNVERIFIED" },
      { label: "Parados", value: 1, state: "STALLED" }, { label: "Bloqueados", value: 1, state: "BLOCKED" }])}'></sl-donut>
<sl-donut label="Tokens por etapa" center="182 mil" segments='${j([
      { label: "Execução", value: 98000, state: "RUNNING" }, { label: "Validação", value: 51000, state: "PASS" },
      { label: "Mapeamento", value: 33340, state: "PENDING" }])}'></sl-donut>
<sl-donut label="Sem dados ainda" segments="[]"></sl-donut></div>`,
  },
  {
    tag: "sl-heatmap", title: "Mapa de calor",
    about: "Intensidade por linha e coluna, com leitura do valor ao navegar pelas setas.",
    html: `<sl-heatmap label="Falhas por gate e hora" unit="falhas" columns='${j(["13h", "14h", "15h", "16h", "17h", "18h", "19h"])}' rows='${j([
      { label: "evidence", values: [0, 1, 0, 2, 0, 0, 1] }, { label: "watcher", values: [1, 0, 3, 5, 2, 1, 0] },
      { label: "oracle", values: [0, 0, 0, 1, null, 0, 0] }, { label: "DoD", values: [2, 4, 6, 3, 1, 0, 2] }])}'></sl-heatmap>`,
  },
  {
    tag: "sl-log-viewer", title: "Log",
    about: "Log filtrável por texto e nível, com opção de seguir o fim durante o streaming. Conteúdo é sempre texto, nunca HTML.",
    html: `<sl-log-viewer label="Log do run" lines='${j(LOG)}'></sl-log-viewer>`,
  },
  {
    tag: "sl-json-tree", title: "Árvore JSON",
    about: "Recibos e contratos como árvore navegável por teclado, com filhos carregados só quando abertos.",
    html: `<sl-json-tree label="completion-receipt.json" expand-depth="1" data='${j(RECEIPT)}'></sl-json-tree>`,
  },
  {
    tag: "sl-diff-view", title: "Diff",
    about: "Diff unificado com números de linha e marcadores + e − além da cor.",
    html: `<sl-diff-view label="Diff do passo"></sl-diff-view>`,
    setup: (root) => root.querySelectorAll("sl-diff-view").forEach((el) => { el.diff = DIFF; }),
  },
  {
    tag: "sl-kpi-card", title: "Indicador",
    about: "Um número medido, a variação contra o run anterior e se ela melhorou ou piorou.",
    html: `<div class="kpis">
<sl-kpi-card label="Duração do run" value="38" unit="min" delta="-12%" good="down" state="PASS" trend="52,47,44,43,38"></sl-kpi-card>
<sl-kpi-card label="Tokens" value="182 mil" delta="+8%" good="down" state="RUNNING" trend="120,140,150,168,182"></sl-kpi-card>
<sl-kpi-card label="Cobertura" value="71" unit="%" delta="-4%" state="FAIL" detail="Mínimo exigido: 85%"></sl-kpi-card>
<sl-kpi-card label="Critérios verificados" value="11/14" delta="0%" state="UNVERIFIED"></sl-kpi-card>
<sl-kpi-card label="Lanes paradas" value="1" state="STALLED"></sl-kpi-card>
<sl-kpi-card label="Itens bloqueados" value="1" delta="+1" good="down" state="BLOCKED"></sl-kpi-card>
<sl-kpi-card label="Fila" value="3" unit="issues"></sl-kpi-card></div>`,
  },
  {
    tag: "sl-alert-toast", title: "Alerta",
    about: "Alertas de stall, gate falhando, lease expirada e orçamento. Falhas usam role alert e ficam até serem dispensadas; Esc também dispensa.",
    html: `<div class="stack">
<sl-alert-toast state="FAIL" heading="Gate de evidência falhou" href="#sl-log-viewer">Terceira falha seguida em test_progress.py.</sl-alert-toast>
<sl-alert-toast state="STALLED" heading="Lane parada">lane-d sem eventos há 41 min.</sl-alert-toast>
<sl-alert-toast state="BLOCKED" heading="Lease expirada">A lane-b perdeu a lease; outro worker pode assumir.</sl-alert-toast>
<sl-alert-toast state="UNVERIFIED" heading="Orçamento perto do limite">82% do orçamento de tokens usado.</sl-alert-toast>
<sl-alert-toast state="PASS" heading="Watcher aprovou">Desafio respondido com evidência.</sl-alert-toast>
<sl-alert-toast state="RUNNING" heading="Revisão em andamento" persistent>3 revisores em paralelo.</sl-alert-toast>
<p class="row"><button type="button" class="demo-btn" data-notify>Mostrar alerta temporário</button></p></div>`,
    setup: (root) => root.querySelectorAll("[data-notify]").forEach((b) => b.addEventListener("click", () =>
      SlAlertToast.notify({ state: "UNVERIFIED", heading: "Recibo ainda não verificado", message: "O oracle não confirmou ready: true.", timeout: 8000 }))),
  },
  {
    tag: "sl-command-palette", title: "Paleta de comandos",
    about: "Busca de runs, fases, gates e ações. Abre com Ctrl+K ou Cmd+K (atributo hotkey), navega com as setas e devolve o foco ao fechar.",
    html: `<div class="row"><sl-command-palette label="Buscar comandos" commands='${j(COMMANDS)}'></sl-command-palette><output aria-live="polite">Nenhum comando executado.</output></div>`,
  },
  {
    tag: "sl-calendar", title: "Calendário",
    about: "Agenda do painel de marketing: publicações por dia com estado, navegável por setas, Home, End e PageUp/PageDown.",
    html: `<sl-calendar label="Publicações" month="2026-10" today="2026-10-02" selected="2026-10-05" events='${j([
      { date: "2026-10-01", title: "Post LinkedIn: release 3.46", state: "PASS", channel: "LinkedIn" },
      { date: "2026-10-02", title: "Clipe do painel ao vivo", state: "RUNNING", channel: "YouTube" },
      { date: "2026-10-02", title: "Thread no X", state: "UNVERIFIED", channel: "X" },
      { date: "2026-10-05", title: "Newsletter", state: "PENDING", channel: "E-mail" },
      { date: "2026-10-05", title: "Short vertical", state: "PENDING", channel: "TikTok" },
      { date: "2026-10-07", title: "Webinar", state: "BLOCKED", channel: "YouTube" },
      { date: "2026-10-09", title: "Post Instagram", state: "FAIL", channel: "Instagram" },
      { date: "2026-10-14", title: "Artigo no blog", state: "STALLED", channel: "Blog" },
      { date: "2026-10-14", title: "Corte 1", state: "PENDING" }, { date: "2026-10-14", title: "Corte 2", state: "PENDING" },
      { date: "2026-10-14", title: "Corte 3", state: "PENDING" }])}'></sl-calendar>`,
  },
  {
    tag: "sl-connection-dot", title: "Conexão ao vivo",
    about: "Estado do stream de eventos (SSE) no topo do painel.",
    html: `<div class="row"><sl-connection-dot status="live" detail="último evento há 2 s"></sl-connection-dot>
<sl-connection-dot status="connecting"></sl-connection-dot><sl-connection-dot status="stale" detail="há 45 s"></sl-connection-dot>
<sl-connection-dot status="offline" detail="tentando de novo em 5 s"></sl-connection-dot></div>`,
  },
];

const HERO = `<div class="board">
<div class="row"><sl-connection-dot status="live" detail="run-20261002-1399"></sl-connection-dot>
<sl-gate-badge gate="evidence" state="PASS"></sl-gate-badge><sl-gate-badge gate="watcher" state="UNVERIFIED" reason="Desafio sem resposta"></sl-gate-badge>
<sl-gate-badge gate="oracle" state="PENDING"></sl-gate-badge></div>
<sl-stage-rail phase="executing" status="RUNNING" percent="46" label="Fases do run em destaque"></sl-stage-rail>
<div class="kpis"><sl-kpi-card label="Duração" value="38" unit="min" delta="-12%" good="down" state="PASS" trend="52,47,44,43,38"></sl-kpi-card>
<sl-kpi-card label="Tokens" value="182 mil" delta="+8%" good="down" state="RUNNING" trend="120,140,150,168,182"></sl-kpi-card>
<sl-kpi-card label="Critérios verificados" value="11/14" state="UNVERIFIED"></sl-kpi-card></div></div>`;

function themed(html, compare) {
  if (!compare) return html;
  return `<div class="themes">${THEMES.map(([key, name]) =>
    `<div class="theme" data-sl-theme="${key}"><span class="cap">${name}</span>${html}</div>`).join("")}</div>`;
}

function render() {
  const params = new URLSearchParams(location.search);
  const theme = THEMES.some(([k]) => k === params.get("theme")) ? params.get("theme") : "dark";
  const compare = params.get("compare") === "1";
  document.documentElement.dataset.slTheme = theme;
  document.querySelector(`input[name=theme][value=${theme}]`).checked = true;
  document.querySelector("input[name=compare]").checked = compare;
  const main = document.querySelector("main");
  main.innerHTML = `<section class="spec hero" id="painel" aria-labelledby="painel-h"><h2 id="painel-h">Um run ao vivo</h2>
<p>Os componentes juntos, como o topo do painel do loop de codificação.</p>${themed(HERO, compare)}</section>` +
    SPECS.map((s) => `<section class="spec" id="${s.tag}" aria-labelledby="${s.tag}-h"><h2 id="${s.tag}-h">&lt;${s.tag}&gt;</h2>
<p><strong>${s.title}.</strong> ${s.about}</p>${themed(s.html, compare)}</section>`).join("");
  for (const s of SPECS) s.setup?.(main.querySelector(`#${s.tag}`));
  document.getElementById("toc").innerHTML = `<li><a href="#painel">Um run ao vivo</a></li>` +
    SPECS.map((s) => `<li><a href="#${s.tag}">&lt;${s.tag}&gt;</a></li>`).join("");
}

function setParam(key, value) {
  const params = new URLSearchParams(location.search);
  if (value == null) params.delete(key); else params.set(key, value);
  history.replaceState(null, "", `${location.pathname}?${params}${location.hash}`);
  render();
}

document.querySelector(".controls").addEventListener("change", (e) => {
  if (e.target.name === "theme") setParam("theme", e.target.value);
  if (e.target.name === "compare") setParam("compare", e.target.checked ? "1" : null);
});
document.querySelector(".controls").addEventListener("submit", (e) => e.preventDefault());

document.addEventListener("sl-command", (e) => {
  const id = String(e.detail.id);
  if (id.startsWith("theme:")) setParam("theme", id.slice(6));
  else if (id.startsWith("goto:")) {
    const target = document.getElementById(`sl-${id.slice(5)}`);
    target?.scrollIntoView();
    target?.querySelector("h2")?.setAttribute("tabindex", "-1");
    target?.querySelector("h2")?.focus();
  }
  const out = e.target.closest?.("section")?.querySelector("output") ?? document.querySelector("#sl-command-palette output");
  if (out) out.textContent = `Executado: ${e.detail.command.label}`;
});

const header = document.querySelector("sl-command-palette[hotkey]");
header.commands = COMMANDS;
render();
await Promise.all([...new Set([...document.querySelectorAll("*")].map((el) => el.localName).filter((n) => n.startsWith("sl-")))]
  .map((n) => customElements.whenDefined(n)));
await document.fonts?.ready;
document.documentElement.dataset.ready = "1";

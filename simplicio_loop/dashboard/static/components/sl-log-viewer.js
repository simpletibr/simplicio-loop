import { SlElement, define, esc } from "./base.js";

const LEVELS = { error: "Erro", warn: "Aviso", info: "Info", debug: "Debug" };
const FILTERS = [["all", "Tudo"], ["error", "Erros"], ["warn", "Avisos e erros"]];

function normLine(line) {
  if (typeof line === "string") return { text: line, level: /\b(error|erro|fail|traceback)\b/i.test(line) ? "error" : "info" };
  const level = String(line?.level ?? "info").toLowerCase();
  return { ts: line?.ts ?? "", source: line?.source ?? "", text: String(line?.text ?? ""), level: Object.hasOwn(LEVELS, level) ? level : "info" };
}

/**
 * Filterable, followable log. Property/attribute `lines`: strings or { ts, level, source, text }.
 * Attributes: label, follow (auto-scroll to the newest line). Method append(line) for live streams.
 */
export class SlLogViewer extends SlElement {
  static observedAttributes = ["lines", "label", "follow"];
  static jsonProps = ["lines"];
  static styles = `
:host { display: block; }
.box { background: var(--sl-panel); border-radius: var(--sl-radius-panel); box-shadow: var(--sl-shadow), inset 0 0 0 1px var(--sl-line-soft); overflow: hidden; }
.bar { display: flex; flex-wrap: wrap; gap: var(--sl-space-2) var(--sl-space-4); align-items: center; padding: var(--sl-space-3) var(--sl-space-4);
  border-block-end: 1px solid var(--sl-line-soft); }
.bar label { display: flex; gap: var(--sl-space-2); align-items: center; font-size: var(--sl-step--1); }
input[type="search"] { font: inherit; color: var(--sl-ink); background: var(--sl-raised); border: 1px solid var(--sl-line);
  border-radius: var(--sl-radius-plate); padding: var(--sl-space-1) var(--sl-space-2); inline-size: 14em; }
.seg { display: inline-flex; border: 1px solid var(--sl-line); border-radius: var(--sl-radius-pill); overflow: hidden; }
.seg button { border: 0; background: transparent; padding: var(--sl-space-1) var(--sl-space-3); font-size: var(--sl-step--1); cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--sl-ink); color: var(--sl-panel); }
.follow { margin-inline-start: auto; }
.count { font-size: var(--sl-step--2); color: var(--sl-ink-muted); }
ol { list-style: none; margin: 0; padding: var(--sl-space-2) 0; max-block-size: var(--sl-log-height, 22em); overflow: auto;
  font-family: var(--sl-font-mono); font-size: var(--sl-step--1); line-height: 1.5; }
li { display: grid; grid-template-columns: 6.5em 4.5em minmax(0, 1fr); gap: var(--sl-space-3); padding: 1px var(--sl-space-4); }
li[data-level="error"] { background: color-mix(in srgb, var(--sl-state-fail) 12%, transparent); }
li[data-level="warn"] { background: color-mix(in srgb, var(--sl-state-unverified) 10%, transparent); }
.ts { color: var(--sl-ink-muted); }
.lvl { font-weight: var(--sl-weight-strong); }
li[data-level="error"] .lvl { color: var(--sl-state-fail); }
li[data-level="warn"] .lvl { color: var(--sl-state-unverified); }
li[data-level="debug"] .lvl, li[data-level="info"] .lvl { color: var(--sl-ink-muted); }
.msg { white-space: pre-wrap; overflow-wrap: anywhere; }
.src { color: var(--sl-ink-muted); }
mark { background: var(--sl-state-unverified); color: var(--sl-on-lamp); border-radius: 2px; }
.empty { display: block; padding: var(--sl-space-4); color: var(--sl-ink-muted); font-family: var(--sl-font-sans); }
`;

  constructor() {
    super();
    this._extra = [];
    this._filter = "all";
    this._query = "";
  }

  /** Append one line (string or object) without re-rendering the toolbar. */
  append(line) {
    this._extra.push(line);
    this._renderLines();
  }

  update() {
    if (!this.shadowRoot.querySelector(".box")) {
      const label = esc(this.getAttribute("label") || "Log");
      this.shadowRoot.innerHTML = `<div class="box"><div class="bar">
<label>Filtrar <input type="search" placeholder="texto ou fonte"></label>
<div class="seg" role="group" aria-label="Nível">${FILTERS.map(([k, t]) => `<button type="button" data-filter="${k}" aria-pressed="${k === this._filter}">${t}</button>`).join("")}</div>
<label class="follow"><input type="checkbox" class="follow-box"> Seguir o fim</label><span class="count" aria-live="polite"></span></div>
<ol tabindex="0" role="log" aria-label="${label}"></ol></div>`;
      const root = this.shadowRoot;
      root.querySelector("input[type=search]").addEventListener("input", (e) => { this._query = e.target.value; this._renderLines(); });
      root.querySelector(".seg").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-filter]");
        if (!b) return;
        this._filter = b.dataset.filter;
        for (const x of root.querySelectorAll(".seg button")) x.setAttribute("aria-pressed", String(x === b));
        this._renderLines();
      });
      root.querySelector(".follow-box").addEventListener("change", (e) => this.toggleAttribute("follow", e.target.checked));
    }
    this.shadowRoot.querySelector(".follow-box").checked = this.hasAttribute("follow");
    this.shadowRoot.querySelector("ol").setAttribute("aria-label", this.getAttribute("label") || "Log");
    this._renderLines();
  }

  get visibleLines() {
    const base = this.lines;
    const all = [...(typeof base === "string" ? base.split("\n") : Array.isArray(base) ? base : []), ...this._extra].map(normLine);
    const q = this._query.trim().toLowerCase();
    return all.filter((l) => (this._filter === "all" || l.level === "error" || (this._filter === "warn" && l.level === "warn"))
      && (!q || `${l.text} ${l.source}`.toLowerCase().includes(q)));
  }

  _renderLines() {
    const ol = this.shadowRoot.querySelector("ol");
    if (!ol) return;
    const q = this._query.trim();
    const hi = (text) => {
      if (!q) return esc(text);
      const lower = text.toLowerCase(), needle = q.toLowerCase();
      let out = "", i = 0, j;
      while ((j = lower.indexOf(needle, i)) !== -1) {
        out += esc(text.slice(i, j)) + `<mark>${esc(text.slice(j, j + needle.length))}</mark>`;
        i = j + needle.length;
      }
      return out + esc(text.slice(i));
    };
    const lines = this.visibleLines;
    ol.innerHTML = lines.length
      ? lines.map((l) => `<li data-level="${l.level}"><span class="ts">${esc(l.ts)}</span><span class="lvl">${LEVELS[l.level]}</span>` +
        `<span class="msg">${l.source ? `<span class="src">${esc(l.source)} </span>` : ""}${hi(l.text)}</span></li>`).join("")
      : `<li class="empty">Nenhuma linha corresponde ao filtro. Limpe a busca ou escolha "Tudo".</li>`;
    this.shadowRoot.querySelector(".count").textContent = `${lines.length} linhas`;
    if (this.hasAttribute("follow")) ol.scrollTop = ol.scrollHeight;
  }
}

define("sl-log-viewer", SlLogViewer);

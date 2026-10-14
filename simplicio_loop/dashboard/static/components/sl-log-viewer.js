import { SlElement, define, esc } from "./base.js";

const LEVELS = { error: "Erro", warn: "Aviso", info: "Info", debug: "Debug" };
const FILTERS = [["all", "Tudo"], ["error", "Erros"], ["warn", "Avisos e erros"]];

function normLine(line) {
  if (typeof line === "string") return { text: line, level: /\b(error|erro|fail|traceback)\b/i.test(line) ? "error" : "info" };
  const level = String(line?.level ?? "info").toLowerCase();
  return { ts: line?.ts ?? "", source: line?.source ?? "", text: String(line?.text ?? ""), level: Object.hasOwn(LEVELS, level) ? level : "info" };
}

const OVERSCAN = 30;
const FALLBACK_HEIGHT = 352;

/**
 * Filterable, followable, virtualized log: only the rows in view (plus an overscan) are in the DOM, so 100 000
 * lines scroll like 100. Rows have one fixed height; a long message is cut with an ellipsis and keeps its full
 * text in the row title. Property/attribute `lines`: strings or { ts, level, source, text }.
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
.lines { position: relative; margin: 0; block-size: var(--sl-log-height, 22em); overflow: auto;
  font-family: var(--sl-font-mono); font-size: var(--sl-step--1); line-height: 1.5; }
.sizer { position: relative; }
.win { position: absolute; inset-block-start: 0; inset-inline: 0; }
.line { block-size: var(--row, 1.5em); overflow: hidden; align-items: center; display: grid; grid-template-columns: 6.5em 4.5em minmax(0, 1fr); gap: var(--sl-space-3); padding: 1px var(--sl-space-4); }
.line[data-level="error"] { background: color-mix(in srgb, var(--sl-state-fail) 12%, transparent); }
.line[data-level="warn"] { background: color-mix(in srgb, var(--sl-state-unverified) 10%, transparent); }
.ts { color: var(--sl-ink-muted); }
.lvl { font-weight: var(--sl-weight-strong); }
.line[data-level="error"] .lvl { color: var(--sl-state-fail); }
.line[data-level="warn"] .lvl { color: var(--sl-state-unverified); }
.line[data-level="debug"] .lvl, .line[data-level="info"] .lvl { color: var(--sl-ink-muted); }
.msg { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.src { color: var(--sl-ink-muted); }
mark { background: var(--sl-state-unverified); color: var(--sl-on-lamp); border-radius: 2px; }
.empty { display: block; padding: var(--sl-space-4); color: var(--sl-ink-muted); font-family: var(--sl-font-sans); }
`;

  constructor() {
    super();
    this._extra = [];
    this._filter = "all";
    this._query = "";
    this._rowH = 0;
    this._all = null;
    this._allBase = undefined;
    this._allExtra = -1;
    this._view = null;
    this._viewKey = "";
    this._frame = 0;
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
<div class="lines" tabindex="0" role="log" aria-label="${label}"><div class="sizer"><div class="win"></div></div></div></div>`;
      const root = this.shadowRoot;
      root.querySelector("input[type=search]").addEventListener("input", (e) => { this._query = e.target.value; this._renderLines(); });
      root.querySelector(".seg").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-filter]");
        if (!b) return;
        this._filter = b.dataset.filter;
        for (const x of root.querySelectorAll(".seg button")) x.setAttribute("aria-pressed", String(x === b));
        this._renderLines();
      });
      root.querySelector(".lines").addEventListener("scroll", () => {
        if (!this._frame) this._frame = requestAnimationFrame(() => { this._frame = 0; this._paint(); });
      });
      root.querySelector(".follow-box").addEventListener("change", (e) => this.toggleAttribute("follow", e.target.checked));
    }
    this.shadowRoot.querySelector(".follow-box").checked = this.hasAttribute("follow");
    this.shadowRoot.querySelector(".lines").setAttribute("aria-label", this.getAttribute("label") || "Log");
    this._renderLines();
  }

  // Normalised lines, rebuilt only when the `lines` value or the appended count changes.
  _normalised() {
    const base = this.lines;
    if (this._all === null || base !== this._allBase || this._extra.length !== this._allExtra) {
      const list = typeof base === "string" ? base.split("\n") : Array.isArray(base) ? base : [];
      this._all = [...list, ...this._extra].map(normLine);
      this._allBase = base;
      this._allExtra = this._extra.length;
      this._view = null;
    }
    return this._all;
  }

  get visibleLines() {
    const q = this._query.trim().toLowerCase();
    const key = `${this._filter}\u0000${q}`;
    const all = this._normalised();
    if (this._view === null || this._viewKey !== key) {
      this._viewKey = key;
      this._view = all.filter((l) => (this._filter === "all" || l.level === "error" || (this._filter === "warn" && l.level === "warn"))
        && (!q || `${l.text} ${l.source}`.toLowerCase().includes(q)));
    }
    return this._view;
  }

  _row(l, hi) {
    return `<div class="line" data-level="${l.level}" title="${esc(l.text)}"><span class="ts">${esc(l.ts)}</span><span class="lvl">${LEVELS[l.level]}</span>` +
      `<span class="msg">${l.source ? `<span class="src">${hi(l.source)} </span>` : ""}${hi(l.text)}</span></div>`;
  }

  _highlighter() {
    const q = this._query.trim();
    return (text) => {
      if (!q) return esc(text);
      const lower = text.toLowerCase(), needle = q.toLowerCase();
      let out = "", i = 0, j;
      while ((j = lower.indexOf(needle, i)) !== -1) {
        out += esc(text.slice(i, j)) + `<mark>${esc(text.slice(j, j + needle.length))}</mark>`;
        i = j + needle.length;
      }
      return out + esc(text.slice(i));
    };
  }

  // Paints only the rows in view. Cheap enough to run on every scroll frame.
  _paint() {
    const root = this.shadowRoot;
    const box = root.querySelector(".lines");
    const sizer = root.querySelector(".sizer");
    const win = root.querySelector(".win");
    if (!box) return;
    const lines = this.visibleLines;
    if (!lines.length) {
      sizer.style.height = "";
      win.style.transform = "";
      win.innerHTML = `<p class="empty">Nenhuma linha corresponde ao filtro. Limpe a busca ou escolha "Tudo".</p>`;
      return;
    }
    const hi = this._highlighter();
    if (!this._rowH) {
      win.innerHTML = this._row(lines[0], hi);
      this._rowH = win.firstElementChild.getBoundingClientRect().height || 0;
      if (this._rowH) box.style.setProperty("--row", `${this._rowH}px`);
    }
    const rowH = this._rowH || 22;
    sizer.style.height = `${lines.length * rowH}px`;
    const height = box.clientHeight || FALLBACK_HEIGHT;
    const first = Math.min(Math.max(0, Math.floor(box.scrollTop / rowH) - OVERSCAN), lines.length - 1);
    const last = Math.min(lines.length, Math.ceil((box.scrollTop + height) / rowH) + OVERSCAN);
    win.style.transform = `translateY(${first * rowH}px)`;
    win.innerHTML = lines.slice(first, last).map((l) => this._row(l, hi)).join("");
  }

  _renderLines() {
    const box = this.shadowRoot.querySelector(".lines");
    if (!box) return;
    const count = this.visibleLines.length;
    this.shadowRoot.querySelector(".count").textContent = `${count} linhas`;
    this._paint();
    if (this.hasAttribute("follow")) {
      box.scrollTop = box.scrollHeight;
      this._paint();
    }
  }
}

define("sl-log-viewer", SlLogViewer);

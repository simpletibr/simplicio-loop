import { SlElement, define, esc } from "./base.js";

/** Parse a unified diff into files -> rows. Exported for tests and other renderers. */
export function parseUnifiedDiff(text) {
  const files = [];
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  let file = null, oldNo = 0, newNo = 0, inHunk = false;
  const start = (name) => { file = { name, rows: [], add: 0, del: 0 }; files.push(file); inHunk = false; };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("diff --git ")) {
      start(line.split(" b/").at(-1) || line.slice(11));
    } else if (line.startsWith("--- ") && lines[i + 1]?.startsWith("+++ ")) {
      const oldName = line.slice(4).replace(/^a\//, "").trim();
      const newName = lines[++i].slice(4).replace(/^b\//, "").trim();
      const name = newName !== "/dev/null" ? newName : oldName;
      if (!file || file.rows.length) start(name);
      else file.name = name;
    } else if (line.startsWith("@@")) {
      const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      oldNo = m ? Number(m[1]) : 0;
      newNo = m ? Number(m[2]) : 0;
      if (!file) start("diff");
      file.rows.push({ kind: "hunk", text: line });
      inHunk = true;
    } else if (inHunk && file) {
      if (line.startsWith("+")) { file.rows.push({ kind: "add", newNo: newNo++, text: line.slice(1) }); file.add++; }
      else if (line.startsWith("-")) { file.rows.push({ kind: "del", oldNo: oldNo++, text: line.slice(1) }); file.del++; }
      else if (line.startsWith("\\")) file.rows.push({ kind: "meta", text: line });
      else if (line.startsWith(" ")) file.rows.push({ kind: "ctx", oldNo: oldNo++, newNo: newNo++, text: line.slice(1) });
    }
  }
  return files.filter((f) => f.rows.length);
}

const MARK = { add: "+", del: "−", ctx: " " };
const SR = { add: "adicionada", del: "removida" };

/** Diffs with more rows than this (summed over files) switch to the flattened virtual list. */
export const VIRTUAL_ROWS = 1000;
/** Fixed row height of the virtual list in px: rows never wrap, long lines scroll horizontally. */
export const ROW_HEIGHT = 22;
const OVERSCAN = 30;
const FALLBACK_VIEWPORT = 480;

/**
 * Index range [first, last) of the virtual items to paint for a scroll position. `last` is exclusive and both
 * ends include `overscan` extra items, clamped to [0, total]. Pure: it runs under node as well as in a browser.
 */
export function windowRange(scrollTop, viewport, rowHeight, total, overscan = OVERSCAN) {
  if (!(total > 0) || !(rowHeight > 0)) return { first: 0, last: 0 };
  const top = Math.max(0, Number(scrollTop) || 0);
  const height = Math.max(0, Number(viewport) || 0);
  const first = Math.min(Math.max(0, Math.floor(top / rowHeight) - overscan), total);
  const last = Math.min(total, Math.ceil((top + height) / rowHeight) + overscan);
  return { first, last: Math.max(first, last) };
}

/**
 * Flatten parsed files into one virtual list: a head item per file, then that file's rows (hunks and meta
 * included). `rows` counts diff rows only (no heads) and decides whether the virtual list is used.
 */
export function flattenDiff(files) {
  const items = [];
  let rows = 0;
  for (const f of files) {
    items.push({ kind: "file", name: f.name, add: f.add, del: f.del });
    for (const r of f.rows) items.push(r);
    rows += f.rows.length;
  }
  return { files, items, rows, virtual: rows > VIRTUAL_ROWS };
}

function itemHtml(r) {
  if (r.kind === "file") {
    return `<div class="vrow wide vhead"><span class="name">${esc(r.name)}</span>` +
      `<span class="add">+${r.add}<span class="sr-only"> linhas adicionadas</span></span>` +
      `<span class="del">−${r.del}<span class="sr-only"> linhas removidas</span></span></div>`;
  }
  if (r.kind === "hunk" || r.kind === "meta") return `<div class="vrow wide r-${r.kind}">${esc(r.text)}</div>`;
  return `<div class="vrow r-${r.kind}"><span class="vno">${r.oldNo ?? ""}</span><span class="vno">${r.newNo ?? ""}</span>` +
    `<span class="vmk" aria-hidden="true">${MARK[r.kind]}</span><span class="vcode">${SR[r.kind] ? `<span class="sr-only">${SR[r.kind]}: </span>` : ""}${esc(r.text)}</span></div>`;
}

/**
 * Unified diff viewer. Property/attribute `diff` (unified diff text); without it the element's
 * own text content is used. Attribute `label` names the region. Up to VIRTUAL_ROWS rows every file is rendered
 * as a table; above that the whole diff is one windowed list (fixed rows, only the visible ones in the DOM).
 */
export class SlDiffView extends SlElement {
  static observedAttributes = ["diff", "label"];
  static styles = `
:host { display: block; }
.file { background: var(--sl-panel); border-radius: var(--sl-radius-panel); box-shadow: var(--sl-shadow), inset 0 0 0 1px var(--sl-line-soft);
  overflow: hidden; }
.file + .file { margin-block-start: var(--sl-space-4); }
.head { display: flex; gap: var(--sl-space-3); align-items: baseline; flex-wrap: wrap; padding: var(--sl-space-3) var(--sl-space-4);
  border-block-end: 1px solid var(--sl-line-soft); margin: 0; font-size: var(--sl-step-0); font-weight: var(--sl-weight-strong); }
.name { font-family: var(--sl-font-mono); overflow-wrap: anywhere; }
.add { color: var(--sl-state-pass); }
.del { color: var(--sl-state-fail); }
.scroll { overflow-x: auto; max-block-size: var(--sl-diff-height, 30em); }
table { border-collapse: collapse; inline-size: 100%; font-family: var(--sl-font-mono); font-size: var(--sl-step--1); line-height: 1.5; }
td { padding: 0 var(--sl-space-2); vertical-align: top; }
.no { inline-size: 1%; min-inline-size: 3.5em; text-align: end; color: var(--sl-ink-muted); user-select: none; }
.mk { inline-size: 1.2em; text-align: center; user-select: none; font-weight: var(--sl-weight-strong); }
.code { white-space: pre-wrap; overflow-wrap: anywhere; }
tr.r-add { background: color-mix(in srgb, var(--sl-state-pass) 16%, transparent); }
tr.r-add .mk { color: var(--sl-state-pass); }
tr.r-del { background: color-mix(in srgb, var(--sl-state-fail) 16%, transparent); }
tr.r-del .mk { color: var(--sl-state-fail); }
tr.r-hunk td, tr.r-meta td { color: var(--sl-ink-muted); background: color-mix(in srgb, var(--sl-state-running) 9%, transparent); padding-block: 2px; }
.empty { color: var(--sl-ink-muted); margin: 0; }
.vsum { margin: 0 0 var(--sl-space-2); font-size: var(--sl-step--2); color: var(--sl-ink-muted); }
.vbox { position: relative; overflow: auto; max-block-size: var(--sl-diff-height, 30em); background: var(--sl-panel);
  border-radius: var(--sl-radius-panel); box-shadow: var(--sl-shadow), inset 0 0 0 1px var(--sl-line-soft);
  font-family: var(--sl-font-mono); font-size: var(--sl-step--1); }
.vsizer { inline-size: max-content; min-inline-size: 100%; }
.vrows { inline-size: max-content; min-inline-size: 100%; }
.vrow { display: grid; grid-template-columns: 3.5em 3.5em 1.2em max-content; column-gap: var(--sl-space-2);
  block-size: ${ROW_HEIGHT}px; line-height: ${ROW_HEIGHT}px; white-space: pre; padding-inline-end: var(--sl-space-2); }
.vrow.wide { display: block; padding-inline: var(--sl-space-2); }
.vrow.wide.vhead { font-weight: var(--sl-weight-strong); background: var(--sl-raised); }
.vrow.vhead > span { margin-inline-end: var(--sl-space-3); }
.vno { text-align: end; color: var(--sl-ink-muted); user-select: none; }
.vmk { text-align: center; user-select: none; font-weight: var(--sl-weight-strong); }
.vrow.r-add { background: color-mix(in srgb, var(--sl-state-pass) 16%, transparent); }
.vrow.r-add .vmk { color: var(--sl-state-pass); }
.vrow.r-del { background: color-mix(in srgb, var(--sl-state-fail) 16%, transparent); }
.vrow.r-del .vmk { color: var(--sl-state-fail); }
.vrow.r-hunk, .vrow.r-meta { color: var(--sl-ink-muted); background: color-mix(in srgb, var(--sl-state-running) 9%, transparent); }
`;

  constructor() {
    super();
    this._model = null;
    this._modelKey = null;
    this._shown = null;
    this._mode = "";
    this._refs = null;
    this._frame = 0;
  }

  connectedCallback() {
    if (Object.hasOwn(this, "diff")) {
      const value = this.diff;
      delete this.diff;
      this._diff = value;
    }
    super.connectedCallback();
  }

  get diff() {
    return this._diff ?? this.getAttribute("diff") ?? this.textContent;
  }

  set diff(value) {
    this._diff = value;
    if (this.isConnected) this.update();
  }

  // Parsed once per diff text; scrolling and repainting reuse the cached model.
  _parsed() {
    const key = String(this.diff ?? "");
    if (this._model === null || key !== this._modelKey) {
      this._model = flattenDiff(parseUnifiedDiff(key));
      this._modelKey = key;
    }
    return this._model;
  }

  update() {
    const model = this._parsed();
    if (!model.virtual) {
      this._mode = "";
      this._refs = null;
      super.update();
      return;
    }
    this._mountVirtual(model);
  }

  render() {
    const files = this._parsed().files;
    if (!files.length) return `<p class="empty">Sem alterações neste passo.</p>`;
    const label = this.getAttribute("label") || "Diff";
    return files.map((f) => `<div class="file" role="group" aria-label="${esc(f.name)}"><p class="head"><span class="name">${esc(f.name)}</span>` +
      `<span class="add">+${f.add}<span class="sr-only"> linhas adicionadas</span></span><span class="del">−${f.del}<span class="sr-only"> linhas removidas</span></span></p>` +
      `<div class="scroll" tabindex="0" role="region" aria-label="${esc(label)}: ${esc(f.name)}"><table><tbody>${f.rows.map((r) =>
        r.kind === "hunk" || r.kind === "meta"
          ? `<tr class="r-${r.kind}"><td colspan="4">${esc(r.text)}</td></tr>`
          : `<tr class="r-${r.kind}"><td class="no">${r.oldNo ?? ""}</td><td class="no">${r.newNo ?? ""}</td>` +
            `<td class="mk" aria-hidden="true">${MARK[r.kind]}</td><td class="code">${SR[r.kind] ? `<span class="sr-only">${SR[r.kind]}: </span>` : ""}${esc(r.text)}</td></tr>`
      ).join("")}</tbody></table></div></div>`).join("");
  }

  // Builds the virtual shell once; later updates keep the scroll box (and its position) and only repaint.
  _mountVirtual(model) {
    const root = this.shadowRoot;
    if (this._mode !== "virtual" || !this._refs?.box.isConnected) {
      root.innerHTML = `<p class="vsum"></p><div class="vbox" tabindex="0" role="region">` +
        `<div class="vsizer"><div class="spacer top"></div><div class="vrows"></div><div class="spacer bot"></div></div></div>`;
      const box = root.querySelector(".vbox");
      box.addEventListener("scroll", () => {
        if (!this._frame) this._frame = requestAnimationFrame(() => { this._frame = 0; this._paint(); });
      });
      this._refs = {
        sum: root.querySelector(".vsum"), box,
        top: root.querySelector(".spacer.top"), bot: root.querySelector(".spacer.bot"), rows: root.querySelector(".vrows"),
      };
      this._mode = "virtual";
      this._shown = null;
    }
    const { sum, box } = this._refs;
    box.setAttribute("aria-label", this.getAttribute("label") || "Diff");
    sum.textContent = `${model.rows} linhas, ${model.files.length} arquivos`;
    if (this._shown !== model) {
      box.scrollTop = 0;
      this._shown = model;
    }
    this._paint();
  }

  // Paints only the items in view plus an overscan; the spacers stand in for everything above and below.
  _paint() {
    const refs = this._refs;
    if (!refs || !refs.box.isConnected || !this._model) return;
    const { items } = this._model;
    const { first, last } = windowRange(refs.box.scrollTop, refs.box.clientHeight || FALLBACK_VIEWPORT, ROW_HEIGHT, items.length, OVERSCAN);
    refs.top.style.blockSize = `${first * ROW_HEIGHT}px`;
    refs.bot.style.blockSize = `${(items.length - last) * ROW_HEIGHT}px`;
    refs.rows.innerHTML = items.slice(first, last).map(itemHtml).join("");
  }
}

define("sl-diff-view", SlDiffView);

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

/**
 * Unified diff viewer. Property/attribute `diff` (unified diff text); without it the element's
 * own text content is used. Attribute `label` names the region.
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
`;

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

  render() {
    const files = parseUnifiedDiff(this.diff);
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
}

define("sl-diff-view", SlDiffView);

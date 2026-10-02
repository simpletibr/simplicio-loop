import { SlElement, define, esc } from "./base.js";

let uid = 0;

/** Rank commands by a forgiving match on label, group and keywords (exported for tests). */
export function filterCommands(commands, query) {
  const q = String(query ?? "").trim().toLowerCase();
  const list = Array.isArray(commands) ? commands.filter((c) => c && c.label) : [];
  if (!q) return list;
  const words = q.split(/\s+/);
  return list
    .map((c) => {
      const label = String(c.label).toLowerCase();
      const hay = `${label} ${c.group ?? ""} ${c.hint ?? ""} ${(c.keywords ?? []).join(" ")}`.toLowerCase();
      if (!words.every((w) => hay.includes(w))) return null;
      return { c, score: label.startsWith(q) ? 0 : label.includes(q) ? 1 : 2 };
    })
    .filter(Boolean)
    .sort((a, b) => a.score - b.score)
    .map((x) => x.c);
}

/**
 * Command palette (Ctrl+K / Cmd+K with the `hotkey` attribute). Property/attribute `commands`:
 * [{ id, label, group, hint, keywords }]. Attributes: label, placeholder, hotkey, no-trigger.
 * Choosing a command fires `sl-command` with { id, command } and closes the dialog; focus returns
 * to where it was. Built on the native modal <dialog> (focus containment, inert page, Escape).
 */
export class SlCommandPalette extends SlElement {
  static observedAttributes = ["commands", "label", "placeholder", "no-trigger"];
  static jsonProps = ["commands"];
  static styles = `
:host { display: inline-block; }
.trigger { display: inline-flex; align-items: center; gap: var(--sl-space-3); padding: var(--sl-space-2) var(--sl-space-2) var(--sl-space-2) var(--sl-space-3);
  border: 1px solid var(--sl-line); border-radius: var(--sl-radius-plate); background: var(--sl-raised); cursor: pointer; font-size: var(--sl-step--1); }
.trigger:hover { border-color: var(--sl-ink-muted); }
kbd { font: inherit; font-size: var(--sl-step--2); padding: 0.1em 0.45em; border-radius: var(--sl-radius-plate);
  border: 1px solid var(--sl-line); color: var(--sl-ink-muted); }
dialog { inline-size: min(40rem, calc(100vw - 2rem)); padding: 0; border: 0; border-radius: var(--sl-radius-panel);
  background: var(--sl-panel); color: var(--sl-ink); box-shadow: 0 0 0 1px var(--sl-line), 0 30px 60px -20px rgb(0 0 0 / 0.6);
  margin-block-start: 12vh; font-family: var(--sl-font-sans); }
dialog::backdrop { background: color-mix(in srgb, var(--sl-bg) 70%, transparent); }
.field { display: flex; align-items: center; gap: var(--sl-space-3); padding: var(--sl-space-3) var(--sl-space-4); border-block-end: 1px solid var(--sl-line-soft); }
input { flex: 1; font: inherit; font-size: var(--sl-step-1); color: var(--sl-ink); background: transparent; border: 0; padding: var(--sl-space-2) 0; }
input:focus-visible { outline: none; }
.field:focus-within { box-shadow: inset 0 -3px 0 var(--sl-focus); }
ul { list-style: none; margin: 0; padding: var(--sl-space-2); max-block-size: min(24rem, 55vh); overflow: auto; }
li { display: grid; grid-template-columns: 1fr auto; gap: var(--sl-space-3); align-items: baseline; padding: var(--sl-space-2) var(--sl-space-3);
  border-radius: var(--sl-radius-plate); cursor: pointer; }
li[aria-selected="true"] { background: var(--sl-ink); color: var(--sl-panel); }
li[aria-selected="true"] .hint { color: inherit; }
.group { font-size: var(--sl-step--2); color: inherit; opacity: 0.85; display: block; }
.hint { font-size: var(--sl-step--1); color: var(--sl-ink-muted); }
.empty { padding: var(--sl-space-4); color: var(--sl-ink-muted); margin: 0; }
.foot { display: flex; gap: var(--sl-space-4); padding: var(--sl-space-2) var(--sl-space-4); border-block-start: 1px solid var(--sl-line-soft);
  font-size: var(--sl-step--2); color: var(--sl-ink-muted); margin: 0; }
:host([no-trigger]) .trigger { display: none; }
`;

  constructor() {
    super();
    this._id = `slcp${++uid}`;
    this._active = 0;
    this._results = [];
    this._onHotkey = (e) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        this.isOpen ? this.close() : this.open();
      }
    };
  }

  connectedCallback() {
    super.connectedCallback();
    if (this.hasAttribute("hotkey")) document.addEventListener("keydown", this._onHotkey);
  }

  disconnectedCallback() {
    document.removeEventListener("keydown", this._onHotkey);
  }

  get isOpen() {
    return Boolean(this.shadowRoot.querySelector("dialog")?.open);
  }

  update() {
    const root = this.shadowRoot;
    if (!root.querySelector("dialog")) {
      const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
      root.innerHTML = `<button class="trigger" type="button" part="trigger" aria-haspopup="dialog"><span class="t-label"></span><kbd>${mac ? "⌘" : "Ctrl"} K</kbd></button>
<dialog part="dialog"><div class="field"><input type="text" role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls="${this._id}-list" autocomplete="off" spellcheck="false"></div>
<ul id="${this._id}-list" role="listbox"></ul>
<p class="foot" aria-hidden="true"><span>↑ ↓ navegar</span><span>Enter executar</span><span>Esc fechar</span></p></dialog>`;
      root.querySelector(".trigger").addEventListener("click", () => this.open());
      const input = root.querySelector("input");
      input.addEventListener("input", () => { this._active = 0; this._renderList(); });
      input.addEventListener("keydown", (e) => this._onKey(e));
      const list = root.querySelector("ul");
      list.addEventListener("click", (e) => { const li = e.target.closest("li[data-i]"); if (li) this._choose(Number(li.dataset.i)); });
      list.addEventListener("pointermove", (e) => {
        const li = e.target.closest("li[data-i]");
        if (li && Number(li.dataset.i) !== this._active) { this._active = Number(li.dataset.i); this._renderList(); }
      });
      root.querySelector("dialog").addEventListener("close", () => this.emit("sl-close", {}));
    }
    const label = this.getAttribute("label") || "Buscar comandos";
    root.querySelector(".t-label").textContent = label;
    root.querySelector("dialog").setAttribute("aria-label", label);
    const input = root.querySelector("input");
    input.setAttribute("aria-label", label);
    input.placeholder = this.getAttribute("placeholder") || "Run, fase, gate ou ação";
    this._renderList();
  }

  open() {
    const dialog = this.shadowRoot.querySelector("dialog");
    if (!dialog || dialog.open) return;
    const input = this.shadowRoot.querySelector("input");
    input.value = "";
    this._active = 0;
    this._renderList();
    dialog.showModal();
    input.focus();
    this.emit("sl-open", {});
  }

  close() {
    this.shadowRoot.querySelector("dialog")?.close();
  }

  _renderList() {
    const input = this.shadowRoot.querySelector("input");
    const list = this.shadowRoot.querySelector("ul");
    this._results = filterCommands(this.commands, input.value);
    this._active = Math.min(this._active, Math.max(0, this._results.length - 1));
    if (!this._results.length) {
      list.innerHTML = `<li class="empty" role="option" aria-disabled="true" aria-selected="false">Nenhum comando para "${esc(input.value)}". Tente o nome da fase, do run ou do gate.</li>`;
      input.removeAttribute("aria-activedescendant");
      return;
    }
    list.innerHTML = this._results.map((c, i) => `<li id="${this._id}-o${i}" role="option" data-i="${i}" aria-selected="${i === this._active}">` +
      `<span>${c.group ? `<span class="group">${esc(c.group)}</span>` : ""}${esc(c.label)}</span>${c.hint ? `<span class="hint">${esc(c.hint)}</span>` : ""}</li>`).join("");
    input.setAttribute("aria-activedescendant", `${this._id}-o${this._active}`);
    list.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: "nearest" });
  }

  _onKey(e) {
    const n = this._results.length;
    const moves = { ArrowDown: 1, ArrowUp: -1, PageDown: 5, PageUp: -5 };
    if (e.key in moves && n) {
      e.preventDefault();
      this._active = (this._active + moves[e.key] + n * 5) % n;
      this._renderList();
    } else if (e.key === "Enter" && n) {
      e.preventDefault();
      this._choose(this._active);
    }
  }

  _choose(i) {
    const command = this._results[i];
    if (!command) return;
    this.close();
    this.emit("sl-command", { id: command.id ?? command.label, command });
  }
}

define("sl-command-palette", SlCommandPalette);

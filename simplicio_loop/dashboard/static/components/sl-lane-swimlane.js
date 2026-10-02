import { SlElement, STATES, define, esc, lamp, normState } from "./base.js";
import { PHASES, phaseMeta } from "./phase-meta.js";

/**
 * Lanes (worktrees) x phases. Property/attribute `lanes`:
 * [{ id, label, detail, stages: { <phase>: "PASS" | { state, retries, duration } } }]
 * Optional `phases` (array of phase keys) narrows the columns; attribute `label` names the table.
 */
export class SlLaneSwimlane extends SlElement {
  static observedAttributes = ["lanes", "phases", "label"];
  static jsonProps = ["lanes", "phases"];
  static styles = `
:host { display: block; }
.scroll { overflow-x: auto; border-radius: var(--sl-radius-panel); background: var(--sl-panel);
  box-shadow: var(--sl-shadow), inset 0 0 0 1px var(--sl-line-soft); }
table { border-collapse: separate; border-spacing: 0; inline-size: 100%; min-inline-size: 48rem; }
caption { text-align: start; padding: var(--sl-space-4) var(--sl-space-4) 0; font-weight: var(--sl-weight-strong);
  font-size: var(--sl-step-1); }
th, td { padding: var(--sl-space-3) var(--sl-space-2); text-align: center; vertical-align: middle; }
thead th { font-size: var(--sl-step--2); font-weight: var(--sl-weight-body); color: var(--sl-ink-muted);
  line-height: var(--sl-leading-tight); border-block-end: 1px solid var(--sl-line-soft); }
thead th .emoji { display: block; font-size: var(--sl-step-1); margin-block-end: var(--sl-space-1); }
th[scope="row"] { text-align: start; padding-inline-start: var(--sl-space-4); min-inline-size: 11em; }
th[scope="row"] .lane { display: block; font-weight: var(--sl-weight-strong); }
th[scope="row"] .detail { display: block; color: var(--sl-ink-muted); font-size: var(--sl-step--2); font-weight: var(--sl-weight-body); }
tbody tr + tr > * { border-block-start: 1px solid var(--sl-line-soft); }
td { position: relative; }
td::before { content: ""; position: absolute; inset-inline: 0; top: 50%; block-size: 4px; translate: 0 -50%;
  background: var(--seg, var(--sl-line-soft)); }
td[data-state="PASS"] { --seg: color-mix(in srgb, var(--sl-state-pass) 55%, transparent); }
td:last-child::before { inset-inline-end: 50%; }
td:nth-child(2)::before { inset-inline-start: 50%; }
.cell { position: relative; display: inline-grid; justify-items: center; gap: 2px; }
.lamp { --size: 1.7em; }
.meta { font-size: var(--sl-step--2); color: var(--sl-ink); background: var(--sl-panel); padding-inline: 0.3em;
  border-radius: var(--sl-radius-plate); line-height: 1.2; }
.empty { padding: var(--sl-space-5); color: var(--sl-ink-muted); margin: 0; }
`;

  render() {
    const lanes = Array.isArray(this.lanes) ? this.lanes : [];
    const phases = Array.isArray(this.phases) && this.phases.length ? this.phases : PHASES;
    const label = this.getAttribute("label") || "Lanes por fase";
    if (!lanes.length) {
      return `<div class="scroll"><p class="empty">Nenhuma lane ativa. As lanes aparecem quando um worker cria a worktree do run.</p></div>`;
    }
    const head = phases.map((p) => {
      const m = phaseMeta(p);
      return `<th scope="col"><span class="emoji" aria-hidden="true">${m.icon}</span>${esc(m.label)}</th>`;
    }).join("");
    const rows = lanes.map((lane) => {
      const stages = lane?.stages || {};
      const cells = phases.map((p) => {
        const raw = stages[p];
        const info = raw && typeof raw === "object" ? raw : { state: raw };
        const state = normState(info.state);
        const retries = Number(info.retries) > 0 ? Number(info.retries) : 0;
        const extra = [retries ? `${retries}× retry` : "", info.duration ? String(info.duration) : ""].filter(Boolean);
        return `<td data-state="${state}"><span class="cell">${lamp(state, state === "RUNNING" ? "live" : "")}` +
          `<span class="sr-only">${esc(phaseMeta(p).label)}: ${STATES[state]}</span>${
            extra.length ? `<span class="meta">${esc(extra.join(" "))}</span>` : ""}</span></td>`;
      }).join("");
      return `<tr><th scope="row"><span class="lane">${esc(lane?.label ?? lane?.id ?? "lane")}</span>${
        lane?.detail ? `<span class="detail">${esc(lane.detail)}</span>` : ""}</th>${cells}</tr>`;
    }).join("");
    return `<div class="scroll" tabindex="0" role="region" aria-label="${esc(label)}"><table><caption>${esc(label)}</caption>
<thead><tr><th scope="col">Lane</th>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }
}

define("sl-lane-swimlane", SlLaneSwimlane);

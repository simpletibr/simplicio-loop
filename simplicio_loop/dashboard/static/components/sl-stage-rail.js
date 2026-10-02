import { SlElement, STATES, define, esc, lamp, normState, toNumber } from "./base.js";
import { PHASES, phaseMeta } from "./phase-meta.js";

const OFF_RAIL = { blocked: "BLOCKED", cancelled: "FAIL", awaiting_decision: "STALLED" };

/**
 * The run's phases drawn as a lit track diagram (signal-box mimic panel).
 * Attributes: phase, status (state of the current phase), percent, receipt-ready,
 * at (phase where an off-rail run left the track), reason, label.
 * Honesty rule (docs/PROGRESS_PROTOCOL.md): 100% only with receipt-ready.
 */
export class SlStageRail extends SlElement {
  static observedAttributes = ["phase", "status", "percent", "receipt-ready", "at", "reason", "label"];
  static styles = `
:host { display: block; container-type: inline-size; }
.rail { background: var(--sl-panel); border-radius: var(--sl-radius-panel); padding: var(--sl-space-5);
  box-shadow: var(--sl-shadow), inset 0 0 0 1px var(--sl-line-soft); }
.now { display: flex; align-items: baseline; gap: var(--sl-space-3); flex-wrap: wrap; margin: 0 0 var(--sl-space-5); }
.now .emoji { font-size: var(--sl-step-3); }
.now .label { font-size: var(--sl-step-3); font-weight: var(--sl-weight-strong); line-height: var(--sl-leading-tight); }
.now .state-text { font-size: var(--sl-step-0); }
.pct { margin-inline-start: auto; font-size: var(--sl-step-4); font-weight: var(--sl-weight-strong); line-height: 1; }
.pct small { font-size: 0.5em; color: var(--sl-ink-muted); font-weight: var(--sl-weight-body); }
.track { --n: 8; list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); }
.station { position: relative; display: grid; justify-items: center; align-content: start; gap: var(--sl-space-2);
  text-align: center; padding-inline: var(--sl-space-1); }
.station::before { content: ""; position: absolute; inset-inline: 0; top: calc(1.2em - var(--sl-track-width) / 2);
  block-size: var(--sl-track-width); background: var(--seg); z-index: 0; }
.station:first-child::before { inset-inline-start: 50%; }
.station:last-child::before { inset-inline-end: 50%; }
.station[data-seg="done"] { --seg: var(--sl-state-pass); }
.station[data-seg="todo"] { --seg: repeating-linear-gradient(90deg, var(--sl-line) 0 10px, transparent 10px 16px); }
.station[data-seg="current"] { --seg: linear-gradient(90deg, var(--sl-state-pass) 50%, var(--sl-line) 50%); }
.station:first-child[data-seg="current"] { --seg: var(--sl-line); }
.lamp { --size: 2.4em; position: relative; z-index: 1; font-size: 1em; }
.lamp .icon { inline-size: 1.4em; block-size: 1.4em; }
.station[aria-current] .lamp { --size: 2.4em; outline: 3px solid var(--sl-c); outline-offset: 4px; }
.name { font-size: var(--sl-step--1); line-height: var(--sl-leading-tight); color: var(--sl-ink-muted); text-wrap: balance; }
.station[data-state="PASS"] .name, .station[aria-current] .name { color: var(--sl-ink); }
.station[aria-current] .name { font-weight: var(--sl-weight-strong); }
.emoji { font-size: var(--sl-step-0); line-height: 1; }
.siding { --col: 0; margin-block-start: var(--sl-space-3);
  margin-inline-start: clamp(0%, calc((var(--col) + 0.5) / var(--n) * 100% - 1.2em), calc(100% - 22em));
  display: grid; grid-template-columns: auto 1fr; gap: var(--sl-space-1) var(--sl-space-3); align-items: center;
  max-inline-size: 26em; position: relative; padding: var(--sl-space-3); border-radius: var(--sl-radius-plate);
  border-inline-start: 6px solid var(--sl-c); background: color-mix(in srgb, var(--sl-c) 12%, var(--sl-raised)); }
.siding strong { font-weight: var(--sl-weight-strong); }
.siding .reason { grid-column: 2; color: var(--sl-ink); font-size: var(--sl-step--1); }
.note { margin: var(--sl-space-4) 0 0; font-size: var(--sl-step--1); color: var(--sl-ink-muted); }
@container (max-width: 40rem) {
  .track { grid-template-columns: 1fr; }
  .station { grid-template-columns: auto auto 1fr; justify-items: start; align-items: center; text-align: start;
    padding-block: var(--sl-space-2); column-gap: var(--sl-space-3); }
  .station::before { inset-inline: auto; inset-block: 0; left: calc(1.2em + var(--sl-space-1) - var(--sl-track-width) / 2);
    top: 0; block-size: auto; inline-size: var(--sl-track-width); }
  .station:first-child::before { inset-inline-start: auto; top: 50%; }
  .station:last-child::before { inset-inline-end: auto; bottom: 50%; }
  .station[data-seg="todo"] { --seg: repeating-linear-gradient(180deg, var(--sl-line) 0 10px, transparent 10px 16px); }
  .station[data-seg="current"] { --seg: linear-gradient(180deg, var(--sl-state-pass) 50%, var(--sl-line) 50%); }
  .siding { margin-inline-start: 0; }
  .pct { margin-inline-start: 0; inline-size: 100%; }
}
`;

  /** Pure model, exposed for tests and for consumers that render their own summary. */
  get model() {
    const raw = String(this.getAttribute("phase") || "intake");
    const ready = this.hasAttribute("receipt-ready");
    const offRail = Object.hasOwn(OFF_RAIL, raw);
    const at = offRail ? this.getAttribute("at") || "intake" : raw;
    let index = PHASES.indexOf(at);
    if (index < 0) index = 0;
    let current = normState(this.getAttribute("status"), offRail ? OFF_RAIL[raw] : "RUNNING");
    const doneWithoutReceipt = raw === "done" && !ready;
    if (raw === "done") current = ready ? "PASS" : "UNVERIFIED";
    const stations = PHASES.map((phase, i) => ({
      phase,
      state: i < index ? "PASS" : i === index ? (offRail ? "PENDING" : current) : "PENDING",
      seg: i < index ? "done" : i === index ? (raw === "done" && ready ? "done" : "current") : "todo",
    }));
    const pctAttr = this.getAttribute("percent");
    let percent = pctAttr == null || raw === "cancelled" ? null : Math.max(0, Math.round(toNumber(pctAttr, 0)));
    if (ready && raw === "done") percent = 100;
    else if (percent != null) percent = Math.min(99, percent);
    return { phase: raw, offRail, index, current, stations, percent, doneWithoutReceipt };
  }

  render() {
    const m = this.model;
    const meta = phaseMeta(m.phase);
    const reason = this.getAttribute("reason");
    const stations = m.stations.map((s, i) => {
      const pm = phaseMeta(s.phase);
      const cur = i === m.index && !m.offRail ? ' aria-current="step"' : "";
      return `<li class="station" data-state="${s.state}" data-seg="${s.seg}"${cur} title="${esc(s.phase)}">${
        lamp(s.state, s.state === "RUNNING" ? "live" : "")}<span class="emoji" aria-hidden="true">${pm.icon}</span>` +
        `<span class="name">${esc(pm.label)}<span class="sr-only">: ${STATES[s.state]}</span></span></li>`;
    }).join("");
    const siding = m.offRail
      ? `<div class="siding" data-state="${m.current}" data-css="--col:${m.index};--n:${m.stations.length}" role="status">${lamp(m.current)}` +
        `<strong>${meta.icon} ${esc(meta.label)}</strong>${reason ? `<span class="reason">${esc(reason)}</span>` : ""}</div>`
      : "";
    const pct = m.percent == null ? "" : `<span class="pct">${m.percent}<small>%</small></span>`;
    const note = m.doneWithoutReceipt
      ? `<p class="note">Sem recibo de conclusão com ready: true, então o progresso fica abaixo de 100%.</p>`
      : !m.offRail && reason ? `<p class="note">${esc(reason)}</p>` : "";
    return `<div class="rail" part="rail" role="group" aria-label="${esc(this.getAttribute("label") || "Fases do run")}">
<p class="now" data-state="${m.current}"><span class="emoji" aria-hidden="true">${meta.icon}</span>` +
      `<span class="label">${esc(meta.label)}</span><span class="state-text">${STATES[m.current]}</span>${pct}</p>
<ol class="track" data-css="--n:${m.stations.length}">${stations}</ol>${siding}${note}</div>`;
  }
}

define("sl-stage-rail", SlStageRail);

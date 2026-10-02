// Generated from simplicio_loop/progress.py PHASE_META by
// `python -m simplicio_loop.dashboard.phase_meta`. Do not edit by hand.
export const PHASES = Object.freeze(["intake", "mapping", "planning", "executing", "validating", "watching", "delivering", "done"]);
export const PHASE_META = Object.freeze({
  "intake": {
    "icon": "📥",
    "label": "Contrato recebido"
  },
  "mapping": {
    "icon": "🗺️",
    "label": "Contexto mapeado"
  },
  "planning": {
    "icon": "🧭",
    "label": "Plano congelado"
  },
  "executing": {
    "icon": "⚙️",
    "label": "Execução em andamento"
  },
  "validating": {
    "icon": "🧪",
    "label": "Validação e evidências"
  },
  "watching": {
    "icon": "👁️",
    "label": "Watcher verificando"
  },
  "delivering": {
    "icon": "📦",
    "label": "Entrega reconciliada"
  },
  "done": {
    "icon": "✅",
    "label": "Concluído pelo oracle"
  },
  "blocked": {
    "icon": "⛔",
    "label": "Bloqueado"
  },
  "cancelled": {
    "icon": "🛑",
    "label": "Cancelado"
  },
  "awaiting_decision": {
    "icon": "⏸️",
    "label": "Aguardando decisão"
  }
});
export function phaseMeta(phase) {
  const key = String(phase ?? "");
  return PHASE_META[key] ?? { icon: "•", label: key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) };
}

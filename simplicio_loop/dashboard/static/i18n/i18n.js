// EN locale of the Live page. pt-BR is the default; `?lang=en` switches the chrome to English.
// Exact-match dictionary applied to text nodes and label attributes, kept in sync by a MutationObserver
// so strings the page renders later are translated too. Unknown strings stay in pt-BR.
export const EN = {
  'Pipeline vivo': 'Live pipeline',
  'Agentes, modelos e custo': 'Agents, models and cost',
  'Agora': 'Now',
  'Aguardando eventos…': 'Waiting for events…',
  'Alertas ativos': 'Active alerts',
  'Alertas do run': 'Run alerts',
  'Ativar notificações do navegador': 'Enable browser notifications',
  'Buscar comandos': 'Search commands',
  'Comando': 'Command',
  'Sinais do worker': 'Worker signals',
  'Comandos': 'Commands',
  'Comandos para reproduzir o run': 'Commands to reproduce the run',
  'Contexto': 'Context',
  'Contexto do mapeamento': 'Mapping context',
  'Contrato': 'Contract',
  'Contrato da tarefa': 'Task contract',
  'Convergência': 'Convergence',
  'Custo por iteração': 'Cost by iteration',
  'Custo por tarefa': 'Cost by task',
  'Definição de pronto': 'Definition of done',
  'Detalhe': 'Detail',
  'Economia acumulada': 'Cumulative savings',
  'Economia de tokens': 'Token savings',
  'Eventos por minuto': 'Events per minute',
  'Fase, tarefa, run ou arquivo': 'Phase, task, run or file',
  'Fases': 'Phases',
  'Fases do run': 'Run phases',
  'Fechar': 'Close',
  'Fila e coordenação': 'Queue and coordination',
  'Fila por estado': 'Queue by state',
  'Gates pendentes por iteração': 'Pending gates per iteration',
  'Histórico e tendências': 'History and trends',
  'Indicadores': 'Indicators',
  'Iterações': 'Iterations',
  'Iterações do run': 'Run iterations',
  'Lanes do run': 'Run lanes',
  'Progresso': 'Progress',
  'Progresso do run': 'Run progress',
  'Providers interceptáveis': 'Interceptable providers',
  'Próximo': 'Next',
  'Quadro por etapa': 'Board by stage',
  'Qualidade': 'Quality',
  'Recibos': 'Receipts',
  'Recibos do run': 'Run receipts',
  'Registro do detalhe': 'Detail log',
  'Requisições capturadas': 'Captured requests',
  'Resumo': 'Summary',
  'Seguir o run': 'Follow the run',
  'Seções do detalhe': 'Detail sections',
  'Tempo na fase': 'Time in phase',
  'Tokens economizados': 'Tokens saved',
  'Tokens por fase e modelo': 'Tokens by phase and model',
  'Último heartbeat': 'Last heartbeat',
};

const ATTRS = ['aria-label', 'label', 'placeholder', 'title'];

function tr(value) {
  const key = value.trim();
  const out = EN[key];
  return out === undefined ? value : value.replace(key, out);
}

function walk(node) {
  if (node.nodeType === 3) {
    const next = tr(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
    return;
  }
  if (node.nodeType !== 1) return;
  for (const a of ATTRS) {
    const v = node.getAttribute(a);
    if (v) {
      const next = tr(v);
      if (next !== v) node.setAttribute(a, next);
    }
  }
  for (const child of node.childNodes) walk(child);
}

export function wanted(search) {
  return new URLSearchParams(search).get('lang') === 'en';
}

if (typeof document !== 'undefined' && wanted(location.search)) {
  document.documentElement.lang = 'en';
  document.title = 'Simplicio Live · Live pipeline';
  walk(document.body);
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'characterData') walk(r.target);
      else if (r.type === 'attributes') walk(r.target);
      else r.addedNodes.forEach(walk);
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

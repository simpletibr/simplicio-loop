// Wires the history panel to the API: one load of the list, trends, heatmap and learn lessons, repeated on a timer, and a
// comparison read when the viewer picks two runs. readApi returns the parsed JSON or null; setText sets an element's text.
import { createHistory } from '/static/history/history-view.js';

const HISTORY_POLL_MS = 30000;

export function startHistory(readApi, setText) {
  const view = createHistory(document.getElementById('history-root'), document.getElementById('history-status'));
  let data = { records: [], trends: null, heatmap: null, compare: null, lessons: [] };
  const draw = () => view.render(data, { onCompare: loadCompare });

  async function loadCompare(a, b) {
    const reply = await readApi('/api/history/compare?a=' + encodeURIComponent(a) + '&b=' + encodeURIComponent(b));
    data = { ...data, compare: reply };
    draw();
  }

  async function load() {
    const [list, trendReply, heat, lessons] = await Promise.all([
      readApi('/api/history'), readApi('/api/history/trends?bucket=week'),
      readApi('/api/history/heatmap'), readApi('/api/history/lessons'),
    ]);
    if (list === null) {
      setText(document.getElementById('history-status'), 'Não foi possível ler o histórico.');
      return;
    }
    data = {
      ...data,
      records: Array.isArray(list.history) ? list.history : [],
      trends: trendReply && Array.isArray(trendReply.trends) ? trendReply.trends : null,
      heatmap: heat && Array.isArray(heat.heatmap) ? heat.heatmap : null,
      lessons: lessons && Array.isArray(lessons.lessons) ? lessons.lessons : [],
    };
    draw();
  }

  load();
  setInterval(load, HISTORY_POLL_MS);
}

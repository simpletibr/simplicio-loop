'''Unit tests for the Langfuse widget of the Simplicio Live extras panel (issue #1610, Langfuse widget, TDD red).

The widget reads GET /api/runs/<run_id>/langfuse body and displays the chip state, trace link, and comparison gates.
The view (static/extras/langfuse.js) exports:
  - viewOf(reply): pure function that maps the reply to {state, label, reason, queue, link, notice, warn, gates, tokens, cost}
    or null if reply is invalid or chip.state is not recognized.
  - startLangfuse(readApi, runId, anchor): polls /api/runs/<run_id>/langfuse every 10000ms and renders a <section>.

The module runs in node through a stub document; the wiring in extras.js is checked on the sources.
langfuse.js never uses innerHTML/outerHTML/insertAdjacentHTML/eval/DOMParser/inline styles, never contains 'http://'/'https://',
and never contains the words claude/haiku/sonnet/opus.
'''
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'simplicio_loop' / 'dashboard' / 'static'
EXTRAS_DIR = STATIC / 'extras'
LANGFUSE_MODULE = os.environ.get('D1_LANGFUSE_MODULE', str(EXTRAS_DIR / 'langfuse.js'))
STYLE = EXTRAS_DIR / 'extras.css'
# Same forbidden patterns as test_live_extras_unit.py plus URL literals
FORBIDDEN = [r'\binnerHTML\b', r'\bouterHTML\b', r'\binsertAdjacentHTML\b', r'\bdocument\s*\.\s*write', r'\beval\s*\(',
             r'https?://', r'setAttribute\(\s*.style', r'\.style\s*=', r'\.style\s*\.(?!setProperty\()', r'\.style\s*\[',
             r'\.style\s*\?\.', r'\bstyle\s*\[', r'Object\s*\.\s*assign\s*\([^)]*style', r"setProperty\(\s*(?!'width',)",
             r'\bcssText\b', r'\b(?:claude|haiku|sonnet|opus)\b', r"\[\s*['\"]style['\"]\s*\]",
             r'\{[^}]*\bstyle\b[^}]*\}\s*=', r'\bsetAttributeNS\b', r'\binsertAdjacentElement\b',
             r'\bcreateContextualFragment\b', r'\bDOMParser\b', r'\bsrcdoc\b', r'\b(?:setHTML|setHTMLUnsafe|parseHTMLUnsafe)\b']
MOTION = re.compile(r'(?<![\w-])(?:animation|transition)(?:-[a-z-]+)?\s*:', re.IGNORECASE)

VALID_REPLY = {
    "schema": "simplicio.dashboard-langfuse/v1",
    "chip": {"state": "ok", "label": "em dia", "reason": None},
    "queue": 5,
    "trace": {"id": "0123456789abcdef0123456789abcdef", "url": "https://langfuse.example.com/trace/0123456789abcdef0123456789abcdef", "exported": True},
    "compare": {
        "state": "OK",
        "reason": None,
        "gates": [{"name": "token_count", "passed": True, "langfuse": "igual"}],
        "tokens": {"loop": {"input": 100, "output": 50}, "langfuse": {"input": 100, "output": 50}, "diverge": False},
        "cost": {"state": "UNVERIFIED", "reason": None}
    }
}

def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed')


def _view(reply):
    '''Call viewOf(reply) in node and return the result.'''
    script = f'''
import fs from 'node:fs';
import {{ viewOf }} from {repr(Path(LANGFUSE_MODULE).as_uri())};
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(viewOf(input.reply)));
'''
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], 
                         input=json.dumps({'reply': reply}), 
                         capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f'stderr: {proc.stderr}'
    return json.loads(proc.stdout)


def test_langfuse_module_exports_the_contract():
    '''viewOf and startLangfuse must be exported.'''
    text = Path(LANGFUSE_MODULE).read_text(encoding='utf-8')
    for name in ('viewOf', 'startLangfuse'):
        assert re.search(rf'export\s+(?:const|let|function)\s+{name}\b', text), f'{name} not exported'


def test_viewof_returns_null_for_null_reply():
    '''null reply => null view.'''
    assert _view(None) is None


def test_viewof_returns_null_for_foreign_schema():
    '''Foreign schema => null view.'''
    reply = dict(VALID_REPLY, schema='simplicio.other/v1')
    assert _view(reply) is None


def test_viewof_returns_null_for_missing_chip():
    '''Missing chip => null view.'''
    reply = {k: v for k, v in VALID_REPLY.items() if k != 'chip'}
    assert _view(reply) is None


def test_viewof_returns_null_for_invalid_chip_state():
    '''Invalid chip.state => null view.'''
    reply = dict(VALID_REPLY, chip={'state': 'invalid_state', 'label': 'x', 'reason': None})
    assert _view(reply) is None


def test_viewof_off_state_shows_only_chip():
    '''When chip.state === "off", all other fields are null/empty even if reply has them.'''
    reply = dict(VALID_REPLY, chip={'state': 'off', 'label': 'desligado', 'reason': None})
    view = _view(reply)
    assert view is not None
    assert view['state'] == 'off'
    assert view['label'] == 'Langfuse: desligado'
    assert view['reason'] is None
    assert view['queue'] is None
    assert view['link'] is None
    assert view['notice'] is None
    assert view['warn'] is None
    assert view['gates'] == []
    assert view['tokens'] is None
    assert view['cost'] is None


def test_viewof_off_state_ignores_extra_lixo():
    '''off state ignores queue, trace, gates even if they are in reply.'''
    reply = dict(VALID_REPLY, 
                 chip={'state': 'off', 'label': 'desligado', 'reason': None},
                 queue=999,
                 trace={'id': 'abc', 'url': 'https://example.com', 'exported': False},
                 compare={'state': 'DIVERGE', 'reason': 'nope', 'gates': [{'name': 'x', 'passed': True, 'langfuse': 'diverge'}]})
    view = _view(reply)
    assert view['state'] == 'off'
    assert view['queue'] is None
    assert view['link'] is None
    assert view['gates'] == []


def test_viewof_ok_state_shows_label_and_full_data():
    '''When chip.state === "ok", label, queue, link, gates, tokens, cost are shown.'''
    view = _view(VALID_REPLY)
    assert view is not None
    assert view['state'] == 'ok'
    assert view['label'] == 'Langfuse: em dia'
    assert view['reason'] is None
    assert view['queue'] == 'Fila em disco: 5'
    assert view['link'] == {'href': 'https://langfuse.example.com/trace/0123456789abcdef0123456789abcdef', 'text': 'Abrir trace no Langfuse'}
    assert view['notice'] is None
    assert view['warn'] is None


def test_viewof_sends_state_shows_label_and_full_data():
    '''When chip.state === "sending", similar to ok.'''
    reply = dict(VALID_REPLY, chip={'state': 'sending', 'label': 'enviando', 'reason': None})
    view = _view(reply)
    assert view['state'] == 'sending'
    assert view['label'] == 'Langfuse: enviando'


def test_viewof_late_state_shows_label_and_full_data():
    '''When chip.state === "late", similar to ok.'''
    reply = dict(VALID_REPLY, chip={'state': 'late', 'label': 'atrasado 5 min', 'reason': None})
    view = _view(reply)
    assert view['state'] == 'late'
    assert view['label'] == 'Langfuse: atrasado 5 min'


def test_viewof_error_state_shows_label_no_link():
    '''When chip.state === "error", link is null even if trace.url is valid.'''
    reply = dict(VALID_REPLY, chip={'state': 'error', 'label': 'erro', 'reason': 'falha ao enviar'})
    view = _view(reply)
    assert view['state'] == 'error'
    assert view['label'] == 'Langfuse: erro'
    assert view['reason'] == 'falha ao enviar'
    assert view['link'] is None
    assert view['queue'] == 'Fila em disco: 5'


def test_viewof_link_requires_valid_https_or_http_url():
    '''Link only when trace.url is https:// or http://.'''
    # Valid https
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'https://example.com/trace/x', 'exported': True})
    assert _view(reply)['link'] is not None
    
    # Valid http (rare but allowed)
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'http://example.com/trace/x', 'exported': True})
    assert _view(reply)['link'] is not None
    
    # javascript: is rejected
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'javascript:alert(1)', 'exported': True})
    assert _view(reply)['link'] is None
    
    # data: is rejected
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'data:text/html,...', 'exported': True})
    assert _view(reply)['link'] is None
    
    # Invalid URL throws; link => null
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': '::not a url', 'exported': True})
    assert _view(reply)['link'] is None


def test_viewof_notice_when_trace_not_exported():
    '''When trace.exported === false, notice = "Trace ainda não enviado ao Langfuse" (with accents).'''
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'https://example.com/x', 'exported': False})
    view = _view(reply)
    assert view['notice'] == 'Trace ainda não enviado ao Langfuse'
    
    # When exported === true, notice is null
    reply = dict(VALID_REPLY, trace={'id': 'x', 'url': 'https://example.com/x', 'exported': True})
    view = _view(reply)
    assert view['notice'] is None


def test_viewof_warn_when_diverge():
    '''When compare.state === "DIVERGE", warn = "Atenção: o Langfuse tem valores diferentes dos do loop" (with accent).'''
    reply = dict(VALID_REPLY, compare={'state': 'DIVERGE', 'reason': None, 'gates': [], 'tokens': None, 'cost': None})
    view = _view(reply)
    assert view['warn'] == 'Atenção: o Langfuse tem valores diferentes dos do loop'
    
    # When state === "OK", warn is null
    reply = dict(VALID_REPLY, compare={'state': 'OK', 'reason': None, 'gates': [], 'tokens': None, 'cost': None})
    view = _view(reply)
    assert view['warn'] is None


def test_viewof_gates_list():
    '''Gates appear as {text, state}; text = "<name>: passou|falhou — Langfuse: <langfuse>" (with "não" accent).'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [
            {'name': 'token_count', 'passed': True, 'langfuse': 'igual'},
            {'name': 'cost', 'passed': False, 'langfuse': 'diverge'},
            {'name': 'unknown_gate', 'passed': True, 'langfuse': 'não enviado'},
        ],
        'tokens': None,
        'cost': None
    })
    view = _view(reply)
    gates = view['gates']
    assert len(gates) >= 2
    # First gate: passed, langfuse = igual
    assert any('token_count' in g['text'] and 'passou' in g['text'] and 'igual' in g['text'] and g['state'] == 'PASS' for g in gates)
    # Second gate: failed, langfuse = diverge
    assert any('cost' in g['text'] and 'falhou' in g['text'] and 'diverge' in g['text'] and g['state'] == 'DIVERGE' for g in gates)


def test_viewof_gates_rejects_malformed():
    '''Malformed gates (name not string/empty, passed not bool) are discarded.'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [
            {'name': 'good', 'passed': True, 'langfuse': 'igual'},
            {'name': '', 'passed': True, 'langfuse': 'igual'},  # empty name
            {'name': 'bad_type', 'passed': 'not bool', 'langfuse': 'igual'},  # passed not bool
            {'name': None, 'passed': True, 'langfuse': 'igual'},  # name not string
        ],
        'tokens': None,
        'cost': None
    })
    view = _view(reply)
    gates = view['gates']
    assert len(gates) == 1
    assert 'good' in gates[0]['text']


def test_viewof_gates_max_20():
    '''At most 20 gates are shown; rest are discarded.'''
    gates_list = [{'name': f'gate_{i}', 'passed': True, 'langfuse': 'igual'} for i in range(25)]
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': gates_list,
        'tokens': None,
        'cost': None
    })
    view = _view(reply)
    assert len(view['gates']) == 20


def test_viewof_tokens_missing():
    '''When tokens absent, tokens field = null.'''
    reply = dict(VALID_REPLY, compare={'state': 'OK', 'reason': None, 'gates': [], 'tokens': None, 'cost': None})
    view = _view(reply)
    assert view['tokens'] is None


def test_viewof_tokens_present_and_measured():
    '''When tokens present with both sides measured and equal, state=PASS.'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [],
        'tokens': {'loop': {'input': 100, 'output': 50}, 'langfuse': {'input': 100, 'output': 50}, 'diverge': False},
        'cost': None
    })
    view = _view(reply)
    tokens = view['tokens']
    assert tokens is not None
    assert 'Tokens medidos' in tokens['text']
    assert 'entrada 100' in tokens['text']
    assert 'saída 50' in tokens['text']
    assert tokens['state'] == 'PASS'


def test_viewof_tokens_diverge():
    '''When tokens.diverge === true, state=DIVERGE.'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [],
        'tokens': {'loop': {'input': 100, 'output': 50}, 'langfuse': {'input': 120, 'output': 55}, 'diverge': True},
        'cost': None
    })
    view = _view(reply)
    tokens = view['tokens']
    assert tokens['state'] == 'DIVERGE'


def test_viewof_tokens_with_null_sides():
    '''When a side is null, shows "não medido" (with accent).'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [],
        'tokens': {'loop': {'input': 100, 'output': 50}, 'langfuse': None, 'diverge': False},
        'cost': None
    })
    view = _view(reply)
    tokens = view['tokens']
    assert 'não medido' in tokens['text']


def test_viewof_cost_missing():
    '''When cost absent, cost field = null.'''
    reply = dict(VALID_REPLY, compare={'state': 'OK', 'reason': None, 'gates': [], 'tokens': None, 'cost': None})
    view = _view(reply)
    assert view['cost'] is None


def test_viewof_cost_unverified_with_reason():
    '''When cost.reason is string, cost = {text, state:UNVERIFIED}.'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [],
        'tokens': None,
        'cost': {'state': 'UNVERIFIED', 'reason': 'preço não disponível'}
    })
    view = _view(reply)
    cost = view['cost']
    assert cost is not None
    assert 'Custo:' in cost['text']
    assert 'preço não disponível' in cost['text']
    assert cost['state'] == 'UNVERIFIED'


def test_viewof_cost_no_reason():
    '''When cost.reason is null, cost field = null.'''
    reply = dict(VALID_REPLY, compare={
        'state': 'OK',
        'reason': None,
        'gates': [],
        'tokens': None,
        'cost': {'state': 'UNVERIFIED', 'reason': None}
    })
    view = _view(reply)
    assert view['cost'] is None


def test_langfuse_module_forbids_dynamic_html_and_url_literals():
    '''The module must not contain innerHTML, outerHTML, insertAdjacentHTML, eval, DOMParser, 
       http:// or https:// literals, or the words claude/haiku/sonnet/opus.'''
    text = Path(LANGFUSE_MODULE).read_text(encoding='utf-8')
    for pattern in FORBIDDEN:
        assert not re.search(pattern, text), f'Forbidden pattern {pattern} found in {LANGFUSE_MODULE}'


def test_the_lf_css_uses_only_design_tokens_and_has_no_motion():
    text = STYLE.read_text(encoding='utf-8')
    css = re.sub(r'/\*.*?\*/', '', text[text.index('/* Langfuse widget'):], flags=re.S)
    assert '.lf-chip' in css and '.lf-panel' in css and '.lf-link' in css
    assert not MOTION.search(css)
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(', css), 'a literal colour: the theme tokens carry dark and light'
    for value in re.findall(r'(?:color|background|border[a-z-]*)\s*:\s*([^;]+);', css):
        assert 'var(--sl-' in value or value.strip() in ('none', 'transparent'), value
    assert 'overflow-wrap: anywhere' in css  # long names and reasons wrap inside a 390 px page


def test_extras_js_starts_the_panel_with_the_run_and_its_section():
    text = (EXTRAS_DIR / 'extras.js').read_text(encoding='utf-8')
    assert text.count("import { startLangfuse } from './langfuse.js';") == 1
    assert text.count('startLangfuse(readApi, runId, section);') == 1


DOM_SCRIPT = """
import fs from 'node:fs';
import { startLangfuse } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const timers = [];
globalThis.setInterval = (fn, ms) => { timers.push({ fn, ms }); return 1; };
function element(tag) {
  return { tag, className: '', dataset: {}, attrs: {}, children: [], textContent: '', href: undefined, target: undefined, rel: undefined,
    setAttribute(name, value) { this.attrs[name] = value; },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; } };
}
const dump = (node) => ({ tag: node.tag, className: node.className, dataset: node.dataset, attrs: node.attrs, text: node.textContent,
  href: node.href, target: node.target, rel: node.rel, children: node.children.map(dump) });
const inserted = [];
const anchor = { after(node) { inserted.push(node); } };
globalThis.document = { createElement: element };
const replies = input.replies.slice();
const paths = [];
const readApi = async (path) => { paths.push(path); const next = replies.shift(); return next === undefined ? null : next; };
startLangfuse(readApi, input.runId, anchor);
const shots = [];
const settle = () => new Promise((resolve) => setImmediate(resolve));
await settle();
shots.push(inserted.length ? dump(inserted[0]) : null);
for (let i = 0; i < input.ticks; i += 1) {
  await timers[0].fn();
  shots.push(inserted.length ? dump(inserted[0]) : null);
}
process.stdout.write(JSON.stringify({ paths, intervals: timers.map((t) => t.ms), inserted: inserted.length, shots }));
"""


def _dom(replies, ticks=0, run_id='run-1'):
    script = DOM_SCRIPT % json.dumps(Path(LANGFUSE_MODULE).as_uri())
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps({'replies': replies, 'ticks': ticks, 'runId': run_id}),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _find(node, tag=None, cls=None):
    found = [node] if (tag is None or node['tag'] == tag) and (cls is None or node['className'] == cls) else []
    for child in node['children']:
        found += _find(child, tag, cls)
    return found


def _texts(node):
    return [node['text']] + [t for child in node['children'] for t in _texts(child)]


OFF_REPLY = {'schema': 'simplicio.dashboard-langfuse/v1', 'chip': {'state': 'off', 'label': 'desligado', 'reason': None}}


def test_off_renders_a_section_holding_only_the_chip():
    junk = dict(OFF_REPLY, queue=9, trace={'url': 'https://langfuse.example.test/trace/x'}, compare={'state': 'DIVERGE', 'gates': [{'name': 'g', 'passed': True, 'langfuse': 'diverge'}]})
    out = _dom([junk])
    section = out['shots'][0]
    assert out['inserted'] == 1 and section['tag'] == 'section' and section['className'] == 'panel lf-panel'
    assert section['attrs'] == {'aria-label': 'Langfuse'}
    assert [(c['tag'], [g['className'] for g in c['children']]) for c in section['children']] == [('p', ['lf-chip'])]
    chip = section['children'][0]['children'][0]
    assert chip['text'] == 'Langfuse: desligado' and chip['dataset'] == {'state': 'off'} and chip['attrs'] == {'role': 'status'}
    assert not _find(section, 'a') and not _find(section, 'ul')


def test_an_active_run_renders_chip_queue_link_gates_tokens_and_cost():
    compare = dict(VALID_REPLY['compare'], cost={'state': 'UNVERIFIED', 'reason': 'o exportador não envia custo'})
    section = _dom([dict(VALID_REPLY, compare=compare)])['shots'][0]
    assert _find(section, 'span', 'lf-chip')[0]['text'] == 'Langfuse: em dia'
    assert _find(section, 'p', 'lf-queue')[0]['text'] == 'Fila em disco: 5'
    link = _find(section, 'a')[0]
    assert (link['href'], link['target'], link['rel'], link['text']) == (VALID_REPLY['trace']['url'], '_blank', 'noopener noreferrer', 'Abrir trace no Langfuse')
    assert [li['text'] for li in _find(section, 'li')] == ['token_count: passou — Langfuse: igual']
    assert _find(section, 'p', 'lf-tokens')[0]['dataset'] == {'state': 'PASS'}
    cost = _find(section, 'p', 'lf-cost')[0]
    assert (cost['text'], cost['dataset']) == ('Custo: o exportador não envia custo', {'state': 'UNVERIFIED'})


def test_an_error_chip_shows_its_reason_and_no_link():
    reply = dict(VALID_REPLY, chip={'state': 'error', 'label': 'erro', 'reason': 'langfuse host must be https'})
    reply['trace'] = dict(VALID_REPLY['trace'], url=None)
    section = _dom([reply])['shots'][0]
    assert _find(section, 'p', 'lf-reason')[0]['text'] == 'langfuse host must be https'
    assert not _find(section, 'a')
    forced = dict(VALID_REPLY, chip={'state': 'error', 'label': 'erro', 'reason': 'x'})  # a url in an error reply is still not linked
    assert not _find(_dom([forced])['shots'][0], 'a')


def test_a_diverged_reply_shows_the_alert():
    compare = dict(VALID_REPLY['compare'], state='DIVERGE', gates=[{'name': 'tests', 'passed': False, 'langfuse': 'diverge'}])
    section = _dom([dict(VALID_REPLY, compare=compare)])['shots'][0]
    warn = _find(section, 'p', 'lf-warn')[0]
    assert warn['attrs'] == {'role': 'alert'} and warn['text'].startswith('Atenção')
    assert _find(section, 'li')[0]['dataset'] == {'state': 'DIVERGE'}


@pytest.mark.parametrize('name', ['<img src=x onerror="window.__xss=1">', '<script>window.__xss=2</script>', '__proto__', '"><svg onload=1>'])
def test_gate_names_and_reasons_are_text_never_markup(name):
    compare = dict(VALID_REPLY['compare'], gates=[{'name': name, 'passed': True, 'langfuse': 'igual'}])
    reply = dict(VALID_REPLY, compare=compare, chip={'state': 'error', 'label': 'erro', 'reason': name})
    section = _dom([reply])['shots'][0]
    item = _find(section, 'li')[0]
    assert item['text'] == name + ': passou — Langfuse: igual' and item['children'] == []
    assert _find(section, 'p', 'lf-reason')[0]['text'] == name
    assert {node['tag'] for node in _find(section)} <= {'section', 'p', 'span', 'ul', 'li', 'a'}


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,x', 'ftp://x.example.test/a', '//x.example.test', 'not a url', None, 5])
def test_only_http_and_https_urls_become_a_link(url):
    reply = dict(VALID_REPLY, trace=dict(VALID_REPLY['trace'], url=url))
    assert not _find(_dom([reply])['shots'][0], 'a')


def test_a_failed_or_foreign_reply_creates_nothing_and_never_erases_what_is_shown():
    out = _dom([None, VALID_REPLY, None, {'schema': 'other/v1'}, 'text', OFF_REPLY], ticks=5)
    assert out['shots'][0] is None  # the first read failed: no section at all
    texts = [_texts(shot)[2] if shot else None for shot in out['shots']]
    assert out['inserted'] == 1  # one section for the whole page life
    assert texts[1] == 'Langfuse: em dia' and texts[2:5] == ['Langfuse: em dia'] * 3
    assert _texts(out['shots'][5])[2] == 'Langfuse: desligado'  # a valid off reply does replace the rows


def test_it_reads_the_encoded_path_once_now_and_every_10_seconds():
    out = _dom([VALID_REPLY, VALID_REPLY], ticks=1, run_id='a b/c')
    assert out['paths'] == ['/api/runs/a%20b%2Fc/langfuse'] * 2
    assert out['intervals'] == [10000]


def test_an_empty_run_id_reads_nothing_and_sets_no_timer():
    out = _dom([VALID_REPLY], run_id='')
    assert out['paths'] == [] and out['intervals'] == [] and out['inserted'] == 0

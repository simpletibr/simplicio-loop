'''View tests for the measured agent map of the Simplicio Live page (issue #1550).

static/extras/agent-map.js turns the "agents" field of GET /api/runs/<id>/extras into rows: a summary, the slots and one row
per instance with its lease and heartbeat. A figure the store did not record is UNVERIFIED with the reason. The pure view and
the renderer run in node; the renderer builds the DOM with textContent and attributes only and sets the slot bar width as a
clamped percent through the CSSOM. The file loads on demand from extras.js, so static/live keeps its gzip budget.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / 'simplicio_loop' / 'dashboard' / 'static'
MODULE = STATIC / 'extras' / 'agent-map.js'
HOSTILE = '<img src=x onerror=alert(1)>'

VIEW_SCRIPT = '''
import fs from 'node:fs';
import { agentMapView } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(input.agents.map((agents) => agentMapView(agents))));
'''

RENDER_SCRIPT = '''
import fs from 'node:fs';
import { renderAgentMap } from %s;
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const byId = {};
function element(tag) {
  const node = { tag, children: [], textContent: '', attrs: {}, props: {}, hidden: false, after(node) { this.sibling = node; },
    style: { setProperty(name, value) { node.props[name] = value; } },
    setAttribute(name, value) { node.attrs[name] = String(value); if (name === 'id') byId[String(value)] = node; },
    append(...items) { this.children.push(...items); },
    replaceChildren(...items) { this.children = items; },
    get firstElementChild() { return this.children[0] || null; } };
  return node;
}
const extras = element('section');
byId['live-extras'] = extras;
globalThis.document = { getElementById: (id) => byId[id] || null, createElement: element };
const plain = (node) => (typeof node === 'string' ? node : { tag: node.tag, attrs: node.attrs, props: node.props, hidden: node.hidden,
  children: node.children.map(plain), text: node.textContent });
const out = [];
for (const agents of input.agents) {
  renderAgentMap(agents);
  out.push(plain(byId['agent-map']));
}
process.stdout.write(JSON.stringify({ renders: out, placed: extras.sibling === byId['agent-map'] }));
'''


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed')


def _run(script, agents):
    proc = subprocess.run([_node(), '--input-type=module', '-e', script % json.dumps(MODULE.as_uri())],
                          input=json.dumps({'agents': agents}), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _beat(age=3, stale=False):
    return {'state': 'MEASURED', 'heartbeat_at': '2026-10-10T00:00:00Z', 'age_s': age, 'stale': stale, 'reason': None}


def _instance(agent_id, status='running', beat=None, **fields):
    row = {'agent_id': agent_id, 'status': status, 'attempt': 1, 'worktree': None, 'lease_id': None,
           'heartbeat': beat or {'state': 'UNVERIFIED', 'heartbeat_at': None, 'age_s': None, 'stale': None, 'reason': 'agente sem lease_id'}}
    row.update(fields)
    return row


def _measured(instances, capacity=4, used=2, **extra):
    return {'state': 'MEASURED', 'reason': None, 'counts': {'pending': 1, 'running': 1},
            'slots': {'state': 'MEASURED', 'capacity': capacity, 'used': used, 'free': capacity - used, 'reason': None},
            'instances': instances, 'instances_total': len(instances), **extra}


def _view(agents):
    [view] = _run(VIEW_SCRIPT, [agents])
    return view


def _rows(view):
    return {row['key']: row for row in view['rows']}


def test_a_reply_without_the_agent_map_is_unverified_with_the_reason_and_unmeasured_slots():
    for agents in (None, {}, 'nope', {'state': 'MEASURED'} and []):
        view = _view(agents)
        assert view['state'] == 'UNVERIFIED' and view['reason'] == 'instâncias não medidas: o run não informou o mapa de agentes'
        assert [row['key'] for row in view['rows']] == ['summary', 'slots']
        assert all(row['state'] == 'UNVERIFIED' for row in view['rows'])
        assert view['slots']['percent'] is None


def test_the_server_reason_of_an_unmeasured_map_is_shown_as_is():
    reason = 'operations.sqlite ausente'
    view = _view({'state': 'UNVERIFIED', 'reason': reason, 'instances': [],
                  'slots': {'state': 'UNVERIFIED', 'reason': reason, 'capacity': None, 'used': None, 'free': None}})
    assert _rows(view)['summary']['detail'] == reason
    assert _rows(view)['slots']['detail'] == 'slots não medidos: ' + reason


def test_measured_slots_read_used_of_capacity_and_the_bar_share_is_a_percent():
    view = _view(_measured([_instance('a')]))
    assert _rows(view)['slots'] == {'key': 'slots', 'label': 'Slots', 'state': 'PASS', 'detail': '2 de 4 slots em uso, 2 livres'}
    assert view['slots']['percent'] == 50
    assert _rows(view)['summary']['detail'] == '1 instância medida no store de operações: 1 aguardando, 1 em execução'


def test_the_slot_share_is_clamped_to_100_and_a_zero_capacity_is_not_a_division():
    assert _view(_measured([_instance('a')], capacity=2, used=5))['slots']['percent'] == 100
    assert _view(_measured([_instance('a')], capacity=0, used=0))['slots']['percent'] == 0


def test_slots_without_a_measured_capacity_say_why_and_draw_no_bar():
    agents = _measured([_instance('a')])
    agents['slots'] = {'state': 'UNVERIFIED', 'capacity': None, 'used': None, 'free': None, 'reason': 'capacidade de slots não registrada'}
    view = _view(agents)
    assert view['state'] == 'MEASURED' and view['slots']['percent'] is None
    assert _rows(view)['slots']['state'] == 'UNVERIFIED'
    assert 'capacidade de slots não registrada' in _rows(view)['slots']['detail']


def test_a_running_instance_with_a_fresh_beat_is_running_and_names_its_lease_and_worktree():
    row = _rows(_view(_measured([_instance('agent-a', beat=_beat(7), lease_id='lease-a', worktree='/w/a', attempt=2)])))['agent:agent-a']
    assert row['label'] == 'agent-a' and row['state'] == 'RUNNING'
    assert row['detail'] == 'em execução · tentativa 2 · worktree /w/a · lease lease-a · último batimento há 7 s'


def test_a_running_instance_with_a_stale_beat_is_stalled_and_says_obsolete():
    row = _rows(_view(_measured([_instance('agent-a', beat=_beat(900, stale=True), lease_id='L')])))['agent:agent-a']
    assert row['state'] == 'STALLED' and row['detail'].endswith('batimento obsoleto, último há 900 s')


def test_a_running_instance_whose_beat_is_not_measured_is_unverified_with_the_reason():
    row = _rows(_view(_measured([_instance('agent-a')])))['agent:agent-a']
    assert row['state'] == 'UNVERIFIED' and row['detail'].endswith('sem lease · batimento não medido: agente sem lease_id')


@pytest.mark.parametrize('status, state, text', [
    ('pending', 'PENDING', 'aguardando'), ('completed', 'PASS', 'concluído'),
    ('shutdown', 'STALLED', 'encerrado'), ('reclaimable', 'STALLED', 'recuperável')])
def test_a_finished_or_waiting_instance_is_not_judged_by_a_lease_nobody_beats(status, state, text):
    row = _rows(_view(_measured([_instance('agent-a', status=status, beat=_beat(900, stale=True), lease_id='L')])))['agent:agent-a']
    assert row['state'] == state and row['detail'].startswith(text)


def test_only_twenty_instances_are_listed_and_the_rest_is_counted():
    agents = _measured([_instance('agent-%02d' % i) for i in range(30)])
    agents['instances_total'] = 75
    view = _view(agents)
    assert len([key for key in _rows(view) if key.startswith('agent:')]) == 20
    assert view['more'] == 55 and _rows(view)['summary']['detail'].startswith('75 instâncias medidas')


def test_a_row_without_an_agent_id_is_skipped_and_a_wrong_total_is_not_trusted():
    agents = _measured([_instance('agent-a'), {'status': 'running'}, 'x', None])
    agents['instances_total'] = 1
    view = _view(agents)
    assert [key for key in _rows(view) if key.startswith('agent:')] == ['agent:agent-a'] and view['more'] == 0


def test_the_renderer_builds_the_section_once_after_the_signals_panel_and_updates_it_in_place():
    out = _run(RENDER_SCRIPT, [_measured([_instance('agent-a', beat=_beat(), lease_id='L')]), None])
    assert out['placed'] is True
    first, second = out['renders']
    assert first['attrs']['id'] == 'agent-map' and first['attrs']['aria-labelledby'] == 'agent-map-title'
    title, note, items, bar = first['children']
    assert title['children'] == ['Instâncias, slots e leases']
    assert [li['children'][0]['attrs']['gate'] for li in items['children']] == ['Instâncias', 'Slots', 'agent-a']
    assert [li['children'][0]['attrs']['state'] for li in items['children']] == ['PASS', 'PASS', 'RUNNING']
    assert bar['hidden'] is False and bar['children'][0]['props'] == {'width': '50%'}
    assert [li['children'][0]['attrs']['state'] for li in second['children'][2]['children']] == ['UNVERIFIED', 'UNVERIFIED']
    assert second['children'][3]['hidden'] is True


def test_hostile_ids_reasons_and_worktrees_reach_the_page_only_as_attribute_values():
    agents = _measured([_instance(HOSTILE, worktree=HOSTILE, lease_id=HOSTILE,
                                  beat={'state': 'UNVERIFIED', 'reason': HOSTILE})])
    [render] = _run(RENDER_SCRIPT, [agents])['renders']
    tags = []

    def walk(node):
        if isinstance(node, str):
            return
        tags.append(node['tag'])
        for child in node['children']:
            walk(child)
    walk(render)
    assert set(tags) <= {'section', 'h2', 'p', 'ul', 'li', 'sl-gate-badge', 'div', 'span'}
    badge = render['children'][2]['children'][2]['children'][0]
    assert badge['attrs']['gate'] == HOSTILE and HOSTILE in badge['attrs']['reason']


def test_the_agent_map_module_writes_no_markup_no_inline_style_and_loads_on_demand():
    text = MODULE.read_text(encoding='utf-8')
    for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'createContextualFragment', 'DOMParser',
                   'setAttribute(\'style\'', 'cssText', 'eval(', 'new Function'):
        assert banned not in text, banned
    assert re.findall(r"style\.setProperty\(('[a-z-]+')", text) == ["'width'"]
    static_import = re.compile(r"^\s*(?:import|export)\b[^;]*\bfrom\s+['\"][^'\"]*agent-map\.js['\"]", re.M)
    for path in sorted(STATIC.rglob('*.js')):
        assert not static_import.search(path.read_text(encoding='utf-8')), '%s imports agent-map.js statically' % path.name
    extras = (STATIC / 'extras' / 'extras.js').read_text(encoding='utf-8')
    assert re.search(r"import\(\s*['\"]\./agent-map\.js['\"]\s*\)", extras)
    live = ''.join(path.read_text(encoding='utf-8') for path in (STATIC / 'live').iterdir() if path.suffix in ('.js', '.html'))
    assert 'agent-map' not in live and 'agentMap' not in live.replace("key: 'agentMap'", '')

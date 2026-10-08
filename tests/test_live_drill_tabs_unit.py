'''Unit tests for the 1405a drill-down tabs of the Simplicio Live page (issue #1405, slice 1405a, TDD red).

Resumo, Logs, Recibos and Comandos share the drawer. The reducer gives the receipt rows and the run commands as pure
data; drill-tabs.js renders them without innerHTML. No receipt is shown as valid: the dashboard has no receipt
validator until slice 1405b, so every receipt says so with a reason. The reducer runs in node through
tests/fixtures/live_pipeline/driver.mjs.
'''
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
LIVE = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live'
TABS = LIVE / 'drill-tabs.js'
RUN_ID = 'run-q1'
NO_VALIDATOR = 'o dashboard ainda não valida recibos (validação de schema: fatia 1405b)'
TAB_IDS = ['summary', 'logs', 'receipts', 'commands', 'contract', 'context']


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _drive(steps, run_id=RUN_ID):
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps, 'runId': run_id}),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _action(payload):
    return {'action': payload, 'now': 0}


def _last(steps, run_id=RUN_ID):
    return _drive(steps, run_id)[-1]


def _read(path):
    return path.read_text(encoding='utf-8')


# Receipts: rows from the run detail, never valid before the validator exists.

def test_receipts_are_empty_before_the_run_detail_arrives():
    assert _last([_action(None)])['receipts'] == []


def test_each_receipt_row_keeps_its_name_and_size_and_is_unverified_with_the_reason():
    view = _last([_action({'type': 'receipts', 'receipts': [{'name': 'completion-receipt.json', 'size': 120}]})])
    assert view['receipts'] == [{'name': 'completion-receipt.json', 'size': 120,
                                 'validation': {'state': 'UNVERIFIED', 'reason': NO_VALIDATOR}}]


def test_no_receipt_row_is_ever_valid_or_pass():
    rows = _last([_action({'type': 'receipts', 'receipts': [{'name': 'a.json', 'size': 1}, {'name': 'b.json', 'size': 2}]})])['receipts']
    assert {row['validation']['state'] for row in rows} == {'UNVERIFIED'}


@pytest.mark.parametrize('bad', ['not-a-list', None, [{'size': 1}], [{'name': '', 'size': 1}], [{'name': 'x.json', 'size': 'big'}]])
def test_malformed_receipt_entries_are_dropped_not_rendered(bad):
    assert _last([_action({'type': 'receipts', 'receipts': bad})])['receipts'] == []


# Commands: exact CLI lines for the run and the repo, quoted for the shell and never executed.

def test_no_commands_without_the_repo_path():
    assert _last([_action(None)])['runCommands'] == []


def test_the_run_commands_name_the_run_and_the_repo_with_the_real_cli_flags():
    view = _last([_action({'type': 'repo', 'repo': '/srv/app'})])
    assert [row['id'] for row in view['runCommands']] == ['progress', 'progress-json']
    assert view['runCommands'][0]['command'] == 'simplicio-loop progress run-q1 --repo /srv/app'
    assert view['runCommands'][1]['command'] == 'simplicio-loop progress run-q1 --repo /srv/app --format json --once'


def test_a_repo_path_with_spaces_and_quotes_is_single_quoted_for_the_shell():
    view = _last([_action({'type': 'repo', 'repo': "/x/it's here"})])
    assert view['runCommands'][0]['command'] == "simplicio-loop progress run-q1 --repo '/x/it'\\''s here'"


def test_a_run_id_outside_the_safe_set_gets_no_commands():
    view = _last([_action({'type': 'repo', 'repo': '/srv/app'})], run_id='run;rm')
    assert view['runCommands'] == []


# Tabs and renderer: the page carries the four tabs with ARIA wiring; drill-tabs.js avoids innerHTML and eval.

def test_the_drawer_tabs_are_wired_to_their_panels():
    html = _read(LIVE / 'index.html')
    assert 'role="tablist"' in html
    for name in TAB_IDS:
        assert 'id="drill-tab-%s"' % name in html, name
        assert 'role="tab"' in html
        assert 'id="drill-panel-%s"' % name in html, name
        assert 'aria-controls="drill-panel-%s"' % name in html, name
        assert 'aria-labelledby="drill-tab-%s"' % name in html, name


def test_the_receipts_and_commands_lists_exist_in_the_drawer():
    html = _read(LIVE / 'index.html')
    assert 'id="drill-receipts"' in html
    assert 'id="drill-commands"' in html
    assert 'id="drill-copy-status"' in html


def test_drill_tabs_module_exists_and_avoids_innerhtml_eval_and_absolute_urls():
    assert TABS.is_file(), TABS
    text = _read(TABS)
    for pattern in (r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, pattern


def test_drill_tabs_move_focus_with_the_arrow_home_and_end_keys():
    text = _read(TABS)
    for key in ('ArrowRight', 'ArrowLeft', 'Home', 'End'):
        assert key in text, key
    assert 'roving' in text.lower() or 'tabindex' in text


def test_copy_handles_a_missing_clipboard_without_throwing():
    text = _read(TABS)
    assert 'navigator.clipboard' in text
    assert 'catch' in text


# Slice 1405b: the Contrato and Contexto tabs show the raw task contract and mapper context, and deep links drive the drawer.

def test_the_contract_and_context_tabs_have_a_json_tree_each():
    html = _read(LIVE / 'index.html')
    for name, tree in (('contract', 'drill-contract'), ('context', 'drill-context')):
        assert 'id="drill-tab-%s"' % name in html, name
        assert 'id="drill-panel-%s"' % name in html, name
        assert 'id="%s"' % tree in html and 'sl-json-tree' in html, tree
        assert 'id="drill-%s-note"' % name in html, name


def test_the_app_reads_the_contract_and_context_artifacts_and_the_deep_link_routes():
    text = _read(LIVE / 'app.js')
    for needle in ("'task-contract.json'", "'mapper-context.json'", 'parseDeepLink', 'deepLinkOf', "'hashchange'", 'replaceState'):
        assert needle in text, needle


def test_the_tab_binder_reports_the_selected_index_to_its_caller():
    assert 'onSelect' in _read(TABS)


def test_the_deep_link_module_passes_the_page_source_guards():
    text = _read(LIVE / 'deeplink.js')
    for pattern in (r'\binnerHTML\b', r'\beval\s*\(', r'https?://'):
        assert re.search(pattern, text) is None, pattern


def test_the_artifact_tabs_ask_only_for_the_files_the_run_lists():
    text = _read(LIVE / 'app.js')
    assert 'drillArtifactNames' in text
    assert 'detail.artifacts' in text
    assert 'Arquivo ainda não gerado neste run.' in text

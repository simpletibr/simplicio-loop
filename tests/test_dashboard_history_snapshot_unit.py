'''Unit tests for the history snapshot page and its CLI flag (#1408).'''
import json
import re

import pytest

from tests.test_dashboard_history_unit import _ev, _run


def _populate(root):
    base = root / '.simplicio-loop' / 'orchestrator'
    base.mkdir(parents=True)
    (base / 'lessons.jsonl').write_text(json.dumps({'schema': 'simplicio.lesson/v1', 'fingerprint': 'f', 'lesson': 'avoid <img src=x>',
                                                    'hit_count': 3, 'last_seen': '2026-10-01T00:00:00Z'}) + '\n', encoding='utf-8')
    _run(root, 'ok-1', outcome='COMPLETE', events=[_ev(1, 'iteration_started', '2026-10-01T10:00:01.000Z', iteration=1)])
    _run(root, 'bad-1', status='blocked', outcome='BLOCKED', started='2026-10-02T09:00:00Z', finished='2026-10-02T09:05:00Z')


def test_history_snapshot_is_offline_escaped_and_complete(tmp_path):
    from simplicio_loop.dashboard import snapshot
    _populate(tmp_path)
    page = snapshot.render_history_snapshot([tmp_path])
    assert '<script' not in page and 'http://' not in page and 'https://' not in page and 'url(' not in page
    assert 'avoid &lt;img src=x&gt;' in page and '<img' not in page
    for text in ('ok-1', 'COMPLETE', 'BLOCKED', 'Tendências', 'Atividade'):
        assert text in page


def test_history_snapshot_with_no_runs_raises(tmp_path):
    from simplicio_loop.dashboard import snapshot
    with pytest.raises(snapshot.SnapshotError):
        snapshot.render_history_snapshot([tmp_path])


def test_cli_snapshot_history_flag_writes_the_page(tmp_path, capsys):
    from simplicio_loop.dashboard import cli
    _populate(tmp_path)
    out = tmp_path / 'out' / 'history.html'
    assert cli.main(['--snapshot', str(out), '--history', '--repo', str(tmp_path)]) == 0
    assert 'ok-1' in out.read_text(encoding='utf-8')
    assert cli.main(['--history']) == 2
    assert 'requires --snapshot' in capsys.readouterr().err

'''Unit tests for simplicio_loop.dashboard.snapshot (issue #1401, slice 3b) - TDD red.

The snapshot module is imported inside each test, never at module top, so this file collects
while simplicio_loop.dashboard.snapshot does not exist yet. Runs are written with the real
dashboard event emitter, under tmp_path only.
'''
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

FORBIDDEN = ['<script', '<link', '<img', '<iframe', 'url(', '@import', 'http://', 'https://']
SECRETS = ['sk-ABCDEFGHIJKLMNOPQRST', 'SUPERSECRETVALUE123']


def _snapshot():
    from simplicio_loop.dashboard import snapshot
    return snapshot


def _make_run(root, run_id, **state):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': 'running', 'phase': 'verify', 'percent': 42,
            'repo': str(root), 'started_at': '2026-10-03T10:00:00Z', 'updated_at': '2026-10-03T10:00:00Z'}
    body.update(state)
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    emitter.emit(run_dir, 'phase_entered', source='runner', phase='intake', strict=True)
    return run_dir


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _make_run(root, 'snap-run-1')
    return root


class _TagCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def test_render_names_the_run_id_phase_and_percent(repo):
    page = _snapshot().render_snapshot([str(repo)], run_id='snap-run-1')
    assert 'snap-run-1' in page
    assert 'verify' in page
    assert '42' in page


def test_injected_script_in_run_state_is_escaped(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _make_run(root, 'xss-run', phase='<script>alert(1)</script>')
    page = _snapshot().render_snapshot([str(root)], run_id='xss-run')
    assert '<script' not in page.lower()
    assert '&lt;script&gt;' in page or 'alert(1)' not in page


def test_clean_snapshot_has_no_external_or_active_content(repo):
    page = _snapshot().render_snapshot([str(repo)], run_id='snap-run-1')
    found = [token for token in FORBIDDEN if token in page.lower()]
    assert found == [], found


def test_snapshot_parses_as_html(repo):
    page = _snapshot().render_snapshot([str(repo)], run_id='snap-run-1')
    collector = _TagCollector()
    collector.feed(page)
    collector.close()
    assert 'html' in collector.tags, collector.tags


def test_secrets_in_run_state_are_masked(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    _make_run(root, 'secret-run', goal='rotate sk-ABCDEFGHIJKLMNOPQRST and api_key=SUPERSECRETVALUE123')
    page = _snapshot().render_snapshot([str(root)], run_id='secret-run')
    assert 'secret-run' in page
    assert 'rotate' in page
    for secret in SECRETS:
        assert secret not in page, secret


def test_write_snapshot_writes_the_file_and_returns_a_path(repo, tmp_path):
    snapshot = _snapshot()
    out = tmp_path / 'snapshot.html'
    result = snapshot.write_snapshot(out, [str(repo)], run_id='snap-run-1')
    assert isinstance(result, Path)
    assert out.is_file()
    assert 'snap-run-1' in out.read_text(encoding='utf-8')


def test_unknown_run_id_raises_snapshot_error(repo):
    snapshot = _snapshot()
    with pytest.raises(snapshot.SnapshotError):
        snapshot.render_snapshot([str(repo)], run_id='no-such-run')


def test_zero_runs_raises_snapshot_error(tmp_path):
    snapshot = _snapshot()
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(snapshot.SnapshotError):
        snapshot.render_snapshot([str(empty)])

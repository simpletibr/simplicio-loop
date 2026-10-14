'''Unit tests for the opt-in dashboard.toml of the Simplicio Live dashboard (issue #1406).

The file is optional. Without it every default holds. A bad file or a bad value never stops the server: the default
stays and the problem is listed in `problems`. The webhook is on only when the file sets an http(s) URL.
'''
from simplicio_loop.dashboard import alerts, config


def _write(root, text):
    path = root / '.simplicio-loop' / 'dashboard.toml'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_absent_file_keeps_every_default(tmp_path):
    cfg = config.load(tmp_path)
    assert cfg.silence_ms == alerts.SILENCE_MS
    assert cfg.browser_notifications is False
    assert cfg.webhook_url is None
    assert cfg.problems == []


def test_file_sets_thresholds_notifications_and_webhook(tmp_path):
    _write(tmp_path, '[alerts]\nphase_silence_minutes = 2\n\n[notifications]\nbrowser = true\n\n'
                     '[webhook]\nurl = "https://hooks.example.test/x"\n')
    cfg = config.load(tmp_path)
    assert cfg.silence_ms == 2 * 60 * 1000
    assert cfg.browser_notifications is True
    assert cfg.webhook_url == 'https://hooks.example.test/x'


def test_bad_values_fall_back_and_are_reported(tmp_path):
    _write(tmp_path, '[alerts]\nphase_silence_minutes = -3\n\n[notifications]\nbrowser = "yes"\n\n'
                     '[webhook]\nurl = "file:///etc/passwd"\n')
    cfg = config.load(tmp_path)
    assert cfg.silence_ms == alerts.SILENCE_MS
    assert cfg.browser_notifications is False
    assert cfg.webhook_url is None
    assert len(cfg.problems) == 3


def test_invalid_toml_keeps_defaults(tmp_path):
    _write(tmp_path, 'this is [not toml')
    cfg = config.load(tmp_path)
    assert cfg.silence_ms == alerts.SILENCE_MS
    assert len(cfg.problems) == 1


def test_public_view_never_exposes_the_webhook_url(tmp_path):
    _write(tmp_path, '[webhook]\nurl = "https://hooks.example.test/secret"\n')
    view = config.load(tmp_path).public()
    assert view == {'browser_notifications': False, 'webhook': True}
    assert 'secret' not in repr(view)


def test_watch_uses_the_configured_silence():
    watch = alerts.AlertWatch(silence_ms=60 * 1000)
    event = {'schema': alerts.SCHEMA, 'seq': 1, 'ts': '2026-10-08T10:00:00.000Z', 'kind': 'phase_entered',
             'phase': 'executing', 'payload': {}}
    start = alerts._to_ms(event['ts'])
    watch.update([event], start)
    raised, _ = watch.update([], start + 90 * 1000)
    assert [a['rule'] for a in raised] == ['phase-silent']
    default = alerts.AlertWatch()
    default.update([event], start)
    assert default.update([], start + 90 * 1000)[0] == []

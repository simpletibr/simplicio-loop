'''Offline HTML snapshot with the Langfuse chip (issue #1610).

The snapshot is a file people share: it carries the chip, the queue size, the trace id and the score comparison, never a
link, a host, a key or any script. Off (the default) it adds the chip and nothing else.
'''
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.test_dashboard_langfuse_view_unit import (HOST, PUBLIC, RUN_ID, SECRET, TRACE_ID, _report, _write_events, export, lf_dir,
                                                     make_repo, on, outbox)

FORBIDDEN = ['<script', '<link', '<img', '<iframe', 'url(', '@import', 'http://', 'https://', 'href=', 'src=']


def _page(ref):
    from simplicio_loop.dashboard import snapshot
    return snapshot.render_snapshot([ref['repo']], run_id=RUN_ID)


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def test_off_adds_only_the_chip(tmp_path):
    ref = make_repo(tmp_path, None, report=_report(), gates={'tests': True})
    page = _page(ref)
    assert 'Langfuse: desligado' in page
    for absent in ('Fila em disco', TRACE_ID, 'em dia', 'Scores'):
        assert absent not in page
    off = page.count('Langfuse')
    assert off == 2  # the heading and the chip, nothing else


def test_on_shows_chip_queue_trace_id_and_the_comparison(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True, 'lint': False})
    export(ref)
    outbox(ref).enqueue('traces', {'x': 1})
    page = _page(ref)
    assert 'Fila em disco' in page and TRACE_ID in page
    assert 'Langfuse: enviando' in page or 'Langfuse: atrasado' in page
    assert 'tests' in page and 'lint' in page and 'igual' in page


def test_the_snapshot_holds_no_key_no_host_no_link_and_no_active_content(tmp_path, monkeypatch):
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', SECRET)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', PUBLIC)
    ref = make_repo(tmp_path, on('http://localhost:3000'), report=_report(), gates={'tests': True})
    lf_dir(ref).mkdir(parents=True, exist_ok=True)
    (lf_dir(ref) / 'credentials.json').write_text(json.dumps({'public_key': PUBLIC, 'secret_key': SECRET}), encoding='utf-8')
    export(ref)
    page = _page(ref)
    assert TRACE_ID in page
    for banned in FORBIDDEN + [SECRET, PUBLIC, 'sk-lf-', 'pk-lf-', 'localhost', HOST.split('//')[1]]:
        assert banned not in page, banned
    tags = _Tags()
    tags.feed(page)
    assert not {'script', 'link', 'img', 'iframe', 'a', 'form'} & set(tags.tags)


def test_a_gate_name_with_markup_is_escaped(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'<script>alert(1)</script>': True})
    export(ref)
    page = _page(ref)
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page


def test_a_diverged_gate_is_warned_in_the_snapshot(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    export(ref)
    _write_events(Path(ref['run_dir']), {'tests': False})
    page = _page(ref)
    assert 'diverge' in page and 'Atenção' in page


def test_an_error_chip_names_the_reason_without_the_host(tmp_path):
    ref = make_repo(tmp_path, on('http://langfuse.example.test'), report=_report(), gates={'tests': True})
    page = _page(ref)
    assert 'Langfuse: erro' in page and 'https' in page
    assert 'langfuse.example.test' not in page


def test_the_chip_follows_the_color_scheme_and_fits_a_phone(tmp_path):
    page = _page(make_repo(tmp_path, on(), report=_report(), gates={'tests': True}))
    css = re.search(r'<style>(.*?)</style>', page, re.S).group(1)
    assert 'prefers-color-scheme: dark' in css and 'name="viewport"' in page
    chip_rules = [rule for rule in css.split('}') if '.chip' in rule]
    assert chip_rules and all('#' not in rule.split('{')[1] or 'var(' in rule for rule in chip_rules)
    assert 'overflow-wrap' in css

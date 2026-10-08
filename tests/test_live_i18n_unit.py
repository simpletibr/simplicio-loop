'''The EN dictionary of the Live page: pt-BR stays the default, EN is opt-in with ``?lang=en``.'''
from __future__ import annotations

import json
import re
import subprocess
import shutil
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'simplicio_loop' / 'dashboard' / 'static'
INDEX = (STATIC / 'live' / 'index.html').read_text(encoding='utf-8')
I18N = STATIC / 'i18n' / 'i18n.js'


def _dictionary() -> dict:
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not available')
    code = ("import('%s').then(m => console.log(JSON.stringify(m.EN)))" % I18N.as_uri())
    out = subprocess.run([node, '-e', code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_index_loads_the_i18n_module_and_keeps_pt_br_default():
    assert '<html lang="pt-BR">' in INDEX
    assert '/static/i18n/i18n.js' in INDEX


def test_every_static_label_has_an_english_entry():
    en = _dictionary()
    text = set(re.findall(r'>([^<>]{2,})<', INDEX)) | set(re.findall(r'(?:aria-label|label|placeholder)="([^"]+)"', INDEX))
    labels = {t.strip() for t in text if re.search(r'[A-Za-zÀ-ú]{3}', t) and not t.strip().startswith(('http', '/'))}
    labels -= {'Simplicio Live · Pipeline vivo', 'Stall', 'Gates', 'Logs', 'Lanes', 'Atual'}  # same word in both, or title
    missing = sorted(l for l in labels if l not in en and not re.fullmatch(r'[\d:() ]+', l) and not l.startswith('Alertas ('))
    assert missing == []
    assert all(k != v for k, v in en.items())

import asyncio
import json
import os
import tempfile
from pathlib import Path
import pytest

from simplicio_loop.watcher247 import state


def test_state_key_of():
    key = state.key_of('repo', 123)
    assert key == 'repo#123'


def test_state_due_new():
    claims = {}
    assert state.due('repo#1', claims) is True


def test_state_due_done():
    claims = {'repo#1': {'status': 'done'}}
    assert state.due('repo#1', claims) is False


def test_state_due_dead():
    claims = {'repo#1': {'status': 'dead'}}
    assert state.due('repo#1', claims) is False


def test_state_due_retry():
    now_str = state.iso(state.now())
    claims = {'repo#1': {'status': 'retry', 'next_try_at': now_str}}
    assert state.due('repo#1', claims) is True


def test_state_save_load():
    async def _test():
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'test.json'
            data = {'test': True, 'num': 42}
            await state.save(path, data)
            loaded = await state.load(path, None)
            assert loaded == data
    asyncio.run(_test())


def test_state_load_default():
    async def _test():
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'missing.json'
            default = {'default': True}
            loaded = await state.load(path, default)
            assert loaded == default
    asyncio.run(_test())

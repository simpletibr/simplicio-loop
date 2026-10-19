"""The marker block in an entry file (AGENTS.md and friends): merged in, refreshed in place, removed exactly."""
from __future__ import annotations

from simplicio_loop.install import entry


def test_merging_into_an_empty_file_is_just_the_block():
    assert entry.merge("") == entry.block() + "\n"


def test_merging_appends_below_the_users_text_and_is_stable():
    once = entry.merge("# mine\n")
    assert once.startswith("# mine\n\n" + entry.BEGIN)
    assert entry.merge(once) == once


def test_removing_the_block_restores_the_users_text_byte_for_byte():
    assert entry.remove(entry.merge("# mine\n")) == "# mine\n"


def test_removing_a_block_only_file_leaves_nothing():
    assert entry.remove(entry.merge("")) == ""


def test_text_written_after_the_block_survives_its_removal():
    text = entry.merge("# mine\n") + "more\n"
    assert entry.remove(text) == "# mine\nmore\n"


def test_a_file_without_the_block_has_nothing_to_remove():
    assert entry.remove("# mine\n") is None


def test_a_legacy_simplicio_tasks_block_is_replaced_by_the_current_one():
    legacy = "<!-- simplicio-tasks:begin -->\nold\n<!-- simplicio-tasks:end -->\n"
    assert entry.merge(legacy) == entry.block() + "\n"

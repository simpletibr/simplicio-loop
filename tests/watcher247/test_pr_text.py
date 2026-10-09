"""The PR title (#1644): `loop: #N text`, whole number first, cut on a word with the ellipsis inside 70 characters."""
import random

import pytest

from simplicio_loop.watcher247.pr_text import LIMIT, fit, pr_title

LONG = "Ajustar o calculo de tarifa quando o cliente muda de plano durante o ciclo de cobranca mensal"


def test_short_title_is_unchanged_and_carries_the_number():
    assert pr_title(7, "Add x") == "loop: #7 Add x"
    assert pr_title(7, "") == "loop: #7"


def test_long_title_ends_on_a_whole_word_with_the_ellipsis_counted():
    out = pr_title(1644, LONG)
    assert out == "loop: #1644 Ajustar o calculo de tarifa quando o cliente muda de…"
    assert len(out) <= LIMIT and out.endswith("…") and not out.endswith(" …")
    assert out[:-1] in f"loop: #1644 {LONG}" and f"loop: #1644 {LONG}"[len(out) - 1] == " "


def test_exactly_at_the_limit_is_not_cut():
    text = "a" * (LIMIT - len("loop: #5 "))
    assert pr_title(5, text) == "loop: #5 " + text and len(pr_title(5, text)) == LIMIT
    assert pr_title(5, text + "b").endswith("…") and len(pr_title(5, text + "b")) == LIMIT


def test_a_single_word_longer_than_the_room_is_cut_hard():
    out = pr_title(12, "x" * 200)
    assert out == "loop: #12 " + "x" * (LIMIT - len("loop: #12 ") - 1) + "…" and len(out) == LIMIT


def test_accents_and_emoji_are_never_cut_by_bytes():
    out = pr_title(3, "ação média ñandú " * 10 + "😀" * 40)
    assert len(out) <= LIMIT and out.startswith("loop: #3 ação média ñandú") and out.endswith("…")
    out.encode("utf-8")
    assert pr_title(3, "😀" * 200).endswith("😀…")


def test_whitespace_is_collapsed_so_the_commit_subject_is_one_clean_line():
    out = pr_title(8, "  two\nlines\t and   gaps  ")
    assert out == "loop: #8 two lines and gaps" and "\n" not in out


def test_closing_words_in_the_issue_title_are_rewritten_before_the_cut():
    out = pr_title(9, "Fixes #99 " + LONG)
    assert out.startswith("loop: #9 Parte de #99 Ajustar") and len(out) <= LIMIT


def test_property_number_whole_limit_word_boundary_and_idempotent():
    rng = random.Random(70)
    words = ["a", "bb", "açúcar", "x" * 30, "pipeline", "tarifa", "😀", "#12", "o", "migração", "y" * 75]
    for _ in range(400):
        number = rng.choice([1, 7, 42, 1644, 123456])
        text = " ".join(rng.choice(words) for _ in range(rng.randint(0, 25)))
        head = f"loop: #{number}"
        out = fit(head, text)
        assert out.startswith(head) and len(out) <= LIMIT
        assert fit(head, out[len(head):]) == out  # idempotent
        full = f"{head} {' '.join(text.split())}".rstrip()
        if out != full:
            assert out.endswith("…") and not out.endswith(" …")
            body = out[:-1]
            assert full.startswith(body)
            word_cut = full[len(body)] == " "
            hard_cut = len(out) == LIMIT
            assert word_cut or hard_cut, (full, out)

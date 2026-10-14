"""Closing words never leave the watcher (#1644): rewrite, detection, the sanitize door and a seeded property test."""
import random
import time

import pytest

from simplicio_loop.watcher247 import closing_words
from simplicio_loop.watcher247.closing_words import has_closing, rewrite, sanitize

# the nine words GitHub documents, written out here on purpose: a word dropped from the module must fail a test
GITHUB_WORDS = ("close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved")

URL = "https://github.com/o/r/issues/1"


@pytest.mark.parametrize("text, expected", [
    ("Closes #1", "Parte de #1"),
    ("closes: #1", "Parte de #1"),
    ("FIXED   #1", "Parte de #1"),
    ("Resolves owner/repo#1", "Parte de owner/repo#1"),
    ('"Closes #1"', '"Parte de #1"'),
    ("(fixes #1)", "(Parte de #1)"),
    ("Fix\n#1", "Parte de #1"),
    (f"Resolved {URL}", f"Parte de {URL}"),
    ("fixes\t:\t#12, closes #13", "Parte de #12, Parte de #13"),
    ("title Resolved: o/r#5 tail", "title Parte de o/r#5 tail"),
    ("see CLOSE GH-7", "see Parte de GH-7"),
])
def test_rewrites_every_closing_shape(text, expected):
    assert has_closing(text)
    assert rewrite(text) == expected


@pytest.mark.parametrize("text", [
    "prefixes #3", "closest #3", "fixture #3", "close the door #3", "Closes", "Fixes the bug", "Parte de #1",
    "refs #1", "resolution #2", "unfixed #4", "Closes #", "Fixes #abc", "fixtures/x#3", "closest o/r#3", "prefixes o/r#3",
])
def test_leaves_alone_what_github_does_not_treat_as_closing(text):
    assert not has_closing(text)
    assert rewrite(text) == text


@pytest.mark.parametrize("word", GITHUB_WORDS)
def test_every_keyword_in_every_case(word):
    for variant in (word, word.upper(), word.title(), word.swapcase()):
        assert rewrite(f"{variant} #9") == "Parte de #9"


@pytest.mark.parametrize("text, expected", [
    ("Fixes https://github.com/owner/repo/issues/12", "Parte de https://github.com/owner/repo/issues/12"),
    ("Fixes https://github.com/owner/repo/pull/12", "Parte de https://github.com/owner/repo/pull/12"),
    ("Closes GH-12", "Parte de GH-12"),
    ("closes: GH-12.", "Parte de GH-12."),
])
def test_github_url_and_gh_number_forms_are_closing_and_rewritten(text, expected):
    assert has_closing(text)
    assert rewrite(text) == expected
    assert not has_closing(expected)
    assert sanitize(text, "PR body") == expected


def test_sanitize_returns_the_rewrite_and_names_what_it_refuses(monkeypatch):
    assert sanitize("x Fixes #2 y", "PR body") == "x Parte de #2 y"
    monkeypatch.setattr(closing_words, "rewrite", lambda text: text)  # a rewrite that missed it: the guard still refuses
    with pytest.raises(RuntimeError, match="PR body still has a GitHub closing word"):
        sanitize("x Fixes #2 y", "PR body")


@pytest.mark.parametrize("gap", [" ", "\n", "\t", " \n"])
def test_a_keyword_followed_by_thousands_of_whitespace_is_linear_not_quadratic(gap):
    """The old `\\s*[:=]?\\s*` took 10 s at 8000 spaces: sanitize is on the delivery path, a model body must not freeze it."""
    for text in ("close" + gap * 8000 + "x", "fixes" + gap * 8000 + "#1", "ok close" + gap * 8000):
        started = time.perf_counter()
        out = sanitize(text, "PR body")
        assert time.perf_counter() - started < 0.5
        assert has_closing(text) == (text.endswith("#1"))
        assert out == (("Parte de #1") if text.endswith("#1") else text)


@pytest.mark.parametrize("bad", [None, b"Closes #1", 5, ["Closes #1"]])
def test_non_str_input_is_a_clear_type_error(bad):
    with pytest.raises(TypeError, match="str"):
        has_closing(bad)
    with pytest.raises(TypeError, match="str"):
        sanitize(bad, "PR body")
    with pytest.raises(TypeError, match="str"):
        rewrite(bad)


def _closing(rng: random.Random) -> tuple[str, str]:
    word = rng.choice(GITHUB_WORDS)
    word = "".join(c.upper() if rng.random() < 0.5 else c.lower() for c in word)
    sep = rng.choice(["", ":", "=", ":", "="]) if rng.random() < 0.4 else ""
    gap = rng.choice([" ", "  ", "\t", "\n", "   "])
    ref = rng.choice([f"#{rng.randint(1, 99999)}", f"own{rng.randint(1, 9)}/rep-o.x#{rng.randint(1, 999)}",
                      f"https://github.com/o/r/issues/{rng.randint(1, 999)}", f"GH-{rng.randint(1, 999)}"])
    return word + (gap if not sep else rng.choice(["", " "]) + sep + gap) + ref, ref


AROUND = ["", "text ", "- ", '"', "(", "* ", "intro line\n\n", "ver ", "Closes the loop. ", "prefixes 3 "]
AFTER = ["", " tail", ".", ")", '"', "\n- next", ", more", " fixture #3", " closest #4"]


def test_property_rewrite_clears_every_closing_word_keeps_the_rest_and_is_idempotent():
    rng = random.Random(1644)
    for _ in range(400):
        before, after = rng.choice(AROUND), rng.choice(AFTER)
        phrase, ref = _closing(rng)
        text = before + phrase + after
        out = rewrite(text)
        assert has_closing(text)
        assert not has_closing(out), text
        assert out == before + "Parte de " + ref + after, text  # only the closing phrase changed
        assert rewrite(out) == out
        assert sanitize(text, "x") == out


def test_property_many_phrases_in_one_text_and_innocent_text_untouched():
    rng = random.Random(2026)
    for _ in range(100):
        pieces = [_closing(rng)[0] if rng.random() < 0.6 else rng.choice(AROUND + AFTER) for _ in range(rng.randint(2, 6))]
        text = " | ".join(pieces)
        out = rewrite(text)
        assert not has_closing(out), text
        assert rewrite(out) == out
    innocent = ["prefixes #3", "closest #3", "fixture #3", "close the door #3", "refix"]
    for _ in range(100):
        text = " ".join(rng.choice(innocent) for _ in range(4))
        assert rewrite(text) == text and not has_closing(text)

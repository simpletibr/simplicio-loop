"""
exec_cases.py — self-contained, executable benchmark tasks.

Unlike the regex harness (run_offline.py), these are scored by RUNNING the
model's code against a hidden pytest suite: pass == the generated module
actually imports and all assertions (true AND false states) hold. The test
code is NOT shown to the model — only the natural-language goal/criteria are.

Each case asks the model to emit the COMPLETE contents of `solution.py`. That
output shape is held constant across both sides of the benchmark; the only
variable is whether the task is wrapped in the simplicio contract.
"""
from __future__ import annotations

CASES = [
    {
        "id": "can_delete",
        "stack": "python",
        "goal": "Implement `can_delete(user)` in solution.py. It returns True only "
                "when the user is an admin, i.e. user is a dict and user.get('role') "
                "== 'admin'. For any other role, a missing role, or a non-dict input "
                "it returns False.",
        "criteria": "- admin user -> True\n- non-admin role -> False\n"
                    "- missing 'role' key -> False\n- non-dict input -> False",
        "constraints": "- pure function, no I/O\n- never raise on bad input",
        "test": (
            "from solution import can_delete\n"
            "def test_admin_true():\n"
            "    assert can_delete({'role': 'admin'}) is True\n"
            "def test_non_admin_false():\n"
            "    assert can_delete({'role': 'editor'}) is False\n"
            "def test_missing_role_false():\n"
            "    assert can_delete({}) is False\n"
            "def test_bad_input_false():\n"
            "    assert can_delete(None) is False\n"
            "    assert can_delete('admin') is False\n"
        ),
    },
    {
        "id": "email_editable",
        "stack": "python",
        "goal": "Implement `email_editable(profile)` in solution.py. The email field "
                "is editable only for the 'editor' profile. Return True when profile "
                "== 'editor', otherwise False. Comparison is case-sensitive.",
        "criteria": "- 'editor' -> True\n- 'admin' / 'viewer' / '' -> False\n"
                    "- 'Editor' (wrong case) -> False",
        "constraints": "- pure function, no I/O",
        "test": (
            "from solution import email_editable\n"
            "def test_editor_true():\n"
            "    assert email_editable('editor') is True\n"
            "def test_others_false():\n"
            "    for p in ('admin', 'viewer', ''):\n"
            "        assert email_editable(p) is False\n"
            "def test_case_sensitive():\n"
            "    assert email_editable('Editor') is False\n"
        ),
    },
    {
        "id": "slugify",
        "stack": "python",
        "goal": "Implement `slugify(title)` in solution.py. Lowercase the title, "
                "replace runs of whitespace with a single hyphen, drop every "
                "character that is not a-z, 0-9 or hyphen, and collapse repeated "
                "hyphens into one. Strip leading/trailing hyphens. Empty or "
                "whitespace-only input returns ''.",
        "criteria": "- 'Hello World' -> 'hello-world'\n"
                    "- '  Multiple   Spaces! ' -> 'multiple-spaces'\n"
                    "- 'a@@@b' -> 'ab'\n- '' -> ''",
        "constraints": "- pure function, no I/O\n- no leading/trailing hyphens",
        "test": (
            "from solution import slugify\n"
            "def test_basic():\n"
            "    assert slugify('Hello World') == 'hello-world'\n"
            "def test_spaces_and_punct():\n"
            "    assert slugify('  Multiple   Spaces! ') == 'multiple-spaces'\n"
            "def test_strip_symbols():\n"
            "    assert slugify('a@@@b') == 'ab'\n"
            "def test_empty():\n"
            "    assert slugify('   ') == ''\n"
        ),
    },
    {
        "id": "apply_discount",
        "stack": "python",
        "goal": "Implement `apply_discount(price, code)` in solution.py. 'SAVE10' "
                "gives 10% off, 'HALF' gives 50% off, any other or empty code gives "
                "no discount. Return the final price as a float, rounded to 2 "
                "decimals, never below 0.",
        "criteria": "- (100, 'SAVE10') -> 90.0\n- (100, 'HALF') -> 50.0\n"
                    "- (100, 'NOPE') -> 100.0\n- (100, '') -> 100.0\n"
                    "- result never negative",
        "constraints": "- pure function, no I/O\n- round to 2 decimals",
        "test": (
            "from solution import apply_discount\n"
            "def test_save10():\n"
            "    assert apply_discount(100, 'SAVE10') == 90.0\n"
            "def test_half():\n"
            "    assert apply_discount(100, 'HALF') == 50.0\n"
            "def test_invalid_code():\n"
            "    assert apply_discount(100, 'NOPE') == 100.0\n"
            "    assert apply_discount(100, '') == 100.0\n"
            "def test_non_negative():\n"
            "    assert apply_discount(0, 'HALF') == 0.0\n"
        ),
    },
    {
        "id": "merge_intervals",
        "stack": "python",
        "goal": "Implement `merge_intervals(intervals)` in solution.py. Given a list "
                "of [start, end] pairs, merge all overlapping or touching intervals "
                "and return them sorted by start. Touching means end == next start.",
        "criteria": "- [[1,3],[2,6],[8,10]] -> [[1,6],[8,10]]\n"
                    "- [[1,4],[4,5]] -> [[1,5]] (touching merges)\n"
                    "- [] -> []\n- input order should not matter",
        "constraints": "- pure function, no I/O\n- output sorted by start",
        "test": (
            "from solution import merge_intervals\n"
            "def test_overlap():\n"
            "    assert merge_intervals([[1,3],[2,6],[8,10]]) == [[1,6],[8,10]]\n"
            "def test_touching():\n"
            "    assert merge_intervals([[1,4],[4,5]]) == [[1,5]]\n"
            "def test_empty():\n"
            "    assert merge_intervals([]) == []\n"
            "def test_unsorted_input():\n"
            "    assert merge_intervals([[8,10],[1,3],[2,6]]) == [[1,6],[8,10]]\n"
        ),
    },
    {
        "id": "validate_password",
        "stack": "python",
        "goal": "Implement `validate_password(pw)` in solution.py. Return True only "
                "when pw is a string of length >= 8 that contains at least one digit, "
                "one uppercase letter and one lowercase letter. Otherwise False.",
        "criteria": "- 'Abcd1234' -> True\n- 'short1A' (len 7) -> False\n"
                    "- 'alllower1' (no upper) -> False\n- 'ALLUPPER1' (no lower) -> False\n"
                    "- 'NoDigitsHere' -> False\n- non-string -> False",
        "constraints": "- pure function, no I/O\n- never raise on bad input",
        "test": (
            "from solution import validate_password\n"
            "def test_valid():\n"
            "    assert validate_password('Abcd1234') is True\n"
            "def test_too_short():\n"
            "    assert validate_password('short1A') is False\n"
            "def test_missing_class():\n"
            "    assert validate_password('alllower1') is False\n"
            "    assert validate_password('ALLUPPER1') is False\n"
            "    assert validate_password('NoDigitsHere') is False\n"
            "def test_bad_input():\n"
            "    assert validate_password(12345678) is False\n"
        ),
    },
]

"""Tests for simplicio.detect — heuristic classifier."""
from simplicio import cli
from simplicio.detect import detect


def test_code_task_with_file_and_verb():
    r = detect("esconda o botão admin no Header.tsx para não-admins")
    assert r.is_code_task is True
    assert r.score >= 3
    assert any(s.startswith("verb:") for s in r.signals)
    assert any(s.startswith("file:") for s in r.signals)
    assert "Header.tsx" in r.hint


def test_code_task_english():
    r = detect("add email validation to UserForm.tsx")
    assert r.is_code_task is True
    assert r.score >= 3
    assert "UserForm.tsx" in r.hint


def test_explicit_invocation_alone_wins():
    r = detect("use simplicio for this")
    assert r.is_code_task is True
    assert "explicit_invocation" in r.signals


def test_read_only_question_is_not_code_task():
    r = detect("o que faz a função generate em providers.py?")
    assert r.is_code_task is False
    assert r.hint == ""


def test_explain_english_is_not_code_task():
    r = detect("explain how the verify loop works")
    assert r.is_code_task is False


def test_empty_prompt():
    r = detect("")
    assert r.is_code_task is False
    assert r.score == 0


def test_low_signal_prompt_below_threshold():
    r = detect("the button component")
    assert r.is_code_task is False


def test_hint_includes_target_file_when_present():
    r = detect("rename the prop in src/components/Modal.tsx")
    assert r.is_code_task is True
    assert "target = src/components/Modal.tsx" in r.hint


def test_portuguese_endpoint_alignment_is_code_task():
    r = detect("veja todas as telas e alinhe todos os endpoints com a API")
    assert r.is_code_task is True
    assert r.scope == "sprint"
    assert "sprint-scale code work" in r.hint
    assert any(signal.startswith("verb:") for signal in r.signals)
    assert any(signal.startswith("noun:") for signal in r.signals)
    assert "sprint:full_inventory" in r.signals


def test_portuguese_playwright_local_api_evidence_is_code_task():
    r = detect("vamos usar playwright para evidenciar as telas web conectando ao api com banco postgresql local")
    assert r.is_code_task is True
    assert r.scope == "feature"
    assert "feature-scale code work" in r.hint
    assert any(signal.startswith("verb:") for signal in r.signals)
    assert any(signal.startswith("noun:") for signal in r.signals)
    assert "feature:real_stack_evidence" in r.signals


def test_cli_detect_accepts_positional_prompt(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main([
        "detect",
        "ajuste",
        "o",
        "endpoint",
        "em",
        "Header.tsx",
        "--json",
        "--quiet",
    ])

    assert code == 0
    assert '"is_code_task": true' in capsys.readouterr().out


def test_cli_detect_reports_sprint_scope_for_full_inventory(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main([
        "detect",
        "veja",
        "todas",
        "as",
        "telas",
        "e",
        "todos",
        "os",
        "endpoints",
        "--json",
        "--quiet",
    ])

    assert code == 0
    assert '"scope": "sprint"' in capsys.readouterr().out


def test_detect_reports_sprint_scope_for_remaining_endpoint_backlog():
    r = detect("alinhar as 32 rotas restantes do ai-agents contra api .NET com fontes do mapper")

    assert r.is_code_task is True
    assert r.scope == "sprint"
    assert "sprint:remaining_endpoint_inventory" in r.signals
    assert "sprint-scale code work" in r.hint

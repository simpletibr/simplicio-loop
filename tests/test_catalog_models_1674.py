"""Issue 1674: the codex and grok execution models map back to the execution role."""

from simplicio_loop import model_roles


def test_codex_execution_can_be_resolved_to_role():
    result = model_roles.role_of('gpt-5.6-luna')
    assert result is not None
    assert result['role'] == 'execution'


def test_grok_execution_can_be_resolved_to_role():
    result = model_roles.role_of('grok-4.7')
    assert result is not None
    assert result['role'] in ('planning', 'coordination', 'execution')

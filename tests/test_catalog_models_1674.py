"""Issue 1674: the codex and grok models resolve to exactly the roles the catalog gives them."""

import json

from simplicio_loop import model_roles


def test_codex_execution_can_be_resolved_to_role():
    result = model_roles.role_of('gpt-5.6-luna')
    assert result is not None
    assert result['role'] == 'execution'


def test_codex_roles_are_the_catalog_models():
    models = [model_roles.resolve('codex', role)['model'] for role in model_roles.ROLES]
    assert models == ['gpt-5.6-terra', 'gpt-5.5', 'gpt-5.6-luna']


def test_grok_47_is_listed_for_exactly_the_three_grok_roles():
    families = json.loads(model_roles.CATALOG.read_text(encoding='utf-8'))['families']
    listed = [(family, role) for family in families for role in model_roles.ROLES
              if model_roles.resolve(family, role)['model'] == 'grok-4.7']
    assert listed == [('grok', 'planning'), ('grok', 'coordination'), ('grok', 'execution')]
    assert [model_roles.resolve('grok', role)['effort'] for role in model_roles.ROLES] == ['xhigh', 'high', 'high']

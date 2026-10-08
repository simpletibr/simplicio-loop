'''Unit tests for the default model per role (TDD red).

simplicio_loop/_catalog/model_roles.json is the single source. Each runtime family has three roles: planning
(hard decisions), coordination (coordination, review, tracking) and execution (execution, tests, merges, workers).
resolve() returns the model and effort for a family and a role, and refuses anything outside the table.
'''
import json
from pathlib import Path

import pytest

from simplicio_loop import model_roles

ROLES = ('planning', 'coordination', 'execution')
FAMILIES = ('claude', 'codex', 'grok', 'gemini')
EXPECTED = {
    ('claude', 'planning'): ('claude-opus-5-5', 'high'),
    ('claude', 'coordination'): ('claude-sonnet-5-5', 'high'),
    ('claude', 'execution'): ('claude-haiku-5-5', 'high'),
    ('codex', 'planning'): ('gpt-6-astra', 'high'),
    ('codex', 'coordination'): ('gpt-6.1-sol', 'high'),
    ('codex', 'execution'): ('gpt-6-luna', 'high'),
    ('grok', 'planning'): ('grok-4.7', 'xhigh'),
    ('grok', 'coordination'): ('grok-4.6', 'high'),
    ('grok', 'execution'): ('grok-4.5', 'high'),
    ('gemini', 'planning'): ('gemini-3.8-flash', 'high'),
    ('gemini', 'coordination'): ('gemini-3.7-flash', 'high'),
    ('gemini', 'execution'): ('gemini-3.6-flash', 'high'),
}
CATALOG = Path(model_roles.__file__).with_name('_catalog') / 'model_roles.json'


def test_the_catalog_names_its_schema_date_and_sources():
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    assert data['schema'] == 'simplicio.model-roles/v1'
    assert data['as_of'] == '2026-10-08'
    assert data['sources'] and all(url.startswith('https://') for url in data['sources'])


def test_every_family_has_every_role_with_a_model_and_an_effort():
    data = json.loads(CATALOG.read_text(encoding='utf-8'))
    assert sorted(data['families']) == sorted(FAMILIES)
    for family in FAMILIES:
        assert sorted(data['families'][family]) == sorted(ROLES), family
        for role in ROLES:
            entry = data['families'][family][role]
            assert isinstance(entry['model'], str) and entry['model'], (family, role)
            assert entry['effort'] in model_roles.EFFORTS, (family, role)


@pytest.mark.parametrize('family, role', sorted(EXPECTED))
def test_the_default_model_and_effort_for_each_family_and_role(family, role):
    assert model_roles.resolve(family, role) == {'model': EXPECTED[(family, role)][0], 'effort': EXPECTED[(family, role)][1]}


def test_an_unknown_family_is_refused():
    with pytest.raises(model_roles.ModelRoleError):
        model_roles.resolve('mistral', 'planning')


def test_an_unknown_role_is_refused():
    with pytest.raises(model_roles.ModelRoleError):
        model_roles.resolve('claude', 'reviewer')


def test_the_opus_default_is_high_not_max():
    assert model_roles.resolve('claude', 'planning')['effort'] == 'high'


def test_the_table_is_for_a_list_of_roles_in_the_documented_order():
    assert model_roles.ROLES == ROLES

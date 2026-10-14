'''Default model and effort for each role of a runtime family (the model-roles table).

The table lives in _catalog/model_roles.json. resolve() reads it and refuses a family or a role it does not list, so a
typo fails loudly instead of falling back to some other model.
'''
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROLES = ('planning', 'coordination', 'execution')
EFFORTS = ('low', 'medium', 'high', 'xhigh')
CATALOG = Path(__file__).resolve().with_name('_catalog') / 'model_roles.json'


class ModelRoleError(ValueError):
    '''A family or a role that is not in the table.'''


def _table() -> dict[str, Any]:
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def resolve(family: str, role: str) -> dict[str, str]:
    '''The default {"model", "effort"} for a runtime family and a role.'''
    families = _table()['families']
    if family not in families:
        raise ModelRoleError('unknown runtime family: %s' % family)
    if role not in ROLES:
        raise ModelRoleError('unknown role: %s' % role)
    entry = families[family][role]
    return {'model': entry['model'], 'effort': entry['effort']}


def role_of(model: str) -> dict[str, str] | None:
    '''The {"role", "effort"} the table gives a model ID in any family, or None when no family lists it.'''
    for family in _table()['families'].values():
        for role in ROLES:
            entry = family[role]
            if entry['model'] == model:
                return {'role': role, 'effort': entry['effort']}
    return None

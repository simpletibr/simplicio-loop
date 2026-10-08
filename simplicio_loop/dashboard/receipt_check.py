'''Schema check for one receipt a run wrote (issue #1405, slice 1405c).

Only schemas the package ships are checked, listed in SHIPPED_SCHEMAS. A receipt with any other schema id is UNVERIFIED
with the reason, never valid. The check runs in-process with jsonschema, which is a runtime dependency.
'''
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / '_contracts'
# Receipt schema id -> the shipped schema file, relative to CONTRACTS_DIR. Add a row when a schema ships.
SHIPPED_SCHEMAS = {
    'simplicio.stage-receipt/v1': 'stage-agents/v1/stage-receipt.schema.json',
}
MAX_BYTES = 1_000_000


def _unverified(reason: str) -> dict[str, Any]:
    return {'state': 'UNVERIFIED', 'reason': reason}


def _first_error(schema: dict[str, Any], data: dict[str, Any]) -> jsonschema.ValidationError | None:
    validator = jsonschema.validators.validator_for(schema)(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: [str(part) for part in error.absolute_path])
    return errors[0] if errors else None


def check_receipt(path: Path) -> dict[str, Any]:
    '''VALID, INVALID or UNVERIFIED for one receipt file, with a readable reason. Never raises for a bad file.'''
    try:
        size = path.stat().st_size
    except OSError:
        return _unverified('recibo não pôde ser lido')
    if size > MAX_BYTES:
        return _unverified('recibo grande demais para validar')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except OSError:
        return _unverified('recibo não pôde ser lido')
    except ValueError:
        return _unverified('recibo ilegível: não é JSON')
    if not isinstance(data, dict) or not isinstance(data.get('schema'), str):
        return _unverified('recibo sem campo schema')
    shipped = SHIPPED_SCHEMAS.get(data['schema'])
    if shipped is None:
        return _unverified('sem schema publicado para ' + data['schema'])
    schema = json.loads((CONTRACTS_DIR / shipped).read_text(encoding='utf-8'))
    error = _first_error(schema, data)
    if error is None:
        return {'state': 'VALID', 'reason': 'conforme ao schema ' + data['schema']}
    where = '/'.join(str(part) for part in error.absolute_path) or '(raiz)'
    return {'state': 'INVALID', 'reason': where + ': ' + error.message}

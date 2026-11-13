import importlib
import hashlib
import json
import math
import os
from pathlib import Path
from studio.config import ROOT


def manifests():
    result = {}
    for path in sorted(Path(__file__).parent.glob('*/manifest.json')):
        value = json.loads(path.read_text())
        if value['id'] != path.parent.name:
            raise ValueError('Model manifest id must match its directory.')
        result[value['id']] = value
    return result


def manifest(identifier):
    if identifier not in manifests():
        raise ValueError('Unknown model module.')
    return manifests()[identifier]


def interpreter(identifier):
    manifest(identifier)
    override = os.environ.get('STUDIO_MODEL_PYTHON_' + identifier.upper())
    return Path(override) if override else ROOT / ('.venv-' + identifier) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def installed(identifier):
    python = interpreter(identifier)
    if not python.is_file():
        return False
    if os.environ.get('STUDIO_MODEL_PYTHON_' + identifier.upper()):
        return True
    requirements = ROOT / 'studio' / 'models' / identifier / 'requirements.txt'
    expected = hashlib.sha256(requirements.read_bytes() + (ROOT / 'requirements.txt').read_bytes()).hexdigest()
    stamp = ROOT / ('.venv-' + identifier) / '.requirements-sha256'
    return stamp.is_file() and stamp.read_text() == expected


def adapter(identifier):
    spec = manifest(identifier)
    module, name = spec['entrypoint'].split(':')
    return getattr(importlib.import_module(module), name)()


def validate_settings(identifier, supplied):
    spec = manifest(identifier)
    fields = {field['key']: field for field in spec['settings']}
    if not isinstance(supplied, dict) or set(supplied) - fields.keys():
        raise ValueError('Unknown model setting.')
    result = {}
    for key, field in fields.items():
        value = supplied.get(key, field.get('default'))
        kind = field['type']
        if kind == 'boolean':
            valid = isinstance(value, bool)
        elif kind in ('integer', 'number'):
            valid = not isinstance(value, bool) and isinstance(value, int if kind == 'integer' else (int, float)) and math.isfinite(value)
            valid = valid and field.get('min', float('-inf')) <= value <= field.get('max', float('inf'))
        else:
            valid = isinstance(value, str) and bool(value.strip())
            if valid:
                value = value.strip()
        if not valid or ('options' in field and value not in field['options']):
            raise ValueError('Invalid value for ' + field['label'] + '.')
        result[key] = value
    return result

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / 'studio.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, body TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, body TEXT)')

    def connect(self):
        return sqlite3.connect(self.db, timeout=30)

    def create(self, kind, body):
        value = dict(body, id=uuid4().hex, created_at=now())
        with self.connect() as db:
            db.execute('INSERT INTO records VALUES (?, ?, ?)', (value['id'], kind, json.dumps(value)))
        return value

    def get(self, kind, identifier):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
        if row is None:
            raise LookupError('Item not found.')
        return json.loads(row[0])

    def update(self, kind, identifier, **changes):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, identifier)).fetchone()
            if row is None:
                raise LookupError('Item not found.')
            body = dict(json.loads(row[0]), **changes, updated_at=now())
            db.execute('UPDATE records SET body=? WHERE id=?', (json.dumps(body), identifier))
        return body

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, body):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, json.dumps(body)))

    def directory(self, kind, identifier):
        self.get(kind, identifier)
        path = self.root / kind / identifier
        path.mkdir(parents=True, exist_ok=True)
        return path

    def release(self, identifier, action, reviewer=None):
        """Registry, experiment approval, and audit are one durable transaction."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', ('experiments', identifier)).fetchone()
            if not row:
                raise LookupError('Experiment not found.')
            experiment = json.loads(row[0])
            row = db.execute('SELECT body FROM settings WHERE key=?', ('active',)).fetchone()
            active = json.loads(row[0]) if row else {}
            previous = active.get(experiment['model_id'])
            if action == 'approve':
                if experiment['status'] != 'evaluated' or not experiment.get('acceptance_result', {}).get('passed'):
                    raise ValueError('Only candidates that pass their final evaluation can be approved.')
                if previous != experiment.get('baseline_id'):
                    raise ValueError('The active baseline changed. Create a new experiment against the current model before approval.')
                experiment.update(status='approved', approved_at=now(), approved_by=reviewer)
            elif action != 'rollback' or experiment['status'] != 'approved':
                raise ValueError('Only previously approved versions can be restored.')
            active[experiment['model_id']] = identifier
            event = {'id': uuid4().hex, 'created_at': now(), 'model_id': experiment['model_id'],
                     'experiment_id': identifier, 'previous_id': previous, 'action': action, 'reviewer': reviewer}
            db.execute('UPDATE records SET body=? WHERE id=?', (json.dumps(experiment), identifier))
            db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', ('active', json.dumps(active)))
            db.execute('INSERT INTO records VALUES (?, ?, ?)', (event['id'], 'releases', json.dumps(event)))

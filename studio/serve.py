"""Explicitly serve approved checkpoints; never started by npm run dev."""
import os
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from flask import Flask, jsonify, request
from studio.config import DATA_DIR, ROOT
from studio.models.registry import adapter, interpreter, installed
from studio.store import Store


def main():
    store = Store(DATA_DIR)
    identifier = os.environ.get('STUDIO_MODEL_MODULE')
    active = store.setting('active', {})
    if not identifier:
        if len(active) != 1:
            raise SystemExit('Approve a checkpoint first. With multiple approved model families, set STUDIO_MODEL_MODULE to choose one.')
        identifier = next(iter(active))
    if identifier not in active:
        raise SystemExit('This model module has no approved checkpoint.')
    if os.environ.get('STUDIO_MODEL_WORKER') != '1':
        python = interpreter(identifier)
        if not installed(identifier):
            raise SystemExit(f'Run npm run setup:model -- {identifier} first.')
        os.execve(str(python), [str(python), '-m', 'studio.serve'],
                  dict(os.environ, STUDIO_MODEL_WORKER='1', STUDIO_MODEL_MODULE=identifier))
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
    engine = adapter(identifier)
    lock = threading.Lock()
    # Snapshot the approved release on startup. Registry changes require an explicit restart.
    release = store.get('experiments', active[identifier])
    if release['status'] != 'approved':
        raise SystemExit('The selected checkpoint is not approved.')
    settings = release['settings']
    if settings.get('offline'):
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
    runtime = engine.load(store.directory('experiments', release['id']) / 'checkpoint', settings)

    @app.before_request
    def local_only():
        if urlsplit('http://' + request.host).hostname not in ('127.0.0.1', 'localhost', '::1') or request.headers.get('Origin'):
            return jsonify(error='Use the trusted local connector for browser access.'), 403

    @app.get('/health')
    def health():
        return jsonify(ok=True, model=identifier, experiment_id=release['id'])

    @app.post('/v1/systemone')
    def predict():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get('questions'), dict) or not data['questions'] or 'state' not in data:
            return jsonify(error='Provide state and questions.'), 400
        try:
            with lock:
                result = engine.predict(runtime, data['state'], data['questions'])
            result['checkpoint_id'] = release['id']
            return jsonify(result)
        except Exception:
            app.logger.exception('Prediction failed')
            return jsonify(error='The model could not answer this request. Check its question schema and the local terminal.'), 400

    port = int(os.environ.get('STUDIO_INFERENCE_PORT', '8002'))
    print(f'Approved model {release["name"]}: http://127.0.0.1:{port}', flush=True)
    print('Restart this server after an approval or rollback to serve that release.', flush=True)
    app.run(host='127.0.0.1', port=port, threaded=True, debug=False)


if __name__ == '__main__':
    main()

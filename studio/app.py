import csv
import io
import json
import math
import os
import platform
import threading
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from studio.config import ROOT, DATA_DIR, PORT, DEFAULTS
from studio.datasets import (read_spreadsheet, describe, import_codebook, inspect, save_partitions,
                             digest, language_suggestions)
from studio.jobs import Jobs
from studio.models.registry import manifests, manifest, validate_settings, interpreter, installed
from studio.store import Store, write_json, now


def create_app(data_dir=None, start_jobs=True):
    app = Flask(__name__, static_folder=str(ROOT / 'static'), static_url_path='/static')
    app.config['MAX_CONTENT_LENGTH'] = DEFAULTS['max_upload_mb'] * 1024 * 1024
    store = Store(data_dir or DATA_DIR)
    jobs = Jobs(store) if start_jobs else None
    app.extensions['store'] = store
    app.extensions['jobs'] = jobs
    mutation_lock = threading.Lock()

    @app.before_request
    def local_only():
        host = urlsplit('http://' + request.host).hostname
        if host not in ('localhost', '127.0.0.1', '::1'):
            return jsonify(error='Model Studio accepts localhost requests only.'), 403
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            return jsonify(error='Cross-origin requests are not allowed.'), 403
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('X-Studio-Request') != '1':
            return jsonify(error='Missing local request header.'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error='The upload is too large.' if error.code == 413 else error.description), error.code
        if isinstance(error, (ValueError, UnicodeError, LookupError)):
            return jsonify(error=str(error)), 404 if isinstance(error, LookupError) else 400
        app.logger.exception('Request failed')
        return jsonify(error='The operation failed. Check the local terminal for details.'), 500

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError('Expected an object.')
        return value

    def dataset_data(identifier):
        record = store.get('datasets', identifier)
        path = store.directory('datasets', identifier) / 'data.json'
        return record, json.loads(path.read_text(encoding='utf-8'))

    def public_report(report):
        return {key: value if key != 'issues' else value[:100] for key, value in report.items() if key != 'partitions'}

    @app.get('/')
    def index():
        return send_file(ROOT / 'static' / 'index.html')

    @app.get('/api/status')
    def status():
        models = [dict(spec, installed=installed(key)) for key, spec in manifests().items()]
        return jsonify(models=models, platform=platform.system(), machine=platform.machine(),
                       defaults=store.setting('defaults', DEFAULTS), active=store.setting('active', {}),
                       data_directory=str(store.root), version='0.1.0')

    @app.put('/api/settings')
    def settings():
        value = body()
        allowed = {'test_fraction', 'calibration_fraction', 'train_fraction', 'min_test_decisions', 'min_accuracy_gain', 'max_slice_regression', 'min_slice_size'}
        if set(value) - allowed:
            raise ValueError('Unknown preference.')
        result = dict(store.setting('defaults', DEFAULTS))
        for key, v in value.items():
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v):
                raise ValueError('Preferences must be finite numbers.')
            if key in ('min_test_decisions', 'min_slice_size'):
                if type(v) is not int or not 1 <= v <= 100000:
                    raise ValueError('Minimum sample counts must be positive whole numbers.')
            elif key == 'train_fraction':
                if not 0.5 <= v <= 0.95:
                    raise ValueError('Training share must be 50–95%.')
            elif key in ('test_fraction', 'calibration_fraction'):
                if not 0.05 <= v <= 0.3:
                    raise ValueError('Test and calibration shares must be 5–30%.')
            elif not 0 <= v <= 0.5:
                raise ValueError('Acceptance tolerances must be 0–50%.')
            result[key] = v
        store.set_setting('defaults', result)
        return jsonify(result)

    @app.get('/api/datasets')
    def datasets_list():
        return jsonify(store.list('datasets'))

    @app.post('/api/datasets')
    def upload():
        upload = request.files.get('file')
        if not upload or not upload.filename:
            raise ValueError('Choose a spreadsheet.')
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ('.xlsx', '.csv', '.jsonl'):
            raise ValueError('Choose an .xlsx, .csv, or .jsonl file.')
        import tempfile
        with tempfile.TemporaryDirectory(dir=store.root) as temporary:
            path = Path(temporary) / ('upload' + suffix)
            upload.save(path)
            data = read_spreadsheet(path, DEFAULTS['max_rows'])
            policy = store.setting('defaults', DEFAULTS)
            record = store.create('datasets', dict(name=Path(upload.filename).name, **describe(data),
                                  sheets=data['sheets'], sheet=data['sheet'], split_policy={k: policy[k] for k in ('test_fraction', 'calibration_fraction', 'split_seed')},
                                  fingerprint=digest(data)))
            directory = store.directory('datasets', record['id'])
            path.replace(directory / ('original' + suffix))
            write_json(directory / 'data.json', data)
        return jsonify(record), 201

    @app.post('/api/datasets/<identifier>/sheet')
    def select_sheet(identifier):
        record = store.get('datasets', identifier)
        if any(e['dataset_id'] == identifier for e in store.list('experiments')):
            raise ValueError('This dataset is frozen by an experiment. Upload again to use a different sheet.')
        directory = store.directory('datasets', identifier)
        data = read_spreadsheet(directory / 'original.xlsx', DEFAULTS['max_rows'], body()['sheet'])
        write_json(directory / 'data.json', data)
        return jsonify(store.update('datasets', identifier, **describe(data), sheet=data['sheet'], fingerprint=digest(data)))

    @app.post('/api/codebooks/inspect')
    def inspect_codebook():
        return jsonify(import_codebook(body()))

    @app.post('/api/datasets/<identifier>/languages')
    def languages(identifier):
        record, data = dataset_data(identifier)
        return jsonify(language_suggestions(data, body().get('column')))

    @app.post('/api/datasets/<identifier>/inspect')
    def quality(identifier):
        value = body()
        record, data = dataset_data(identifier)
        result = inspect(data, value['mapping'], manifest(value['model_id']), record['split_policy'])
        return jsonify(public_report(result))

    @app.get('/api/experiments')
    def experiments_list():
        return jsonify(store.list('experiments'))

    @app.get('/api/experiments/<identifier>')
    def experiment_get(identifier):
        return jsonify(store.get('experiments', identifier))

    @app.post('/api/experiments')
    def experiment_create():
        value = body()
        name = value.get('name', '').strip()
        if not name or len(name) > 160:
            raise ValueError('Give the experiment a name of 1–160 characters.')
        model_id = value['model_id']
        settings = validate_settings(model_id, value.get('settings', {}))
        if not value.get('mapping', {}).get('codebook') and value.get('mapping', {}).get('taxonomy_confirmed') is not True:
            raise ValueError('Confirm the inferred categories and coding instructions before saving.')
        record, data = dataset_data(value['dataset_id'])
        result = inspect(data, value['mapping'], manifest(model_id), record['split_policy'])
        if any(result['split_counts'][key] == 0 for key in ('train', 'validation', 'calibration', 'test')):
            raise ValueError('Each split needs eligible records. Add more team-validated examples; unlabelled files can be inspected but cannot start supervised training.')
        defaults = store.setting('defaults', DEFAULTS)
        active_id = store.setting('active', {}).get(model_id)
        baseline = str(store.directory('experiments', active_id) / 'checkpoint') if active_id else settings['base_checkpoint']
        experiment = store.create('experiments', {'name': name, 'dataset_id': record['id'], 'dataset_name': record['name'],
            'dataset_fingerprint': record['fingerprint'], 'model_id': model_id, 'module_version': manifest(model_id)['version'],
            'settings': settings, 'mapping': value['mapping'], 'split_policy': record['split_policy'],
            'baseline_checkpoint': baseline, 'baseline_id': active_id, 'status': 'draft',
            'message': 'Ready to train. The active model has not changed.',
            'acceptance': {k: defaults[k] for k in ('min_test_decisions', 'min_accuracy_gain', 'max_slice_regression', 'min_slice_size')}})
        directory = store.directory('experiments', experiment['id'])
        quality = save_partitions(directory, result)
        experiment = store.update('experiments', experiment['id'], quality={k: v for k, v in quality.items() if k != 'issues'})
        write_json(directory / 'experiment.json', experiment)
        return jsonify(experiment), 201

    @app.post('/api/experiments/<identifier>/<action>')
    def experiment_action(identifier, action):
        value = body()
        with mutation_lock:
            experiment = store.get('experiments', identifier)
            if action in ('train', 'test'):
                if not jobs:
                    raise ValueError('Job execution is disabled in this instance.')
                if action == 'test' and value.get('confirmed') is not True:
                    raise ValueError('Confirm that this candidate is ready for its final test.')
                jobs.start(identifier, action)
            elif action == 'cancel':
                jobs.cancel(identifier)
            elif action == 'approve':
                if experiment['status'] != 'evaluated' or not experiment.get('acceptance_result', {}).get('passed'):
                    raise ValueError('Only candidates that pass their final evaluation can be approved.')
                if not str(value.get('reviewer', '')).strip():
                    raise ValueError('Enter the approving reviewer’s name.')
                store.release(identifier, 'approve', value['reviewer'].strip())
            elif action == 'rollback':
                if experiment['status'] != 'approved' or value.get('confirmed') is not True:
                    raise ValueError('Confirm rollback to a previously approved version.')
                store.release(identifier, 'rollback')
            else:
                raise LookupError('Action not found.')
        return jsonify(store.get('experiments', identifier))

    @app.get('/api/experiments/<identifier>/download/<kind>')
    def download(identifier, kind):
        directory = store.directory('experiments', identifier)
        allowed = {'configuration': 'experiment.json', 'quality': 'quality.json', 'log': 'job.log', 'validation': 'validation-comparison.json', 'test': 'test-comparison.json'}
        if kind not in allowed or not (directory / allowed[kind]).exists():
            raise LookupError('This file is not available yet.')
        return send_file(directory / allowed[kind], as_attachment=True)

    @app.get('/api/experiments/<identifier>/log')
    def job_log(identifier):
        path = store.directory('experiments', identifier) / 'job.log'
        if not path.exists():
            return jsonify(text='No worker log yet.')
        with path.open('rb') as handle:
            handle.seek(max(0, path.stat().st_size - 12000))
            return jsonify(text=handle.read().decode('utf-8', errors='replace'))

    @app.get('/api/releases')
    def releases():
        return jsonify(store.list('releases'))

    return app


if __name__ == '__main__':
    os.umask(0o077)
    app = create_app()
    print(f'\nAidstack Model Studio → http://127.0.0.1:{PORT}\nLocal data: {DATA_DIR}\n', flush=True)
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False, threaded=True)

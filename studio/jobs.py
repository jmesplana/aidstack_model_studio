import atexit
import os
import subprocess
import threading
from studio.config import ROOT
from studio.models.registry import interpreter, installed


class Jobs:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.processes = {}
        for experiment in store.list('experiments'):
            if experiment['status'] == 'running':
                store.update('experiments', experiment['id'], status='interrupted', message='The app restarted during this job. Its partial checkpoint was not approved.')
        atexit.register(self.stop_all)

    def start(self, identifier, action):
        with self.lock:
            if any(p.poll() is None for p in self.processes.values()):
                raise ValueError('Another job is running. Wait for it or stop it first.')
            item = self.store.get('experiments', identifier)
            if action == 'train' and item['status'] != 'draft':
                raise ValueError('Training starts from a draft. Create a new experiment to retry with a clean checkpoint.')
            if action == 'test' and item['status'] != 'trained':
                raise ValueError('The final test runs once after successful training. Create a new experiment if a test failed.')
            python = interpreter(item['model_id'])
            if not installed(item['model_id']):
                raise ValueError(f"Install this model module first: npm run setup:model -- {item['model_id']}")
            directory = self.store.directory('experiments', identifier)
            log = (directory / 'job.log').open('a', encoding='utf-8')
            self.store.update('experiments', identifier, status='running', action=action, phase='starting', message='Starting the isolated model worker.')
            try:
                process = subprocess.Popen([str(python), '-u', '-m', 'studio.worker', str(self.store.root), identifier, action],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONUNBUFFERED='1'))
            except Exception:
                self.store.update('experiments', identifier, status='failed', message='Could not start the model worker.')
                raise
            finally:
                log.close()
            self.processes[identifier] = process
            threading.Thread(target=self.monitor, args=(identifier, process), daemon=True).start()

    def monitor(self, identifier, process):
        code = process.wait()
        if self.store.get('experiments', identifier)['status'] == 'running':
            self.store.update('experiments', identifier, status='failed', phase='failed',
                              message=f'The worker exited with code {code}. See the job log; memory exhaustion or missing model dependencies can cause this.')

    def cancel(self, identifier):
        with self.lock:
            process = self.processes.get(identifier)
            if not process or process.poll() is not None:
                raise ValueError('This job is not running.')
            self.store.update('experiments', identifier, status='cancelled', message='Job stopped. The partial checkpoint cannot be approved.')
            process.terminate()

    def stop_all(self):
        for identifier, process in self.processes.items():
            if process.poll() is None:
                self.store.update('experiments', identifier, status='interrupted', message='App closed during the job. Create a new experiment to run again.')
                process.terminate()

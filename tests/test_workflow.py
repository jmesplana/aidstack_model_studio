import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from studio.app import create_app
from studio.metrics import report, gate
from studio.store import Store, write_json
from studio.worker import run
from test_data import fixture, mapping

HEADERS = {'X-Studio-Request': '1'}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(self.temporary.name, start_jobs=False)
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']

    def tearDown(self):
        self.temporary.cleanup()

    def upload(self):
        data = fixture()
        rows = ['text,category,language,review,source'] + [','.join(row.values()) for row in data['rows']]
        result = self.client.post('/api/datasets', data={'file': (io.BytesIO('\n'.join(rows).encode()), 'reviewed.csv')}, headers=HEADERS)
        self.assertEqual(result.status_code, 201, result.json)
        return result.json

    def experiment(self):
        dataset = self.upload()
        response = self.client.post('/api/experiments', json={'dataset_id': dataset['id'], 'model_id': 'laya',
            'settings': {}, 'mapping': mapping(), 'name':'Test candidate'}, headers=HEADERS)
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def test_upload_and_create_never_activate_a_model(self):
        experiment = self.experiment()
        self.assertEqual(experiment['status'], 'draft')
        self.assertEqual(self.store.setting('active', {}), {})
        directory = self.store.directory('experiments', experiment['id'])
        self.assertTrue((directory / 'train.jsonl').is_file())
        self.assertFalse((directory / 'checkpoint').exists())

    def test_cross_origin_and_missing_header_requests_are_rejected(self):
        self.assertEqual(self.client.post('/api/settings', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings', json={}, headers={**HEADERS,'Origin':'https://other.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/status', base_url='http://evil.example').status_code, 403)

    def test_cannot_approve_without_passing_final_test(self):
        experiment = self.experiment()
        path = '/api/experiments/' + experiment['id'] + '/approve'
        response = self.client.post(path, json={'reviewer': 'Tester'}, headers=HEADERS)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.setting('active', {}), {})
        self.store.update('experiments', experiment['id'], status='evaluated', acceptance_result={'passed':False})
        self.assertEqual(self.client.post(path, json={'reviewer':'Tester'}, headers=HEADERS).status_code, 400)

    def test_approval_is_audited_and_stale_baseline_is_rejected(self):
        first, second = self.experiment(), self.experiment()
        for item in (first, second):
            self.store.update('experiments', item['id'], status='evaluated', acceptance_result={'passed':True})
        response = self.client.post(f'/api/experiments/{first["id"]}/approve',json={'reviewer':'Team reviewer'},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(self.store.list('releases')),1)
        response = self.client.post(f'/api/experiments/{second["id"]}/approve',json={'reviewer':'Team reviewer'},headers=HEADERS)
        self.assertEqual(response.status_code,400)
        self.assertIn('baseline changed',response.json['error'])

    def test_settings_changes_do_not_mutate_existing_experiments_or_datasets(self):
        experiment = self.experiment()
        self.client.put('/api/settings',json={'min_test_decisions':99,'test_fraction':.2},headers=HEADERS)
        saved = self.store.get('experiments',experiment['id'])
        self.assertEqual(saved['acceptance'],experiment['acceptance'])
        self.assertEqual(saved['split_policy']['test_fraction'],.1)

    def test_frozen_dataset_cannot_change_sheets(self):
        experiment=self.experiment()
        response=self.client.post(f'/api/datasets/{experiment["dataset_id"]}/sheet',json={'sheet':'Other'},headers=HEADERS)
        self.assertEqual(response.status_code,400)

    def test_inferred_taxonomy_requires_confirmation(self):
        dataset=self.upload()
        response=self.client.post('/api/experiments',json={'dataset_id':dataset['id'],'model_id':'laya','settings':{},
            'mapping':mapping(taxonomy_confirmed=False),'name':'Unconfirmed'},headers=HEADERS)
        self.assertEqual(response.status_code,400)

    def test_ui_assets_and_module_contract_are_available(self):
        with self.client.get('/') as response:
            self.assertEqual(response.status_code,200)
        with self.client.get('/static/js/app.js') as response:
            self.assertEqual(response.status_code,200)
        response=self.client.get('/api/status')
        self.assertEqual(response.json['models'][0]['id'],'laya')
        self.assertIn('settings',response.json['models'][0])


class MetricsTests(unittest.TestCase):
    def test_accuracy_does_not_hide_rare_category_regression(self):
        truth=['common']*90+['critical']*10
        base=[{'row_id':i,'question':'q','expected':v,'predicted':v if i!=0 else 'critical',
               'confidence':.8,'language':'fr','slices':{}} for i,v in enumerate(truth)]
        candidate=[dict(p,predicted='common') for p in base]
        comparison={'baseline':report(base,1),'candidate':report(candidate,1)}
        result=gate(comparison,{'min_test_decisions':30,'min_accuracy_gain':0,'min_slice_size':20,'max_slice_regression':.02})
        self.assertFalse(result['passed'])
        self.assertTrue(any('Macro F1' in reason for reason in result['reasons']))

    def test_unknown_language_is_reported_instead_of_invented(self):
        predictions=[{'question':'q','expected':'A','predicted':'A','confidence':.8,'language':'Unknown','slices':{}}]
        self.assertIn('language:Unknown',report(predictions,1)['slices'])


class AdapterBoundaryTests(unittest.TestCase):
    def test_worker_uses_adapter_without_laya_import_or_training_on_test_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=Store(temporary)
            experiment=store.create('experiments',{'model_id':'another_model','settings':{},'baseline_checkpoint':'baseline',
                                                 'status':'running','acceptance':{}})
            directory=store.directory('experiments',experiment['id'])
            for index,split in enumerate(('train','calibration','validation','test')):
                decision={'state':split,'row_id':index,'questions':{'q':{'type':'choice'}},'expected':{'q':'A'},'language':'fr','slices':{}}
                (directory/(split+'.jsonl')).write_text(json.dumps(decision)+'\n')
            calls=[]
            class AnotherAdapter:
                def train(self,training,calibration,output,settings,progress):
                    calls.extend([training[0]['state'],calibration[0]['state']])
                    output.mkdir()
                    return {'test_fixture':True}
                def evaluate(self,checkpoint,decisions,settings,progress):
                    calls.append(decisions[0]['state'])
                    return [{'row_id':r['row_id'],'question':'q','expected':'A','predicted':'A','confidence':.9,'language':'fr','slices':{}} for r in decisions],1
            with patch('studio.worker.adapter',return_value=AnotherAdapter()):
                self.assertEqual(run(temporary,experiment['id'],'train'),0)
            self.assertEqual(calls,['train','calibration','validation','validation'])
            self.assertEqual(store.get('experiments',experiment['id'])['status'],'trained')
            self.assertFalse((directory/'test-comparison.json').exists())

import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from studio.config import DEFAULTS
from studio.datasets import inspect, read_spreadsheet, compile_question
from studio.models.registry import manifest, validate_settings


def fixture(n=300):
    return {'columns': ['text', 'category', 'language', 'review', 'source'],
            'rows': [{'text': f'Synthetic feedback example {i}', 'category': 'Request' if i % 2 else 'Praise',
                      'language': 'fr' if i % 3 else 'ln', 'review': 'Approved', 'source': f'case-{i // 2}'} for i in range(n)],
            'sheets': [], 'sheet': None}


def mapping(**overrides):
    return dict({'inputs': ['text'], 'targets': ['category'], 'review_mode': 'all_verified', 'review_confirmed': True,
                 'language_column': 'language', 'taxonomy_confirmed': True, 'train_fraction': .8}, **overrides)


class DataTests(unittest.TestCase):
    def analyze(self, data, config=None):
        return inspect(data, config or mapping(), manifest('laya'), DEFAULTS)

    def test_duplicates_conflicts_and_related_records_do_not_leak(self):
        data = fixture()
        data['rows'].append(dict(data['rows'][0], text='  SYNTHETIC   feedback example 0 '))
        data['rows'].append(dict(data['rows'][1], category='Praise'))
        report = self.analyze(data, mapping(group_column='source'))
        self.assertEqual(report['counts']['duplicate'], 1)
        self.assertEqual(report['counts']['label_conflict'], 2)
        memberships = {}
        for split, rows in report['partitions'].items():
            for row in rows:
                self.assertEqual(memberships.setdefault(row['group'], split), split)
                self.assertNotIn(row['row_id'], (3, 303))

    def test_unverified_labels_never_enter_evaluation_or_calibration(self):
        data = fixture(500)
        for row in data['rows'][::2]:
            row['review'] = 'AI only'
        config = mapping(review_mode='column', review_column='review', verified_values=['Approved'], include_unverified=True)
        report = self.analyze(data, config)
        self.assertTrue(any(r['provenance'] == 'unverified' for r in report['partitions']['train']))
        for split in ('test', 'calibration', 'validation'):
            self.assertTrue(report['partitions'][split])
            self.assertTrue(all(r['provenance'] == 'human_validated' for r in report['partitions'][split]))

    def test_test_and_calibration_stay_locked_when_training_share_changes(self):
        data = fixture()
        before = self.analyze(data, mapping(train_fraction=.8))
        after = self.analyze(data, mapping(train_fraction=.9))
        for split in ('test', 'calibration'):
            self.assertEqual(before['partitions'][split], after['partitions'][split])

    def test_missing_labels_are_excluded_not_treated_as_a_class(self):
        data = fixture()
        data['rows'][0]['category'] = ''
        report = self.analyze(data)
        self.assertEqual(report['counts']['missing_labels'], 1)
        self.assertNotIn('', report['label_mappings']['category'])

    def test_targets_cannot_be_inputs(self):
        with self.assertRaisesRegex(ValueError, 'Target labels cannot'):
            self.analyze(fixture(), mapping(inputs=['text', 'category']))

    def test_team_review_requires_confirmation(self):
        with self.assertRaisesRegex(ValueError, 'Confirm'):
            self.analyze(fixture(), mapping(review_confirmed=False))

    def test_jev_options_and_score_order_are_preserved(self):
        question, labels = compile_question({'outputColumnName': 'Topic', 'questionType': 'choice',
            'instructions': 'Choose.', 'options': [{'label': 'Santé', 'description': 'Health services'}, 'Sante']})
        self.assertEqual(labels, {'Santé': 'sante', 'Sante': 'sante_2'})
        self.assertEqual(question['criteria']['sante'], 'Health services')
        _, scores = compile_question({'outputColumnName': 'Urgency', 'questionType': 'score',
            'instructions': 'Urgency.', 'options': ['Low', 'High']})
        self.assertEqual(scores, {'Low': 0, 'High': 1})

    def test_staged_codebooks_are_rejected_instead_of_flattened(self):
        with self.assertRaisesRegex(ValueError, 'staged questions'):
            compile_question({'outputColumnName':'Detail','questionType':'choice','instructions':'Choose',
                              'options':['A','B'],'dependsOn':['Parent']})

    def test_typed_plugin_settings_are_validated(self):
        self.assertEqual(validate_settings('laya', {'epochs': 8})['epochs'], 8)
        for value in (True, -2, 1.4, float('nan')):
            with self.assertRaises(ValueError):
                validate_settings('laya', {'epochs': value})
        with self.assertRaises(ValueError):
            validate_settings('laya', {'execute': 'anything'})

    def test_csv_headers_shape_and_utf8(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'test.csv'
            path.write_text('\ufefftext,category\nBonjour,Santé\n', encoding='utf-8')
            self.assertEqual(read_spreadsheet(path, 10)['rows'][0]['category'], 'Santé')
            for content in ('text,text\nx,y\n', 'text,category\nx,y,z\n'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    read_spreadsheet(path, 10)

    def test_xlsx_sheet_selection_and_formula_rejection(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'test.xlsx'
            book = Workbook()
            book.active.append(['text', 'category'])
            book.active.append(['Hello', 'Request'])
            second = book.create_sheet('Reviewed')
            second.append(['text', 'category'])
            second.append(['Bonjour', 'Demande'])
            book.save(path)
            result = read_spreadsheet(path, 100, 'Reviewed')
            self.assertEqual(result['rows'][0]['category'], 'Demande')
            second['A2'] = '=1+1'
            book.save(path)
            with self.assertRaisesRegex(ValueError, 'Formula'):
                read_spreadsheet(path, 100, 'Reviewed')

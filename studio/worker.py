"""Runs inside the selected module's isolated Python environment."""
import json
import math
import os
import sys
import traceback
from pathlib import Path
from studio.datasets import read_decisions
from studio.metrics import report, gate
from studio.models.registry import adapter
from studio.store import Store, now, write_json


def run(root, identifier, action):
    store = Store(root)
    experiment = store.get('experiments', identifier)
    directory = store.directory('experiments', identifier)
    settings = experiment['settings']
    if settings.get('offline'):
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
    engine = adapter(experiment['model_id'])

    def progress(phase, message, **extra):
        current = store.get('experiments', identifier)
        if current['status'] != 'running':
            raise RuntimeError('Job was stopped or interrupted.')
        store.update('experiments', identifier, phase=phase, message=message, **extra)
        print(message, flush=True)

    def compare(partition):
        decisions = read_decisions(directory / (partition + '.jsonl'))
        if not decisions:
            raise ValueError('This split has no eligible human-validated rows.')
        progress('evaluating', f'Evaluating the baseline on {partition} examples.')
        before, before_time = engine.evaluate(experiment['baseline_checkpoint'], decisions, settings, progress)
        progress('evaluating', f'Evaluating the candidate on the same {partition} examples.')
        after, after_time = engine.evaluate(directory / 'checkpoint', decisions, settings, progress)
        expected_keys = {(row['row_id'], name) for row in decisions for name in row['expected']}
        references = {(row['row_id'], name): (row['expected'][name], row['language'], row['slices']) for row in decisions for name in row['expected']}
        for predictions in (before, after):
            if len(predictions) != len(expected_keys) or {(p['row_id'], p['question']) for p in predictions} != expected_keys:
                raise ValueError('The model did not return exactly one prediction for every held-out decision.')
            for prediction in predictions:
                reference = references[prediction['row_id'], prediction['question']]
                if (prediction['expected'], prediction['language'], prediction['slices']) != reference:
                    raise ValueError('The model adapter changed evaluation references or cohort labels.')
                confidence = prediction.get('confidence')
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError('The model adapter returned an invalid confidence probability.')
        comparison = {'baseline': report(before, before_time), 'candidate': report(after, after_time),
                      'partition': partition, 'evaluated_at': now()}
        write_json(directory / (partition + '-predictions.json'), {'baseline': before, 'candidate': after})
        write_json(directory / (partition + '-comparison.json'), comparison)
        return comparison

    try:
        if action == 'train':
            training = read_decisions(directory / 'train.jsonl')
            calibration = read_decisions(directory / 'calibration.jsonl')
            metadata = engine.train(training, calibration, directory / 'checkpoint', settings, progress)
            write_json(directory / 'training.json', metadata)
            if not experiment.get('baseline_id') and metadata.get('resolved_base_checkpoint'):
                experiment['baseline_checkpoint'] = metadata['resolved_base_checkpoint']
                store.update('experiments', identifier, baseline_checkpoint=experiment['baseline_checkpoint'])
                write_json(directory / 'experiment.json', store.get('experiments', identifier))
            comparison = compare('validation')
            progress('finished', 'Candidate trained. Review validation results before opening the locked test set.')
            store.update('experiments', identifier, status='trained', training=metadata, validation=comparison)
        else:
            comparison = compare('test')
            acceptance = gate(comparison, experiment['acceptance'])
            progress('finished', 'Final evaluation complete. Production approval is a separate action.')
            store.update('experiments', identifier, status='evaluated', test=comparison, acceptance_result=acceptance)
    except Exception as error:
        traceback.print_exc()
        if store.get('experiments', identifier)['status'] == 'running':
            store.update('experiments', identifier, status='failed', phase='failed', message=str(error), failed_action=action)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(run(*sys.argv[1:4]))

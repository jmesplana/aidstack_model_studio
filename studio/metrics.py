"""Metrics use human-validated held-out answers, never model agreement as truth."""
from collections import Counter, defaultdict


def summarize(predictions):
    n = len(predictions)
    if not n:
        return {'n': 0, 'accuracy': None, 'macro_f1': None, 'ece': None, 'per_class': []}
    correct = sum(p['expected'] == p['predicted'] for p in predictions)
    # Namespace labels by question so unrelated categories never merge.
    truth = Counter((p['question'], str(p['expected'])) for p in predictions)
    predicted = Counter((p['question'], str(p['predicted'])) for p in predictions)
    hits = Counter((p['question'], str(p['expected'])) for p in predictions if p['expected'] == p['predicted'])
    classes = []
    for key in sorted(truth.keys() | predicted.keys()):
        precision = hits[key] / predicted[key] if predicted[key] else 0
        recall = hits[key] / truth[key] if truth[key] else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        classes.append({'question': key[0], 'label': key[1], 'n': truth[key], 'precision': precision, 'recall': recall, 'f1': f1})
    bins = defaultdict(list)
    for p in predictions:
        bins[min(9, int(p['confidence'] * 10))].append(p)
    ece = sum(len(bucket) / n * abs(sum(p['confidence'] for p in bucket) / len(bucket) -
              sum(p['expected'] == p['predicted'] for p in bucket) / len(bucket)) for bucket in bins.values())
    confusion = Counter((p['question'], str(p['expected']), str(p['predicted'])) for p in predictions if p['expected'] != p['predicted'])
    return {'n': n, 'accuracy': correct / n, 'macro_f1': sum(c['f1'] for c in classes) / len(classes),
            'ece': ece, 'per_class': classes,
            'confusions': [{'question': q, 'expected': e, 'predicted': p, 'count': count} for (q, e, p), count in confusion.most_common(20)]}


def report(predictions, elapsed):
    groups = defaultdict(list)
    for prediction in predictions:
        groups['language:' + prediction['language']].append(prediction)
        groups['question:' + prediction['question']].append(prediction)
        for column, value in prediction.get('slices', {}).items():
            groups[column + ':' + value].append(prediction)
    return {'overall': summarize(predictions), 'slices': {key: summarize(rows) for key, rows in groups.items()},
            'seconds': elapsed, 'milliseconds_per_decision': elapsed * 1000 / len(predictions) if predictions else None,
            'cost_note': 'Local execution; energy and hardware costs are not measured.'}


def gate(comparison, policy):
    before, after = comparison['baseline'], comparison['candidate']
    reasons = []
    a, b = before['overall'], after['overall']
    if b['n'] < policy['min_test_decisions']:
        reasons.append(f"Need at least {policy['min_test_decisions']} human-validated test decisions; found {b['n']}.")
    if a['n'] != b['n'] or not b['n']:
        reasons.append('Both models must evaluate the same complete test set.')
    if a['accuracy'] is None or b['accuracy'] is None or b['accuracy'] - a['accuracy'] <= policy['min_accuracy_gain']:
        reasons.append('Candidate accuracy must exceed the baseline by the configured minimum gain.')
    if a['macro_f1'] is not None and b['macro_f1'] is not None and b['macro_f1'] < a['macro_f1']:
        reasons.append('Macro F1 decreased, indicating worse category balance.')
    for key, metric in after['slices'].items():
        previous = before['slices'].get(key)
        if metric['n'] >= policy['min_slice_size'] and previous and previous['accuracy'] - metric['accuracy'] > policy['max_slice_regression']:
            reasons.append(f'{key} regressed beyond the allowed tolerance.')
    return {'passed': not reasons, 'reasons': reasons, 'policy': policy,
            'note': 'These are configured acceptance rules, not a statistical significance claim. Inspect rare and critical categories before approval.'}

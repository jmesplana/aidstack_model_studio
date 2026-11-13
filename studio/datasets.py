"""Spreadsheet ingestion, auditable quality checks, and grouped data partitions."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from studio.store import write_json


def text(value):
    return '' if value is None else str(value).strip()


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', text(value)).casefold().split())


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_spreadsheet(path, limit, sheet=None):
    extension = Path(path).suffix.lower()
    sheets = []
    if extension == '.xlsx':
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=False)
        try:
            sheets = book.sheetnames
            sheet = sheet or sheets[0]
            if sheet not in sheets:
                raise ValueError('Choose an existing worksheet.')
            values = book[sheet].iter_rows()
            header = next(values, ())
            columns = [text(c.value) for c in header]
            rows = []
            for index, cells in enumerate(values):
                if index >= limit:
                    raise ValueError(f'This worksheet exceeds the {limit:,}-row limit. Split the file or increase STUDIO_MAX_ROWS.')
                if any(c.data_type == 'f' for c in cells):
                    raise ValueError('Formula cells are not supported. Save a copy with values only before importing.')
                row = [text(c.value) for c in cells]
                if any(row):
                    rows.append(row)
        finally:
            book.close()
    elif extension == '.csv':
        with open(path, encoding='utf-8-sig', newline='') as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(handle, dialect)
            columns = [text(c) for c in next(reader, [])]
            rows = []
            for index, row in enumerate(reader):
                if index >= limit:
                    raise ValueError(f'This file exceeds the {limit:,}-row limit.')
                if any(text(c) for c in row):
                    if len(row) != len(columns):
                        raise ValueError(f'Row {index + 2} has a different number of fields from the header.')
                    rows.append([text(c) for c in row])
    elif extension == '.jsonl':
        columns, rows = [], []
        with open(path, encoding='utf-8-sig') as handle:
            for line in handle:
                if not line.strip():
                    continue
                if len(rows) >= limit:
                    raise ValueError(f'This file exceeds the {limit:,}-row limit.')
                row = json.loads(line)
                if not isinstance(row, dict) or any(isinstance(v, (dict, list)) for v in row.values()):
                    raise ValueError('Use JSONL with one flat spreadsheet-like object per line.')
                if not columns:
                    columns = list(row)
                if set(row) != set(columns):
                    raise ValueError('Every JSONL row must contain the same column names.')
                rows.append([text(row[c]) for c in columns])
    else:
        raise ValueError('Choose an .xlsx, .csv, or .jsonl file.')
    if not columns or any(not c for c in columns) or len(set(columns)) != len(columns):
        raise ValueError('Column headers must be non-empty and unique. Correct the spreadsheet and try again.')
    if not rows:
        raise ValueError('This worksheet has no data rows.')
    return {'columns': columns, 'rows': [dict(zip(columns, row)) for row in rows], 'sheets': sheets, 'sheet': sheet}


def describe(data):
    rows, columns = data['rows'], data['columns']
    stats = []
    for name in columns:
        counts = Counter(row.get(name, '') for row in rows if row.get(name, ''))
        nonempty = sum(counts.values())
        average = sum(len(value) * n for value, n in counts.items()) / max(1, nonempty)
        stats.append({'name': name, 'missing': len(rows) - nonempty, 'unique': len(counts),
                      'examples': [value[:180] for value in list(counts)[:3]], 'average_length': round(average, 1)})
    likely_input = max(stats, key=lambda s: s['average_length'])['name']
    likely_targets = [s['name'] for s in stats if 2 <= s['unique'] <= min(100, max(3, len(rows) / 2))
                      and s['name'] != likely_input and s['average_length'] < 100]
    return {'row_count': len(rows), 'columns': stats, 'preview': rows[:8],
            'suggested_input': likely_input, 'suggested_targets': likely_targets}


def import_codebook(value):
    if not isinstance(value, dict) or not isinstance(value.get('questions'), list):
        raise ValueError('Import an Excel AI Insights codebook containing questions.')
    if not 1 <= len(value['questions']) <= 100:
        raise ValueError('A codebook must contain 1–100 questions.')
    names = [q.get('outputColumnName') for q in value['questions'] if isinstance(q, dict)]
    if len(names) != len(value['questions']) or any(not isinstance(n, str) or not n.strip() for n in names) or len(set(names)) != len(names):
        raise ValueError('Codebook questions need unique output column names.')
    return value


def compile_question(spec, max_choices=100):
    # Keep the option-key algorithm compatible with Excel AI Insights.
    for key in ('dependsOn', 'branches', 'sourceBranches', 'sourceExcerpt'):
        if spec.get(key):
            raise ValueError(f'{spec["outputColumnName"]}: staged questions need an end-to-end workflow adapter. This version supports independent questions; it will not flatten dependencies.')
    kind = spec.get('questionType', 'choice')
    instructions = spec.get('instructions')
    if kind not in ('choice', 'score', 'noul') or not isinstance(instructions, (str, dict, list)) or not instructions:
        raise ValueError('Each question needs supported instructions and a choice, score, or yes/no type.')
    options = spec.get('options') or []
    if not isinstance(options, list):
        raise ValueError('Question options must be a list.')
    labels = [o.get('label') if isinstance(o, dict) else o for o in options]
    if any(not isinstance(label, str) or not label.strip() for label in labels) or len(set(labels)) != len(labels):
        raise ValueError('Category labels must be non-empty and unique.')
    descriptions = [o.get('description', o['label']) if isinstance(o, dict) else o for o in options]
    question = {'type': kind, 'instructions': instructions}
    if kind == 'choice':
        if not 2 <= len(labels) <= max_choices:
            raise ValueError(f'Choice questions need 2–{max_choices} categories.')
        criteria, mapping = {}, {}
        for label, description in zip(labels, descriptions):
            base = re.sub(r'[^\w]+', '_', unicodedata.normalize('NFKD', label).encode('ascii', 'ignore').decode().lower()).strip('_') or 'option'
            key, suffix = base, 2
            while key in criteria:
                key, suffix = f'{base}_{suffix}', suffix + 1
            criteria[key], mapping[label] = description, key
        question['criteria'] = criteria
    elif kind == 'score':
        if not 2 <= len(labels) <= 10:
            raise ValueError('Score questions need 2–10 ordered levels.')
        question['criteria'] = descriptions
        mapping = {label: i for i, label in enumerate(labels)}
    else:
        if len(labels) not in (0, 2):
            raise ValueError('Yes/no options must be listed as yes then no.')
        labels = labels or ['Yes', 'No']
        mapping = {labels[0]: True, labels[1]: False}
        if 'criteria' in spec:
            if not isinstance(spec['criteria'], dict) or set(spec['criteria']) != {'true', 'false'}:
                raise ValueError('Yes/no criteria need true and false entries.')
            question['criteria'] = spec['criteria']
    return question, mapping


def validate_mapping(data, config, model):
    columns = data['columns']
    inputs, targets = config.get('inputs'), config.get('targets')
    if not isinstance(inputs, list) or not inputs or any(c not in columns for c in inputs):
        raise ValueError('Choose at least one input column.')
    if not isinstance(targets, list) or not targets or any(c not in columns for c in targets):
        raise ValueError('Choose at least one target column.')
    if len(set(inputs)) != len(inputs) or len(set(targets)) != len(targets) or set(inputs) & set(targets):
        raise ValueError('Inputs and targets must be distinct. Target labels cannot be model inputs.')
    for field in ('language_column', 'review_column', 'group_column', 'slice_column'):
        if config.get(field) and config[field] not in columns:
            raise ValueError('Choose an existing column for ' + field.replace('_', ' ') + '.')
    if config.get('review_mode') not in ('all_verified', 'column', 'unreviewed'):
        raise ValueError('Confirm how labels were reviewed.')
    if config['review_mode'] == 'column' and (not config.get('review_column') or not config.get('verified_values')):
        raise ValueError('Choose the review column and values that mean a person approved the labels.')
    if config.get('review_mode') == 'all_verified' and not config.get('review_confirmed'):
        raise ValueError('Confirm that your team checked the selected target labels.')
    book = config.get('codebook')
    if book:
        import_codebook(book)
    specs = {s['outputColumnName']: s for s in (book or {}).get('questions', [])}
    derived = {s.get('outputColumnName') for s in (book or {}).get('derived', [])}
    questions, mappings = {}, {}
    for target in targets:
        if target in derived:
            raise ValueError(f'{target} is derived by your codebook. Select the underlying questions instead.')
        if book and target not in specs:
            raise ValueError(f'No codebook question matches {target}. Map the target to its exact output column name.')
        spec = specs.get(target)
        if not spec:
            labels = sorted({r[target] for r in data['rows'] if r[target]})
            spec = {'outputColumnName': target, 'questionType': 'choice',
                    'instructions': (config.get('instructions') or {}).get(target) or f'Classify the input by {target}. Choose the best matching category.', 'options': labels}
        question, mapping = compile_question(spec, model.get('max_choices', 100))
        if question['type'] not in model['question_types']:
            raise ValueError(f'This model does not support {question["type"]} questions.')
        questions[target], mappings[target] = question, mapping
    return questions, mappings


def inspect(data, config, model, split_policy):
    questions, mappings = validate_mapping(data, config, model)
    targets, inputs = config['targets'], config['inputs']
    counts = Counter()
    issues, candidates = [], []
    labels = {target: Counter() for target in targets}
    languages = Counter()
    seen_labels = defaultdict(lambda: defaultdict(set))
    group_parent = {}

    def find(key):
        group_parent.setdefault(key, key)
        if group_parent[key] != key:
            group_parent[key] = find(group_parent[key])
        return group_parent[key]

    def union(a, b):
        a, b = find(a), find(b)
        group_parent[max(a, b)] = min(a, b)

    for number, row in enumerate(data['rows'], 2):
        state = {column: row[column] for column in inputs}
        key = digest({c: normalized(v) for c, v in state.items()})
        find(key)
        if config.get('group_column') and row[config['group_column']]:
            union(key, 'group:' + normalized(row[config['group_column']]))
        reason = None
        if not any(state.values()):
            reason = 'missing_input'
        elif any(not row[t] for t in targets):
            reason = 'missing_labels'
        elif any(row[t] not in mappings[t] for t in targets):
            reason = 'invalid_labels'
        verified = config['review_mode'] == 'all_verified' or (config['review_mode'] == 'column' and row[config['review_column']] in config.get('verified_values', []))
        if reason:
            counts[reason] += 1
            issues.append({'row': number, 'reason': reason})
            continue
        for target in targets:
            seen_labels[key][target].add(row[target])
        candidates.append({'row_id': number, 'state': state, 'key': key, 'verified': verified, 'source': row})
    conflicts = {key for key, targets_seen in seen_labels.items() if any(len(values) > 1 for values in targets_seen.values())}
    counts['conflict_groups'] = len(conflicts)
    partitions = {key: [] for key in ('train', 'validation', 'calibration', 'test')}
    unique = set()
    # Prefer the human-verified copy of an otherwise identical record.
    candidates.sort(key=lambda c: (not c['verified'], c['row_id']))
    train_fraction = config.get('train_fraction', 0.8)
    if isinstance(train_fraction, bool) or not isinstance(train_fraction, (float, int)) or not 0.5 <= train_fraction <= 0.95:
        raise ValueError('Training share must be between 50% and 95%.')
    for candidate in candidates:
        row, key = candidate['source'], candidate['key']
        reason = 'label_conflict' if key in conflicts else 'duplicate' if key in unique else None
        if reason:
            counts[reason] += 1
            issues.append({'row': candidate['row_id'], 'reason': reason})
            continue
        unique.add(key)
        seed = split_policy['split_seed']
        bucket = int(digest([seed, find(key)])[:12], 16) / 16**12
        test_end = split_policy['test_fraction']
        calibration_end = test_end + (1 - test_end) * split_policy['calibration_fraction']
        validation_end = calibration_end + (1 - calibration_end) * (1 - train_fraction)
        partition = 'test' if bucket < test_end else 'calibration' if bucket < calibration_end else 'validation' if bucket < validation_end else 'train'
        if not candidate['verified'] and (not config.get('include_unverified') or partition != 'train'):
            counts['unreviewed'] += 1
            issues.append({'row': candidate['row_id'], 'reason': 'unreviewed'})
            continue
        language = row.get(config.get('language_column'), '') or 'Unknown'
        languages[language] += 1
        for target in targets:
            labels[target][row[target]] += 1
        decision = {'row_id': candidate['row_id'], 'state': candidate['state'], 'questions': questions,
                    'expected': {t: mappings[t][row[t]] for t in targets}, 'language': language,
                    'slices': {config['slice_column']: row[config['slice_column']]} if config.get('slice_column') else {},
                    'provenance': 'human_validated' if candidate['verified'] else 'unverified', 'group': find(key)}
        partitions[partition].append(decision)
    eligible = sum(len(rows) for rows in partitions.values())
    warnings = []
    if not config.get('language_column'):
        warnings.append('Language evaluation is Unknown until you map a language column. Automatic language suggestions are not verified labels.')
    if not config.get('group_column'):
        warnings.append('Exact normalized duplicates are grouped. Map a source/group ID to also keep related feedback together; paraphrases are not automatically detected.')
    if not config.get('codebook'):
        warnings.append('Categories were inferred from this file. Confirm their meaning and instructions before creating an experiment.')
    for target in targets:
        train_labels = {r['expected'][target] for r in partitions['train']}
        unseen = {r['expected'][target] for part in ('validation', 'calibration', 'test') for r in partitions[part]} - train_labels
        if unseen:
            warnings.append(f'{target}: {len(unseen)} held-out categories have no training examples.')
    return {'total': len(data['rows']), 'eligible': eligible, 'excluded': len(data['rows']) - eligible,
            'counts': dict(counts), 'issues': issues, 'languages': dict(languages),
            'labels': {k: dict(v) for k, v in labels.items()}, 'warnings': warnings,
            'split_counts': {key: len(rows) for key, rows in partitions.items()},
            'questions': questions, 'label_mappings': mappings, 'partitions': partitions}


def save_partitions(directory, report):
    for name, rows in report['partitions'].items():
        path = Path(directory) / (name + '.jsonl')
        with path.open('w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    public = {key: value for key, value in report.items() if key != 'partitions'}
    write_json(Path(directory) / 'quality.json', public)
    return public


def read_decisions(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def language_suggestions(data, column, limit=200):
    if column not in data['columns']:
        raise ValueError('Choose an input column first.')
    try:
        from langdetect import DetectorFactory, detect
    except ImportError:
        return {'available': False, 'message': 'Language suggestions need langdetect. Run npm run setup.'}
    DetectorFactory.seed = 0
    counts = Counter()
    for row in data['rows'][:limit]:
        try:
            language = detect(row[column]) if len(row[column]) >= 20 else 'uncertain'
        except Exception:
            language = 'uncertain'
        counts[language] += 1
    return {'available': True, 'sample_size': min(limit, len(data['rows'])), 'counts': dict(counts),
            'message': 'Suggestions from the first rows only. Lingala is not supported by this detector and may be misidentified. Map a verified language column for evaluation.'}

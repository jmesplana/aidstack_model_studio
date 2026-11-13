import gc
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from studio.models.base import ModelAdapter
from studio.models.registry import manifest
from studio.store import write_json


def release():
    import torch
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def check_lengths(tokenizer, decisions, settings):
    from laya.common import serialize_state, encode_text
    budget = settings['max_len'] - settings['head_max_len'] - 8
    if budget < 32:
        raise ValueError('Input token budget must leave room beyond the question token budget.')
    for row in decisions:
        text = serialize_state(row['state']).replace(tokenizer.mask_token, ' ')
        if len(encode_text(tokenizer, text, add_special_tokens=False)['input_ids']) > budget:
            raise ValueError(f"Row {row['row_id']} exceeds the available input budget. Shorten the input or increase the token budget; this run will not silently truncate it.")


class LayaAdapter(ModelAdapter):
    def train(self, training, calibration, output, settings, progress):
        import laya
        import torch
        from laya.train import (TrainConfig, load_checkpoint, resolve_checkpoint_dir, items_from_rows, resolve_device,
                                train_model, calibration_records, calibration_report, save_checkpoint)
        from laya.common import uses_parallel_layout
        from laya.calibrate import fit_temperature_map
        if laya.__version__ != manifest('laya')['version']:
            raise ValueError('The installed Laya version differs from this module. Run npm run setup:model -- laya in Model Studio.')
        device = resolve_device(settings['device'])
        progress('loading', f'Loading the starting checkpoint on {device}.')
        resolved_base = resolve_checkpoint_dir(settings['base_checkpoint'])
        model, tokenizer, config = load_checkpoint(resolved_base)
        model.to(device)
        check_lengths(tokenizer, training + calibration, settings)
        max_len, head_max_len = settings['max_len'], settings['head_max_len']
        items, skipped = items_from_rows(tokenizer, training, max_len, head_max_len)
        calibration_items, calibration_skipped = items_from_rows(tokenizer, calibration, max_len, head_max_len)
        if skipped or calibration_skipped:
            raise ValueError(f'Tokenization rejected decisions: training={skipped}, calibration={calibration_skipped}. Adjust question budgets or labels before retrying.')
        config_fields = ('epochs', 'micro_batch', 'grad_accum', 'freeze_encoder', 'loss', 'encoder_lr', 'head_lr', 'max_len', 'head_max_len', 'seed')
        train_config = TrainConfig(**{key: settings[key] for key in config_fields}, calib_max=0,
                                   calib_frac=0, gradient_checkpointing=not settings['freeze_encoder'], log_every=10)
        train_config.validate()
        parallel = uses_parallel_layout(config)
        progress('training', f'Training on {len(items):,} decisions; {len(calibration_items):,} separate calibration decisions.')

        def on_epoch(epoch, loss):
            progress('training', f'Training pass {epoch + 1}/{settings["epochs"]} complete. Loss {loss:.4f}.', epoch=epoch + 1, loss=loss)

        history = train_model(model, tokenizer, items, train_config, device, max_len, head_max_len,
                              on_epoch_end=on_epoch, parallel=parallel)
        progress('calibrating', 'Calibrating confidence on separate human-validated examples.')
        records = calibration_records(model, tokenizer, calibration_items, device, max_len, head_max_len,
                                      batch_size=settings['micro_batch'], parallel=parallel)
        fitted = fit_temperature_map(records)
        calibration_result = calibration_report(records, fitted['temperature'])
        output_config = dict(config, max_len=max_len, head_max_len=head_max_len, fine_tuned=True, temperature=fitted['temperature'])
        # Inherited bucket and non-parametric calibration must never mask this fit.
        for key in ('temperature_by_options', 'binning_map', 'abstention_thresholds'):
            output_config.pop(key, None)
        if fitted['temperature_by_options']:
            output_config['temperature_by_options'] = fitted['temperature_by_options']
        output_config['training'] = {'model_studio': {'settings': asdict(train_config), 'calibration': calibration_result}}
        save_checkpoint(model, tokenizer, output_config, str(output))
        write_json(Path(output) / 'questions.json', training[0]['questions'])
        metadata = {'library': laya.__version__, 'device': str(device), 'epoch_loss': history, 'resolved_base_checkpoint': resolved_base,
                    'training_decisions': len(items), 'calibration_decisions': len(calibration_items), 'calibration': calibration_result}
        del model, tokenizer, items, calibration_items, records
        release()
        return metadata

    def load(self, checkpoint, settings):
        import laya
        from laya.train import resolve_device
        return laya.load(str(checkpoint), device=str(resolve_device(settings['device'])))

    def predict(self, runtime, state, questions):
        # Match Excel AI Insights: one question per call, in its original order.
        answers = {}
        for name, question in questions.items():
            answers.update(runtime.predict(state, {name: question})['answers'])
        return {'answers': answers, 'model': 'model-studio:laya'}

    def evaluate(self, checkpoint, decisions, settings, progress):
        # Validate token budgets before evaluation as well as training.
        # The inference runtime is released between baseline and candidate to fit unified memory.
        runtime = self.load(checkpoint, settings)
        check_lengths(runtime.tok, decisions, {'max_len': runtime.cfg.get('max_len', 512), 'head_max_len': runtime.cfg.get('head_max_len', 192)})
        predictions = []
        start = time.perf_counter()
        for index, row in enumerate(decisions):
            result = self.predict(runtime, row['state'], row['questions'])
            for name, question in row['questions'].items():
                answer = result['answers'][name]
                kind = question['type']
                if kind == 'choice':
                    predicted = answer['choice']
                    confidence = answer['probabilities'][predicted]
                elif kind == 'noul':
                    predicted = answer['noul'] >= 0.5
                    confidence = answer['noul'] if predicted else 1 - answer['noul']
                else:
                    predicted = max(0, min(len(question['criteria']) - 1, int(float(answer['score']) + 0.5)))
                    confidence = answer['probabilities'][str(predicted)]
                confidence = float(confidence)
                if not 0 <= confidence <= 1:
                    raise ValueError('Laya returned invalid probabilities.')
                predictions.append({'row_id': row['row_id'], 'question': name, 'expected': row['expected'][name],
                                    'predicted': predicted, 'confidence': confidence, 'language': row['language'], 'slices': row['slices']})
            if index % 10 == 0:
                progress('evaluating', f'Evaluated {index + 1:,}/{len(decisions):,} rows.')
        elapsed = time.perf_counter() - start
        del runtime
        release()
        return predictions, elapsed

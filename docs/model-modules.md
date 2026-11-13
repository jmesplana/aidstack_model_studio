# Adding a model module

Model Studio owns the dataset, review provenance, grouped partitions, experiment lifecycle, metrics, and approval. A model module owns model-specific preparation, training, calibration, and inference.

Add a directory under `studio/models/<module_id>/` containing:

```text
__init__.py
manifest.json
requirements.txt
adapter.py
```

Module IDs must use lowercase letters, numbers, and underscores. The manifest is discovered by the registry; no frontend switch statement is needed. Only trusted code installed by the developer can become a module. Uploaded files never specify Python imports or commands.

Example manifest:

```json
{
  "id": "my_classifier",
  "name": "My classifier",
  "version": "1.0.0",
  "description": "A classification model for reviewed text.",
  "entrypoint": "studio.models.my_classifier.adapter:ClassifierAdapter",
  "question_types": ["choice"],
  "max_choices": 100,
  "settings": [
    {"key":"base_checkpoint","label":"Starting checkpoint","type":"text","default":"my-model"},
    {"key":"epochs","label":"Training passes","type":"integer","default":4,"min":1,"max":50},
    {"key":"device","label":"Compute device","type":"select","default":"auto","options":["auto","cpu"]}
  ]
}
```

All modules must declare `base_checkpoint`; the shared orchestration uses it as the baseline until that module has an approved release. Other fields are model-specific. Field types are `text`, `integer`, `number`, `select`, and `boolean`; use `advanced: true` to collapse technical options. Optional `help`, `min`, `max`, and `options` are used by the form and server validation.

Use `-r ../../../requirements.txt` in the module requirements to include shared worker/server dependencies. Add pinned model dependencies after it. The generic installer creates `.venv-<module_id>`:

```sh
npm run setup:model -- my_classifier
```

Implement `studio.models.base.ModelAdapter`:

- `train(training, calibration, output, settings, progress)` trains using only the supplied training decisions and calibrates only on the separate calibration group. Save the candidate inside `output`. Return serializable metadata, calibration warnings, and optionally `resolved_base_checkpoint` so subsequent baseline evaluation uses the exact resolved model location.
- `evaluate(checkpoint, decisions, settings, progress)` loads the requested model, predicts each decision using only its state/question, and returns `(predictions, elapsed_seconds)`. It must not train or calibrate. Return exactly one prediction per question. Expected labels are included for metrics only and must never influence predictions.
- `load(checkpoint, settings)` returns the inference runtime for a saved checkpoint.
- `predict(runtime, state, questions)` returns the shared System One response envelope (`answers`, optional `model`/`usage`). For a model with a different native format, translate here.

The worker only imports a module inside its own environment. The app server discovers manifests without loading PyTorch or any model library. Progress callbacks are durable updates to the experiment record. A callback also notices cancellation/interruption.

## Provider-neutral data contract

```json
{
  "row_id": 12,
  "state": {"feedback": "Please share clinic opening hours."},
  "questions": {
    "category": {
      "type": "choice",
      "instructions": "Choose the main feedback type.",
      "criteria": {"request": "A request for help or information", "praise": "An expression of appreciation"}
    }
  },
  "expected": {"category": "request"},
  "language": "en",
  "slices": {"criticality": "Routine"},
  "provenance": "human_validated",
  "group": "stable-group-id"
}
```

Choice targets are criterion keys, score targets are zero-based ordered indices, and yes/no targets are booleans. Original labels and their mappings are preserved in the quality report. The shared compiler deliberately limits scope to independent decision questions. Richer staged tasks need a shared workflow representation and end-to-end evaluation that uses predicted upstream answers, rather than leaking gold parent labels into child questions.

Return predictions in this shape:

```json
{
  "row_id": 12,
  "question": "category",
  "expected": "request",
  "predicted": "request",
  "confidence": 0.86,
  "language": "en",
  "slices": {"criticality": "Routine"}
}
```

Confidence is the probability assigned to the selected class, not an entropy-based confidence statistic. Shared metrics derive accuracy, per-class precision/recall/F1, macro F1, calibration error, and cohort summaries. Preserve row/question keys and score every supplied decision, or fail explicitly; never silently skip difficult evaluation rows.

## Isolation and lifecycle

Modules must not modify the starting checkpoint, source dataset, split assignments, global registry, or production services. They must not upload source examples or execute user-supplied commands. Checkpoint downloads are permitted as a separately documented operation; expose an offline option where applicable.

Training is `draft → running → trained`; final testing is `trained → running → evaluated`. Only a passing final comparison can be explicitly approved. Failed, interrupted, or cancelled jobs need a new experiment. The shared inference service loads a snapshot of the approved release on startup; approval/rollback does not hot-swap it during requests.

Add model-specific tests for preprocessing, label encoding, checkpoint reload, full evaluation coverage, and calibration persistence. Use a small real training round-trip before trusting a new module. The shared worker test uses an unrelated synthetic adapter to verify that orchestration does not import Laya.

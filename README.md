# Aidstack Model Studio

A local application for preparing reviewed classification datasets, training a separate candidate model, and evaluating it before human approval. The initial model module supports Laya; model settings and execution are separated from the shared application.

## Run

Requires Node.js 18+ and Python 3.10+ (Python 3.11 or 3.12 recommended).

```sh
npm run dev
```

Open **http://127.0.0.1:8090**. The launcher creates `.venv`, installs the app's Python dependencies when requirements change, and starts the local server. No `npm install` is necessary for the application: the Node launcher has no external dependencies. The first setup needs internet.

`npm run start` starts the same local server. It deliberately does not use a debug reloader, because reloading during training can interrupt a job. Restart after source changes.

## Train with Laya

Install the optional model environment separately:

```sh
npm run setup:model -- laya
```

This creates `.venv-laya` with the adapter's pinned Laya version. It does not modify Excel AI Insights' Laya environment. Model weights are downloaded on the first uncached run. Choose a cached checkpoint and **Use cached models only** for offline execution.

1. Upload an Excel `.xlsx`, CSV, or flat JSONL file. Choose the worksheet for multi-sheet workbooks.
2. Optionally import the codebook exported by Excel AI Insights. Choose original input columns and final, team-approved target columns.
3. Confirm that the team reviewed the selected labels, or map a review-status column. Map language and related-record IDs where available.
4. Inspect missing labels, invalid categories, duplicates, conflicts, and split counts. Without a codebook, confirm the inferred categories and edit their instructions.
5. Configure the model and save a draft experiment. Choose **Start training** to run it.
6. Review the validation comparison, then explicitly open the final test set. Approve only after the acceptance rules pass and you have inspected the relevant slices.

For an Apple Silicon Mac with 32 GB unified memory, begin with a representative subset and the default **decision-head-only** training. Auto selects MPS when available. Full encoder fine-tuning is configurable but needs more memory and a measured trial; no training duration or maximum dataset size is guaranteed. The application can ingest 75,000 rows, but this does not establish that an entire fine-tuning run fits your device.

The initial adapter uses Laya **0.4.31**, whereas the reviewed Excel AI Insights integration pinned **0.3.21**. Separate environments keep that installation untouched. This adapter is implemented against upstream's training API; a live model training run still needs verification on the target Mac.

## Use an approved model in Excel AI Insights

Approval changes the Model Studio registry only. It does not replace your existing Laya process or start inference automatically.

Start a separate server from Model Studio:

```sh
npm run serve:model
```

It snapshots the approved release at startup and serves `/v1/systemone` on **127.0.0.1:8002**. Restart it explicitly after approval or rollback. With more than one model family approved, select one with `STUDIO_MODEL_MODULE`.

Then, from your **Excel AI Insights checkout**, run its existing browser connector against this service:

```sh
LAYA_BASE_URL=http://127.0.0.1:8002 \
LAYA_BRIDGE_PORT=8003 \
LAYA_ALLOWED_ORIGINS=https://YOUR-EXCEL-INSIGHTS-SITE.vercel.app \
venv/bin/python local_laya_bridge.py
```

Use your actual website origin. The connector also permits the local app's default origins. In Excel AI Insights, select **Laya · local**, use the connector address **http://127.0.0.1:8003**, and test the connection. Keep the same codebook used in the experiment. Port 8003 leaves the original port-8001 connector untouched. The inference server supplies the approved checkpoint regardless of the legacy built-in model name in the request; the returned `checkpoint_id` identifies the actual release. Do not run the existing `npm run laya` launcher for this connection, as that launcher starts the original model service as well.

The default connector compatibility is for Laya. New model modules can implement the same System One answer contract; integrating other protocols requires an adapter in the consuming app. This connection has not yet been exercised against a live trained checkpoint here.

## Data handling and evaluation

- All imports, normalized data, split files, logs, and checkpoints are stored under `.studio/`, ignored by Git. Source text is not sent to a cloud provider.
- Downloads of model weights are separate from data processing. Setup, initial uncached models, and dependency installation need network access.
- Human review is an explicit assertion or an exact match against a chosen status column. Model confidence is never treated as evidence of human review.
- Optional unreviewed labels enter **training only**. Calibration, validation, and testing always require human-validated labels.
- Blank inputs, missing/invalid targets, and conflicting normalized duplicates are excluded. Identical normalized inputs are deduplicated. A group column keeps related records together through a union of record and source groups.
- The default split reserves 10% for final testing, then 10% of the remainder for calibration. The remaining records use an 80/20 training/validation split. Hash-based group assignment makes counts approximate. Test and calibration reservations are frozen when a dataset is imported; the training/validation ratio is configurable per experiment.
- Model-generated and corrected labels are not used as input unless explicitly selected; direct input/target overlap is blocked. Users must still review other columns for indirect leakage.
- The test set is stable for a given import, mapping, and grouping. Changing grouping, reimporting with different preferences, or comparing across independent datasets can invalidate cross-experiment comparability. This release does not maintain a global cross-dataset holdout registry.
- Validation and final testing evaluate both baseline and candidate on identical records. Accuracy, macro F1, per-class precision/recall, confusion counts, calibration error, language/column breakdowns, and local inference timing are reported. Electricity, hardware cost, and statistical uncertainty are not estimated.
- Defaults are configurable under **Settings**. Acceptance rules are copied into the experiment at creation. Approval requires an accuracy gain, no macro-F1 reduction, sufficient test decisions, and no regression beyond the configured tolerance in sufficiently large slices. Rare slices still require human inspection.
- Repeatedly tuning against the final test set can overfit it even when the model never trains directly on it. Use validation for experiments and reserve an additional fresh audit dataset for mature releases.
- Files are not encrypted by the application. Use FileVault/device encryption, appropriate access permissions, and backups for humanitarian or personal data. The launcher/app bind to loopback only; this is not a multi-user hosted service.

## Current boundaries

- Independent Choice, Score, and Yes/No questions are supported. Selected staged dependencies, source branches, source-excerpt extraction, and derived target columns are blocked with an explicit error. Training and end-to-end evaluation for those workflows need a workflow adapter; they are not flattened into misleading independent tasks.
- Unlabelled uploads support column inspection; they cannot create supervised training jobs until labels are reviewed. Active learning and an in-app human correction queue are not included yet.
- Language suggestions inspect a sample and are advisory. The bundled detector does **not** support Lingala; map a verified language column for meaningful multilingual evaluation.
- The experiment objective is a reviewer note. It is not an AI configuration interpreter; only confirmed fields and coding instructions determine training.
- One training/evaluation job runs at a time in one app instance. Failed/cancelled/interrupted runs cannot be promoted and do not resume. Create a new experiment to retry. Run only one app instance per workspace.
- UI form changes are kept in memory until an experiment is saved. Refreshing the wizard discards the unsaved mapping; uploaded datasets remain available.

## Commands and configuration

| Command | Purpose |
| --- | --- |
| `npm run dev` | Install app dependencies if needed, then run locally |
| `npm start` | Run the same local app without a debug reloader |
| `npm run setup` | Install only the app dependencies |
| `npm run setup:model -- laya` | Install the isolated model module |
| `npm run serve:model` | Explicitly serve an approved release |
| `npm test` | Run ingestion, splitting, approval, metrics, and module-boundary tests |

| Environment variable | Purpose |
| --- | --- |
| `PORT` | App port, default 8090 |
| `STUDIO_PYTHON` | Python executable used to create virtual environments |
| `STUDIO_APP_PYTHON` | Use an existing app interpreter instead of automatic setup |
| `STUDIO_DATA_DIR` | Local data/checkpoint directory |
| `STUDIO_MODEL_PYTHON_<MODULE_ID>` | Override a model module's Python interpreter |
| `STUDIO_MAX_UPLOAD_MB` | Upload size limit, default 100 MB |
| `STUDIO_MAX_ROWS` | Import row limit, default 200,000 |
| `STUDIO_INFERENCE_PORT` | Approved inference server port, default 8002 |
| `STUDIO_MODEL_MODULE` | Module to serve when several families are approved |

`--python /absolute/path/to/python` can also be passed to `npm run dev` or `npm test` to reuse an existing app environment. It must contain the requirements. Setup failures do not write a success stamp, so the next launch retries.

## Architecture

```text
static/js/          Modular interface and schema-generated model settings
studio/app.py       Local API and approval actions
studio/datasets.py  Ingestion, codebook normalization, quality checks, data splits
studio/store.py     SQLite metadata and local artifact storage
studio/jobs.py      Isolated worker process lifecycle
studio/worker.py    Model-independent train/evaluate orchestration
studio/metrics.py   Shared metrics and acceptance rules
studio/serve.py     Explicit approved-checkpoint inference service
studio/models/     Model manifests and adapter implementations
tests/             Functional tests with synthetic fixtures; no training claims
```

See [the model module guide](docs/model-modules.md) for adding another model. No frontend edits are required to expose a module's settings.

## Verification in the development workspace

Verification passed: **22 Python functional tests and 3 JavaScript rendering/extension tests**, plus JavaScript syntax checks. A **75,000-record synthetic `.xlsx`** was generated, imported, profiled, and partitioned successfully (41.3 seconds for the combined operations in this development environment). It produced 48,443 training, 12,138 validation, 6,775 calibration, and 7,644 test records, with no exclusions.

The tests use synthetic data and a test adapter. They cover real spreadsheet ingestion, split/provenance rules, API behavior, metrics, atomic approval/audit updates, model-independent worker orchestration, schema-driven model controls, and escaping of uploaded text. These checks do not demonstrate Laya accuracy, training compatibility on MPS, browser rendering, or training throughput on 75,000 rows.

This workspace blocks network dependency installation and localhost sockets; tests use an existing Python environment. Browser rendering, a live preview, and a real Laya training/inference run could not be verified here. Run the normal setup and a small training experiment on the target Mac before using real release results.

Brand fonts are bundled locally with licenses in `static/licenses/`; the app requires no external frontend CDN.

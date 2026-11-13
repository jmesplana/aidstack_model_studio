import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get('STUDIO_DATA_DIR', ROOT / '.studio')).expanduser().resolve()
PORT = int(os.environ.get('PORT', '8090'))
DEFAULTS = {
    'test_fraction': 0.1,
    'calibration_fraction': 0.1,
    'train_fraction': 0.8,
    'split_seed': 'aidstack-split-v1',
    'max_upload_mb': int(os.environ.get('STUDIO_MAX_UPLOAD_MB', '100')),
    'max_rows': int(os.environ.get('STUDIO_MAX_ROWS', '200000')),
    'min_test_decisions': 30,
    'min_accuracy_gain': 0.0,
    'max_slice_regression': 0.02,
    'min_slice_size': 20,
}

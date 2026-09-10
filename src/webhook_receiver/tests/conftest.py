"""Bootstrap sys.path so ``webhook_receiver`` resolves without installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sys
from pathlib import Path

# Tasks are resolved by import path, so the sample task module must be importable by name.
sys.path.insert(0, str(Path(__file__).parent))

"""Put the backend directory on sys.path so tests can `import db`, `seed`, `main`
as top-level modules (matching how they are run: from within backend/)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

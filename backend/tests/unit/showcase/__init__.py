"""Unit tests for the showcase tool's pure parts (#1066).

The tool lives in ``tests/acceptance/showcase`` and is imported as
``showcase``; this package puts ``tests/acceptance`` on ``sys.path`` before any
test module in it is imported. Nothing here needs a browser, ffmpeg, Docker
or a database, so the CI unit job runs it.
"""

import sys
from pathlib import Path

ACCEPTANCE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "acceptance"
if str(ACCEPTANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(ACCEPTANCE_ROOT))

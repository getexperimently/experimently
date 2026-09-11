"""Make ``experimentation_openfeature`` (src/) and the ``experimentation`` SDK (sdk/python)
importable from the source tree without installing either package."""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _path in (_HERE.parents[1] / "src", _HERE.parents[2] / "python"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

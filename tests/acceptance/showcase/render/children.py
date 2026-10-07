"""The environment every program the render starts gets: an allow-list, built fresh.

ffmpeg, ffprobe, tesseract, swiftc, the Vision reader and Chromium need a
search path, a home and a temporary directory, and nothing from the caller's
shell: not a cloud profile, not a token, not a database address. So each of
them gets only the variables named here, copied from the render's own
environment when they are set (EM condition 10; the capture keeps its own
list for the stack it starts).
"""

from __future__ import annotations

import os
from typing import Dict

CHILD_ENV_KEYS = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "DEVELOPER_DIR",
    "SDKROOT",
    "TESSDATA_PREFIX",
)


def child_env() -> Dict[str, str]:
    return {key: os.environ[key] for key in CHILD_ENV_KEYS if key in os.environ}

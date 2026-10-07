"""``python -m showcase.capture <slug|all>`` from ``tests/acceptance`` (``make showcase``)."""

from __future__ import annotations

import sys

from showcase.capture.run import main

sys.exit(main())

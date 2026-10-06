"""The oracles a journey's ``expect.number`` may name.

An oracle computes, independently of the product, the number a screen must
show: ``ORACLES[name](**args)``. The loader refuses a journey naming one that is
not here. None is registered yet; the power-calculator journey adds the first
(a two-proportion sample size from scipy).
"""

from __future__ import annotations

from typing import Callable, Dict

ORACLES: Dict[str, Callable[..., float]] = {}

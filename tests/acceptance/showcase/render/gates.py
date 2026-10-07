"""How a render gate reports: its numbers when it passes, a refusal when it does not.

The gate names follow the approved plan (#1066): the QA gate numbers (1, 2,
3, 4, 5, 7, 11, 17) and U4, plus ``disk`` (the 4 GiB floor) and ``capture``
(the capture directory itself). A refusal names its gate, and its text says
what was measured and what was required, never a value from needles.txt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


class Refused(Exception):
    """A render gate failed. Nothing the render made survives a refusal."""

    def __init__(self, gate: str, problems: List[str] | str) -> None:
        self.gate = gate
        self.problems = [problems] if isinstance(problems, str) else list(problems)
        body = (
            self.problems[0]
            if len(self.problems) == 1
            else "\n" + "\n".join(f"- {p}" for p in self.problems)
        )
        super().__init__(f"gate {gate} refused: {body}")


@dataclass
class GateLog:
    """Every gate's numbers, in the order the gates ran, for the review page."""

    gates: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def passed(self, gate: str, numbers: Dict[str, Any]) -> None:
        self.gates[gate] = {"ok": True, "numbers": numbers}

    def require(self, gate: str, problems: List[str], numbers: Dict[str, Any]) -> None:
        """Record the gate, then refuse if it found anything."""
        if problems:
            self.gates[gate] = {"ok": False, "numbers": numbers}
            raise Refused(gate, problems)
        self.passed(gate, numbers)

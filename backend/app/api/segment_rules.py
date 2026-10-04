"""
The write-time segment check for the routes that store targeting rules (#440).

Every segment a flag's or an experiment's rules name must exist, be active,
and, for a rules segment, have stored rules that are valid
(:func:`backend.app.services.segment_membership.segment_reference_problem`).
The pure checks (attribute ``segment``, a segment id, at most 10 segments, no
segment condition in a native ``default_rule``) run earlier, in the request
schemas.
"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.services.segment_membership import segment_reference_problem


def refuse_unusable_segments(db: Session, raw_rules: Any) -> None:
    """422 at ``["body", "targeting_rules"]`` when a named segment cannot be used.

    The message names the condition and the reason, never the submitted value.
    """
    problem = segment_reference_problem(db, raw_rules)
    if problem is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "loc": ["body", "targeting_rules"],
                    "msg": problem,
                    "type": "value_error",
                }
            ],
        )


def refuse_clone_with_unusable_segments(db: Session, raw_rules: Any) -> None:
    """409 when the rules a clone would copy name a segment that cannot be used."""
    problem = segment_reference_problem(db, raw_rules)
    if problem is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The experiment cannot be cloned: its targeting rules use a segment "
                f"that is not active or whose rules are not valid ({problem}). "
                "Create the experiment again with rules that use active segments."
            ),
        )

"""
Edition endpoint -- ``GET /api/v1/edition``.

Unauthenticated on purpose: it drives the dashboard's chrome (edition pill,
grace/expired banner, which nav groups render) and the browser has to be able
to ask before anyone has logged in.

Because it is public it exposes only what the chrome needs.  It never returns
the customer name, the plan, the seat count or any part of the licence key --
a probe learns that *an* enterprise licence exists and which feature names it
covers, and nothing about who owns it.
"""

from datetime import datetime
from typing import List, Literal, Optional, cast

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.app.core.config import settings
from backend.app.core.license import current_license_state, schedule_audit

router = APIRouter()


class EditionResponse(BaseModel):
    """What the dashboard needs to decide what to render."""

    edition: Literal["ce", "enterprise"] = Field(
        ..., description="'enterprise' once a licence is present, even if lapsed"
    )
    features: List[str] = Field(
        default_factory=list,
        description=(
            "Feature names the licence covers. Empty in CE and for an invalid "
            "licence. Non-empty while 'expired' -- read 'status' as well "
            "before enabling a feature."
        ),
    )
    status: Literal["none", "active", "grace", "expired", "invalid"]
    expires_at: Optional[datetime] = None
    version: str


@router.get(
    "/edition",
    response_model=EditionResponse,
    summary="Edition and licence status",
    # No `tags=` here: api.py already includes this router under ["Edition"],
    # and FastAPI concatenates the two, so the OpenAPI operation listed the tag
    # twice and the docs page rendered a duplicate group.
)
async def get_edition() -> EditionResponse:
    """Report the running edition and licence status.

    Community Edition (no ``EXPERIMENTLY_LICENSE_KEY``) answers::

        {"edition": "ce", "features": [], "status": "none",
         "expires_at": null, "version": "..."}
    """
    state = current_license_state()
    # A state change seen here is a real transition (first request after a
    # restart, a key that just lapsed); record it once, in the background --
    # the answer does not depend on the write, and the dashboard's probe must
    # not wait out a database connect timeout to learn the edition.
    schedule_audit(state)

    return EditionResponse(
        # `LicenseState.edition` returns exactly "ce" or "enterprise"; the
        # cast tells mypy what the property's `-> str` cannot.
        edition=cast(Literal["ce", "enterprise"], state.edition),
        features=list(state.features) if state.is_enterprise else [],
        status=cast(
            Literal["none", "active", "grace", "expired", "invalid"],
            state.status.value,
        ),
        expires_at=state.expires_at,
        version=settings.VERSION,
    )

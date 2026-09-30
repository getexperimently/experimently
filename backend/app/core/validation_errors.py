"""The 422 body for a request that fails validation (#500).

FastAPI's default handler returns each error with its ``input``: the value
that was rejected, and for a missing field or a body of the wrong type, the
whole body. A 422 then repeats everything the client submitted, including the
fields that were valid. This handler keeps each error's ``type``, ``loc``,
``msg`` and ``ctx`` and leaves ``input`` out. ``input`` is optional in the
published ``ValidationError`` schema (its required fields are ``loc``, ``msg``
and ``type``), so the documented shape, ``{"detail": [...]}``, is unchanged.

The body is rendered as ASCII-escaped JSON. Any of the kept fields can carry
text from the request -- ``loc`` names a key of a submitted object, ``msg``
and ``ctx`` can carry a validator's message -- and a lone surrogate in a
Python ``str`` cannot be encoded as UTF-8. Starlette's ``JSONResponse``
encodes to UTF-8, so the default handler answered such a request with a 500.
``ensure_ascii=True`` writes it as a ``\\udXXX`` escape instead, which is valid
JSON. If the kept fields cannot be encoded at all (a ``ctx`` value that is not
JSON-serialisable, a NaN), the body falls back to ``type``, ``loc`` and
``msg`` as plain text. The status is 422 in every case.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Sequence

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import Response

#: The fields of each error the response keeps. ``input`` is not one of them.
KEPT_FIELDS: Sequence[str] = ("type", "loc", "msg", "ctx")


def _text(value: Any) -> str:
    """``str(value)``, or an empty string when even that fails."""
    try:
        return value if isinstance(value, str) else str(value)
    except Exception:
        return ""


def _loc(error: Mapping) -> List[Any]:
    loc = error.get("loc", ())
    if isinstance(loc, (str, bytes)) or not isinstance(loc, Iterable):
        return [loc]
    return list(loc)


def _dumps(content: Any) -> bytes:
    return json.dumps(
        content, ensure_ascii=True, allow_nan=False, separators=(",", ":")
    ).encode("ascii")


def render_validation_errors(
    errors: Iterable[Any], fields: Sequence[str] = KEPT_FIELDS
) -> bytes:
    """The JSON body ``{"detail": [...]}`` for *errors*, with only *fields*.

    Always returns ASCII bytes; never raises for anything a validator puts in
    an error.
    """
    kept: List[Dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, Mapping):
            error = {"type": "value_error", "loc": [], "msg": _text(error)}
        item: Dict[str, Any] = {}
        for field in fields:
            if field == "loc":
                item["loc"] = _loc(error)
            elif field in error:
                item[field] = error[field]
        kept.append(item)
    try:
        return _dumps({"detail": jsonable_encoder(kept)})
    except Exception:
        # Plain text only: every value is a str or a list of str, which
        # json.dumps with ensure_ascii cannot fail on.
        plain = [
            {
                name: (
                    [_text(part) for part in item.get("loc", [])]
                    if name == "loc"
                    else _text(item.get(name, ""))
                )
                for name in fields
                if name != "ctx"
            }
            for item in kept
        ]
        return _dumps({"detail": plain})


def validation_error_response(
    errors: Iterable[Any], fields: Sequence[str] = KEPT_FIELDS
) -> Response:
    """A 422 whose body is :func:`render_validation_errors` of *errors*."""
    return Response(
        content=render_validation_errors(errors, fields),
        status_code=422,
        media_type="application/json",
    )


async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """The application's handler for :class:`RequestValidationError`."""
    return validation_error_response(exc.errors())

"""The application's handler for request validation errors (#500).

Driven through ``app.exception_handlers[RequestValidationError]``: whatever
handler the application has registered. With the registration removed, that
is FastAPI's default, which keeps ``input`` and renders UTF-8 -- so these
tests fail on it.
"""

from __future__ import annotations

import json
import math

import pytest
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from backend.app.core.validation_errors import render_validation_errors
from backend.app.main import app

pytestmark = [pytest.mark.unit, pytest.mark.regression]

SUBMITTED = "Vx7-q2Lr-9mTz-probe500"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "query_string": b"",
        }
    )


async def _handle(errors):
    handler = app.exception_handlers[RequestValidationError]
    return await handler(_request(), RequestValidationError(errors))


@pytest.mark.asyncio
async def test_lone_surrogates_in_loc_msg_and_ctx_are_a_422():
    """``loc`` can name a submitted key; ``msg`` and ``ctx`` can carry a
    validator's text. A lone surrogate in any of them cannot be encoded as
    UTF-8; the default handler raised doing so, which is a 500."""
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "attributes", "k\ud800"),
            "msg": "Value error, bad \udfff",
            "input": SUBMITTED,
            "ctx": {"error": "raised \ud83d here", "limit": 3},
        }
    ]
    response = await _handle(errors)
    assert response.status_code == 422
    assert response.media_type == "application/json"
    raw = bytes(response.body)
    raw.decode("ascii")  # every character escaped
    assert SUBMITTED.encode() not in raw
    (error,) = json.loads(raw)["detail"]
    assert error == {
        "type": "value_error",
        "loc": ["body", "attributes", "k\ud800"],
        "msg": "Value error, bad \udfff",
        "ctx": {"error": "raised \ud83d here", "limit": 3},
    }


@pytest.mark.asyncio
async def test_input_is_dropped_and_the_rest_kept():
    errors = [
        {
            "type": "missing",
            "loc": ("body", "email"),
            "msg": "Field required",
            "input": {"password": SUBMITTED},
        },
        {
            "type": "too_short",
            "loc": ("body", "password"),
            "msg": "Value should have at least 8 items after validation, not 6",
            "input": SUBMITTED,
            "ctx": {"min_length": 8},
            "url": "https://errors.pydantic.dev/2/v/too_short",
        },
    ]
    response = await _handle(errors)
    assert response.status_code == 422
    assert SUBMITTED.encode() not in bytes(response.body)
    assert json.loads(response.body) == {
        "detail": [
            {"type": "missing", "loc": ["body", "email"], "msg": "Field required"},
            {
                "type": "too_short",
                "loc": ["body", "password"],
                "msg": "Value should have at least 8 items after validation, not 6",
                "ctx": {"min_length": 8},
            },
        ]
    }


def test_ctx_is_encoded_as_the_default_handler_encodes_it():
    """A validator's exception in ``ctx`` goes through ``jsonable_encoder``,
    exactly as FastAPI's own handler sends it."""
    body = json.loads(
        render_validation_errors(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "x"),
                    "msg": "Value error, nope",
                    "ctx": {"error": ValueError("nope")},
                }
            ]
        )
    )
    assert body["detail"][0]["ctx"] == {"error": {}}


@pytest.mark.parametrize(
    "ctx",
    [{"limit": math.nan}, {"limit": math.inf}, {"thing": object()}],
    ids=["nan", "inf", "unserialisable"],
)
def test_a_ctx_that_cannot_be_json_falls_back_to_type_loc_msg(ctx):
    raw = render_validation_errors(
        [
            {
                "type": "value_error",
                "loc": ("body", 0, "k\ud800"),
                "msg": "Value error, nope",
                "input": SUBMITTED,
                "ctx": ctx,
            }
        ]
    )
    assert SUBMITTED.encode() not in raw
    assert json.loads(raw) == {
        "detail": [
            {
                "type": "value_error",
                "loc": ["body", "0", "k\ud800"],
                "msg": "Value error, nope",
            }
        ]
    }

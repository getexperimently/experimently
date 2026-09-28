"""The ACS answers a SAML response it cannot read with a fixed message (#123).

The detail is one of two fixed strings plus the request id an administrator
searches the API log for. What the parser said goes to the log, bounded, and
never into the response. Both branches are covered: python3-saml (the full
image) and the development and test stand-in.
"""

from __future__ import annotations

import base64
import uuid
from typing import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from modules.backend.app.models.sso_config import SSOConfig, SSOProviderType
from modules.backend.app.services import sso_service

pytestmark = [pytest.mark.unit, pytest.mark.regression]

MARKER = "MARKERq7z"
REQUEST_ID = "3f9c2e1a-req"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


#: Responses that neither branch can read, each carrying MARKER where a parser
#: repeats what it was given.
PAYLOADS = {
    "mismatched-tag": _b64(f"<{MARKER}></r>"),
    "doctype": _b64(
        f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///{MARKER}">]>'
        "<r>&e;</r>"
    ),
    "not-base64": f"{MARKER}!!!",
}


def _config() -> MagicMock:
    cfg = MagicMock(spec=SSOConfig)
    cfg.id = uuid.uuid4()
    cfg.provider_type = SSOProviderType.SAML
    cfg.entity_id = "https://idp.example.com"
    cfg.sso_url = "https://idp.example.com/sso"
    cfg.x509_certificate = "CERT_PLACEHOLDER"
    cfg.is_active = True
    return cfg


@pytest.fixture(params=["library", "stand-in"])
def branch(request, monkeypatch) -> Iterator[str]:
    if request.param == "library":
        # A failure, not a skip: without python3-saml this param would quietly
        # exercise the stand-in twice.
        assert sso_service._SAML_AVAILABLE is True, "python3-saml is not importable"
    else:
        monkeypatch.setattr(sso_service, "_SAML_AVAILABLE", False)
    yield request.param


@pytest.fixture
def request_id(monkeypatch) -> str:
    monkeypatch.setattr(
        sso_service, "get_log_context", lambda: {"request_id": REQUEST_ID}
    )
    return REQUEST_ID


def _expected(branch: str) -> str:
    return (
        sso_service.SAML_PARSE_FAILED_DETAIL
        if branch == "library"
        else sso_service.SAML_DECODE_FAILED_DETAIL
    )


def _refuse(payload: str) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        sso_service.parse_saml_response(_config(), payload)
    return exc_info.value


@pytest.mark.parametrize("payload", sorted(PAYLOADS))
def test_an_unreadable_saml_response_gets_a_fixed_message_and_the_request_id(
    branch, request_id, payload
):
    exc = _refuse(PAYLOADS[payload])
    assert exc.status_code == 400
    assert exc.detail == f"{_expected(branch)} (request ID: {REQUEST_ID})"


@pytest.mark.parametrize("payload", sorted(PAYLOADS))
def test_without_a_request_id_the_message_is_the_fixed_text_alone(
    branch, monkeypatch, payload
):
    monkeypatch.setattr(sso_service, "get_log_context", dict)
    exc = _refuse(PAYLOADS[payload])
    assert exc.detail == _expected(branch)


def test_a_request_id_that_is_not_id_shaped_is_left_out(branch, monkeypatch):
    monkeypatch.setattr(
        sso_service, "get_log_context", lambda: {"request_id": "<b>not an id</b>"}
    )
    exc = _refuse(PAYLOADS["mismatched-tag"])
    assert exc.detail == _expected(branch)


@pytest.fixture
def log(monkeypatch) -> MagicMock:
    logger = MagicMock()
    monkeypatch.setattr(sso_service, "logger", logger)
    return logger


def _refusal_logs(log: MagicMock) -> list:
    """The refusal's WARNING calls, as (format, args); the stand-in logs its own too."""
    return [
        (c.args[0], c.args[1:])
        for c in log.warning.call_args_list
        if c.args and c.args[0].startswith("SAML response refused")
    ]


def _logged_line(log: MagicMock) -> str:
    calls = _refusal_logs(log)
    assert len(calls) == 1, log.mock_calls
    fmt, args = calls[0]
    return fmt % tuple(args)


def test_the_log_line_carries_the_reason_the_class_and_the_request_id(
    branch, request_id, log
):
    # Each branch's parser repeats MARKER for one of these.
    _refuse(PAYLOADS["mismatched-tag" if branch == "library" else "doctype"])
    line = _logged_line(log)
    assert line.startswith(f"SAML response refused: {_expected(branch)}: "), line
    exc_class = line.split(": ")[1].split(" ")[0]
    assert exc_class.isidentifier() and exc_class[0].isupper(), line
    assert MARKER in line  # the reason is the operator's, in the log
    assert line.endswith(f"request_id={REQUEST_ID}"), line


def test_the_logged_reason_is_bounded(branch, request_id, log):
    _refuse(_b64(f"<{MARKER * 100}></r>" + " " * 1000))
    ((_fmt, args),) = _refusal_logs(log)
    reason = args[2]
    assert 0 < len(reason) <= sso_service.SAML_LOG_REASON_LIMIT

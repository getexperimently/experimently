"""The dashboard's nginx sets its own Content-Security-Policy.

docs/security/threat-model.md lists it as an implemented control (#125: the
page used to recommend adding one). This pins what the page says: the header
is set on every response (`always`), starts from `default-src 'self'`, forbids
framing, and takes `connect-src` from `CSP_CONNECT_SRC`, which
frontend/docker-entrypoint.sh substitutes at start-up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
NGINX = REPO_ROOT / "frontend" / "nginx.conf"

_CSP = re.compile(r'^\s*add_header Content-Security-Policy "([^"]*)" always;\s*$', re.M)


def _policy() -> dict[str, str]:
    (value,) = _CSP.findall(NGINX.read_text(encoding="utf-8"))
    directives = {}
    for part in value.split(";"):
        name, _, rest = part.strip().partition(" ")
        if name:
            directives[name] = rest
    return directives


def test_nginx_sets_one_csp_on_every_response():
    assert _CSP.findall(NGINX.read_text(encoding="utf-8")), (
        f"{NGINX} no longer sets Content-Security-Policy with `always`"
    )
    _policy()  # exactly one


def test_the_directives_the_threat_model_names():
    policy = _policy()
    assert policy["default-src"] == "'self'"
    assert policy["frame-ancestors"] == "'none'"
    assert policy["connect-src"] == "${CSP_CONNECT_SRC}"


def test_the_entrypoint_substitutes_connect_src():
    entrypoint = (REPO_ROOT / "frontend" / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "CSP_CONNECT_SRC" in entrypoint

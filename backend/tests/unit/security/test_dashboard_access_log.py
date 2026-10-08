"""The dashboard's nginx writes its access log without query strings (#1098).

The base image's `main` format writes "$request", the whole request line, so a
results WebSocket opened with `?token=` or the OIDC callback's `code` and
`state` reached `docker compose logs web` in full. frontend/nginx.conf now
defines a `noquery` format in http context (the file is included inside the
base image's `http {}`) that writes "$request_method $uri $server_protocol"
where `main` writes "$request" and keeps every other field, and the server
block logs with it.

This reads the template. The template is rendered by envsubst at start-up, so
what nginx runs is checked in the built image by tests/web/access_log.sh (the
Docker Smoke and Compose Production jobs); the last test here pins the one
thing that rendering depends on, that the entrypoint names the variables it
substitutes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
NGINX = REPO_ROOT / "frontend" / "nginx.conf"
ENTRYPOINT = REPO_ROOT / "frontend" / "docker-entrypoint.sh"

# The `main` format of nginx's stock nginx.conf, which the base image keeps.
MAIN = (
    '$remote_addr - $remote_user [$time_local] "$request" '
    '$status $body_bytes_sent "$http_referer" '
    '"$http_user_agent" "$http_x_forwarded_for"'
)
NOQUERY = MAIN.replace('"$request"', '"$request_method $uri $server_protocol"')

_LOG_FORMAT = re.compile(r"^log_format\s+noquery\s+((?:'[^']*'\s*)+);", re.M)
_ACCESS_LOG = re.compile(r"^(\s*)access_log\s+([^;]*);", re.M)


def _text() -> str:
    return NGINX.read_text(encoding="utf-8")


def _server_start(text: str) -> int:
    match = re.search(r"^server\s*\{", text, re.M)
    assert match, f"{NGINX} has no top-level server block"
    return match.start()


@pytest.mark.regression
def test_noquery_format_is_main_without_the_query():
    text = _text()
    formats = list(_LOG_FORMAT.finditer(text))
    assert len(formats) == 1, f"{NGINX} defines {len(formats)} `log_format noquery`"
    (fmt,) = formats
    assert fmt.start() < _server_start(text), (
        "`log_format noquery` must be in http context, before the server block"
    )
    value = "".join(re.findall(r"'([^']*)'", fmt.group(1)))
    assert value == NOQUERY


@pytest.mark.regression
def test_the_server_block_logs_with_noquery():
    text = _text()
    server = text[_server_start(text) :]
    server_level = [
        m.group(2).split() for m in _ACCESS_LOG.finditer(server) if m.group(1) == "    "
    ]
    assert server_level == [["/var/log/nginx/access.log", "noquery"]]


@pytest.mark.regression
def test_no_access_log_uses_another_format():
    """A location with `access_log ... main` would write the query again."""
    for match in _ACCESS_LOG.finditer(_text()):
        args = match.group(2).split()
        assert args in (["off"], ["/var/log/nginx/access.log", "noquery"]), (
            f"access_log {' '.join(args)}"
        )


def test_the_entrypoint_substitutes_only_its_own_variables():
    """envsubst without a list expands every `$name`, and `$uri` would render
    as an empty string."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(
        r"""^\s*envsubst '\$\{API_UPSTREAM\} \$\{CSP_CONNECT_SRC\}' < "\$TEMPLATE" > "\$TARGET"$""",
        text,
        re.M,
    )

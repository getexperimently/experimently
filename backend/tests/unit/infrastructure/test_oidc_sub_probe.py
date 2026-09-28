"""The OIDC subject probe prints three claims and nothing else.

`.github/workflows/oidc-sub-probe.yml` exists so the AWS trust policy is
written from a real token's ``sub`` (docs/deployment/iam-permissions.md). The
token is a bearer credential for any role that trusts it, and the runner does
not mask it, so the probe must never print it. The static checks pin the shape:
dispatch only, the one choice ``staging``, ``id-token: write`` and nothing
else, no action but the shell step. The behavioural check runs the step's
script against a fake token service and requires its output to be exactly the
three ``sub``/``aud``/``environment`` lines -- so printing the token, the
request bearer, the payload or any other claim fails here.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PROBE = WORKFLOWS / "oidc-sub-probe.yml"

pytestmark = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="this tree has no .github/workflows"
)

AUDIENCE = "sts.amazonaws.com"
REQUEST_BEARER = "REQUEST-BEARER-must-never-be-printed"
SIGNATURE = "SIGNATURE-must-never-be-printed"
CLAIMS = {
    "sub": "repo:example-owner@1/example-repo@2:environment:staging",
    "aud": AUDIENCE,
    "environment": "staging",
    # Claims the probe must not print.
    "jti": "JTI-must-never-be-printed",
    "repository": "REPOSITORY-must-never-be-printed",
    "actor": "ACTOR-must-never-be-printed",
    "ref": "REF-must-never-be-printed",
    "iss": "ISS-must-never-be-printed",
}
EXPECTED_OUTPUT = [
    f"sub={CLAIMS['sub']}",
    f"aud={AUDIENCE}",
    "environment=staging",
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


HEADER = _b64url(json.dumps({"alg": "RS256", "kid": "HEADER-KID"}).encode())
PAYLOAD = _b64url(json.dumps(CLAIMS).encode())
JWT = f"{HEADER}.{PAYLOAD}.{SIGNATURE}"


def _load() -> dict[str, Any]:
    assert PROBE.is_file(), f"{PROBE.relative_to(REPO_ROOT)} is missing"
    document = yaml.safe_load(PROBE.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as the boolean True.
    document["on"] = document.pop(True, document.get("on"))
    return document


def _job() -> dict[str, Any]:
    jobs = _load()["jobs"]
    assert len(jobs) == 1, f"the probe has one job, not {sorted(jobs)}"
    return next(iter(jobs.values()))


def _script() -> str:
    steps = _job()["steps"]
    assert len(steps) == 1, f"the probe has one step, not {len(steps)}"
    return steps[0]["run"]


# --- shape -------------------------------------------------------------------


def test_it_is_dispatched_by_hand_only():
    assert set(_load()["on"]) == {"workflow_dispatch"}


def test_the_only_environment_is_staging():
    inputs = _load()["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"environment"}
    environment = inputs["environment"]
    assert environment["type"] == "choice"
    assert environment["options"] == ["staging"]
    assert environment.get("default", "staging") == "staging"


def test_the_job_is_bound_to_the_chosen_environment():
    assert _job()["environment"] == "${{ inputs.environment }}"


def test_the_only_permission_is_id_token_write():
    document = _load()
    # Workflow level grants nothing, so the job level is all there is.
    assert document.get("permissions") == {}
    assert _job()["permissions"] == {"id-token": "write"}


def test_there_is_no_action_and_no_reusable_workflow():
    job = _job()
    assert "uses" not in job
    for step in job["steps"]:
        assert "uses" not in step, step
        assert set(step) <= {"name", "run"}, sorted(step)


def test_the_script_has_no_interpolation_no_secret_and_no_aws_call():
    text = PROBE.read_text(encoding="utf-8")
    script = _script()
    assert "${{" not in script
    assert "secrets." not in text
    assert "vars." not in text
    assert "aws " not in script
    assert AUDIENCE in script


def test_the_workflow_says_when_it_goes():
    assert "stays until the prod trust policy is written" in PROBE.read_text(
        encoding="utf-8"
    )


# --- behaviour: run the step against a fake token service --------------------


class _TokenService(BaseHTTPRequestHandler):
    seen: list[dict[str, Any]] = []

    def do_GET(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.seen.append(
            {"query": query, "authorization": self.headers.get("Authorization")}
        )
        if (
            self.headers.get("Authorization") != f"bearer {REQUEST_BEARER}"
            or query.get("audience") != [AUDIENCE]
            or query.get("api-version") != ["2.0"]
        ):
            self.send_response(403)
            self.end_headers()
            return
        body = json.dumps({"count": len(JWT), "value": JWT}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def token_service() -> Iterator[str]:
    _TokenService.seen = []
    server = HTTPServer(("127.0.0.1", 0), _TokenService)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/idtoken?api-version=2.0"
    finally:
        server.shutdown()
        server.server_close()


def _run(
    script: str, url: str | None, bearer: str | None
) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    assert bash, "bash is needed to run the probe's step"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
    if url is not None:
        env["ACTIONS_ID_TOKEN_REQUEST_URL"] = url
    if bearer is not None:
        env["ACTIONS_ID_TOKEN_REQUEST_TOKEN"] = bearer
    return subprocess.run(
        [bash, "-e", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_nothing_secret(output: str) -> None:
    for secret in (JWT, HEADER, PAYLOAD, SIGNATURE, REQUEST_BEARER):
        assert secret not in output
    for name, value in CLAIMS.items():
        if name not in ("sub", "aud", "environment"):
            assert value not in output, f"the probe printed the {name!r} claim"


def test_the_probe_prints_exactly_sub_aud_and_environment(token_service):
    result = _run(_script(), token_service, REQUEST_BEARER)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    # It asked for the AWS audience, with the request bearer.
    assert _TokenService.seen, "the probe never asked for a token"
    assert _TokenService.seen[-1]["query"]["audience"] == [AUDIENCE]
    _assert_nothing_secret(output)
    assert result.stdout.splitlines() == EXPECTED_OUTPUT, output
    assert result.stderr == "", result.stderr


def test_a_refused_request_prints_nothing_secret(token_service):
    result = _run(_script(), token_service, "a-wrong-bearer")
    output = result.stdout + result.stderr
    assert result.returncode != 0
    _assert_nothing_secret(output)
    assert "a-wrong-bearer" not in output
    assert "sub=" not in output


def test_a_job_without_the_permission_fails_loudly():
    result = _run(_script(), None, None)
    assert result.returncode != 0
    assert "id-token: write" in result.stdout

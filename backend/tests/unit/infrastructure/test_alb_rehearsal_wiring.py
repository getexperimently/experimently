"""Docker Smoke must rehearse the planned AWS topology with the Host check ON.

Every other Docker Smoke request runs with ``ENVIRONMENT=development`` and no
``PUBLIC_BASE_URL``, where the API's Host allow-list is empty and the check is
off. In the planned AWS topology (Stream C, design C3) the ALB sends
``/api/*``, ``/health``, ``/health/*`` and ``/metrics`` to the API and the rest
to the dashboard, preserving the public Host, so a ``PUBLIC_BASE_URL`` naming
the wrong host refuses every non-probe request with 400 while ``/health/ready``
stays 200. The rehearsal (``tests/alb/``) is the one check that would see that.

These are text/YAML reads with no Docker, so they run in the unit job. What
they pin is the WIRING -- the step exists, it runs the script, the override
and the ALB routes have the shape the script's assertions rely on. The
behaviour itself is exercised by the step, in CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr-qa-gate.yml"
ALB_DIR = REPO_ROOT / "tests" / "alb"
OVERRIDE = ALB_DIR / "docker-compose.alb.yml"
NGINX = ALB_DIR / "nginx.conf"
SCRIPT = ALB_DIR / "rehearse.sh"
OVERRIDE_REL = "tests/alb/docker-compose.alb.yml"

pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file() or not ALB_DIR.is_dir(),
    reason="this tree has no .github/workflows or no tests/alb",
)


def _smoke_steps() -> List[Dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow["jobs"]["docker-smoke"]["steps"]


def _step_index(steps: List[Dict[str, Any]], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, (
        f"expected exactly one docker-smoke step running {needle!r}, found {len(hits)}"
    )
    return hits[0]


def _override() -> Dict[str, Any]:
    return yaml.safe_load(OVERRIDE.read_text())["services"]


def _locations() -> Dict[str, str]:
    """``location`` spec -> its ``proxy_pass`` target, from tests/alb/nginx.conf."""
    out: Dict[str, str] = {}
    current = None
    for raw in NGINX.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("location "):
            current = line[len("location ") :].rstrip("{").strip()
        elif current and line.startswith("proxy_pass "):
            out[current] = line[len("proxy_pass ") :].rstrip(";").strip()
            current = None
    return out


class TestTheStep:
    def test_docker_smoke_runs_the_rehearsal_after_the_stack_starts(self):
        steps = _smoke_steps()
        start = _step_index(steps, "-f docker-compose.yml up -d --wait")
        rehearse = _step_index(steps, "bash tests/alb/rehearse.sh")
        assert rehearse > start
        run = str(steps[rehearse]["run"])
        assert f"-f {OVERRIDE_REL}" in run
        assert " alb" in run, "the alb service is not started"
        assert "if" not in steps[rehearse], "the rehearsal step must not be conditional"
        assert not steps[rehearse].get("continue-on-error"), (
            "a rehearsal that cannot fail is not a gate"
        )

    def test_logs_and_teardown_include_the_override(self):
        steps = _smoke_steps()
        for name in ("Container logs (on failure)", "Tear down"):
            (step,) = [s for s in steps if s.get("name") == name]
            assert f"-f {OVERRIDE_REL}" in str(step["run"]), name


class TestTheTopology:
    def test_the_api_host_check_is_on_and_derived_from_public_base_url(self):
        env = _override()["api"]["environment"]
        host = urlparse(env["PUBLIC_BASE_URL"]).hostname
        assert host == "app.example.test"
        # Setting ALLOWED_HOSTS would take precedence over PUBLIC_BASE_URL and
        # hide a wrong one -- the defect the rehearsal exists to catch.
        assert "ALLOWED_HOSTS" not in env
        assert f'PUBLIC_HOST="${{PUBLIC_HOST:-{host}}}"' in SCRIPT.read_text()

    def test_the_dashboard_does_not_proxy_the_api(self):
        env = _override()["frontend"]["environment"]
        assert env["API_UPSTREAM"] == "http://127.0.0.1:1"

    def test_the_alb_routes_exactly_the_planned_path_set(self):
        assert _locations() == {
            "/api/": "http://api:8000",
            "= /health": "http://api:8000",
            "/health/": "http://api:8000",
            "= /metrics": "http://api:8000",
            "/": "http://frontend:8080",
        }

    def test_the_alb_config_is_what_the_alb_service_mounts(self):
        volumes = _override()["alb"]["volumes"]
        assert "./tests/alb/nginx.conf:/etc/nginx/conf.d/default.conf:ro" in volumes


class TestTheScript:
    def test_the_planted_defect_message_is_the_contract(self):
        """Stream C's VERIFICATION names this message verbatim."""
        text = SCRIPT.read_text()
        assert 'fail "expected 401 without credentials, got $code"' in text

    def test_the_host_check_is_proved_on_not_assumed(self):
        """The 401 alone also passes with the check off; the foreign Host must 400."""
        text = SCRIPT.read_text()
        assert '-H "Host: not-$PUBLIC_HOST"' in text
        assert 'test "$code" = "400"' in text

    def test_it_fails_on_error(self):
        assert "set -euo pipefail" in SCRIPT.read_text()

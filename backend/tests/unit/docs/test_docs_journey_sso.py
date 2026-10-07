"""The compose-sso stack: docs/auth/sso.md's sign-in walked as a compose reader walks it.

The sso-sign-in journey (#1075) brings the full profile up with the override
file the page gives a compose reader, taken from the page at run time, plus
``tests/acceptance/docs/stacks/compose-sso.yml``, which adds an identity
provider: the repository's fake OIDC provider over https, in the API's network
namespace, its certificate signed by a CA made for the run
(``docs_runner/stacks.py``, ``ComposeSso``). What decides whether that walk
can pass for the wrong reason is held here, in the unit job:

* neither file sets ``ENVIRONMENT``, ``APP_ENV`` or ``DEV_AUTH_BYPASS`` on
  ``api``, or gives it an ``env_file``: in ``test`` an ``http`` provider is
  allowed, so the walk would not be the reader's development stack. Each is
  planted into the real overlay and refused, and the stack refuses them
  before it starts anything;
* the overlay's only API setting is the run's CA (``SSL_CERT_FILE``), and the
  page's override sets only variables the page documents;
* one address: the provider's issuer is the journey's ``sso_url``, the port
  the api service publishes, and a ``localhost`` the API reaches in its own
  network namespace; and the page's ``PUBLIC_BASE_URL`` is the dashboard's
  origin the stack opens, which the sign-in's cookie depends on;
* the certificates: the CA's key is gone once the leaf is signed, the leaf is
  for ``localhost``, and a TLS client trusts it with that CA and without
  anything else, and refuses it without the CA;
* only compose-sso's browser context ignores certificate errors;
* compose-dev and compose-sso share one project, so whichever comes up brings
  the other down; compose-sso is brought up with the three files, and its
  temporary directory, outside the checkout and the run directory, is removed
  when it comes down.

``docker`` is a fake that records its calls; ``openssl`` is the real one.
Temporary files only; no network beyond a local socket pair, no git, nothing
from ``modules/``, so it runs the same in ``scripts/core_build.sh``'s copy.
"""

from __future__ import annotations

import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER_ROOT = REPO_ROOT / "tests" / "acceptance" / "docs"
if str(RUNNER_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNNER_ROOT))

from docs_runner import guide as guides
from docs_runner import stacks
from docs_runner.stacks import ComposeDev, ComposeSso, Running

OVERLAY = REPO_ROOT / stacks.SSO_OVERLAY
JOURNEY = RUNNER_ROOT / "journeys" / "sso-sign-in.yaml"


def _overlay() -> Dict[str, Any]:
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def _override() -> Dict[str, Any]:
    return yaml.safe_load(stacks.page_override(REPO_ROOT))


# ---------------------------------------------------------------------------
# What the two files may set on api
# ---------------------------------------------------------------------------
def test_neither_file_sets_what_compose_sso_refuses():
    assert stacks.refused_api_settings(OVERLAY.read_text(encoding="utf-8"), "o") == []
    assert stacks.refused_api_settings(stacks.page_override(REPO_ROOT), "p") == []


def _plant(change) -> str:
    data = _overlay()
    change(data["services"]["api"])
    return yaml.safe_dump(data)


@pytest.mark.parametrize(
    "change, refused",
    [
        pytest.param(
            lambda api: api["environment"].update(ENVIRONMENT="test"),
            "sets ENVIRONMENT on api",
            id="environment-test",
        ),
        pytest.param(
            lambda api: api["environment"].update(APP_ENV="test"),
            "sets APP_ENV on api",
            id="app-env",
        ),
        pytest.param(
            lambda api: api["environment"].update(DEV_AUTH_BYPASS="true"),
            "sets DEV_AUTH_BYPASS on api",
            id="dev-auth-setting",
        ),
        pytest.param(
            lambda api: api.update(
                environment=[f"{k}={v}" for k, v in api["environment"].items()]
                + ["ENVIRONMENT=test"]
            ),
            "sets ENVIRONMENT on api",
            id="environment-as-a-list",
        ),
        pytest.param(
            lambda api: api.update(env_file=["sso.env"]),
            "gives api an env_file",
            id="env-file",
        ),
    ],
)
def test_a_planted_setting_on_api_is_refused(change, refused):
    problems = stacks.refused_api_settings(_plant(change), "the overlay")
    assert len(problems) == 1 and refused in problems[0], problems


def test_the_overlay_sets_only_the_runs_ca_on_api():
    """The one way the API differs from a reader's: it trusts the run's CA."""
    services = _overlay()["services"]
    assert set(services) == {"api", "idp"}
    assert services["api"]["environment"] == {"SSL_CERT_FILE": "/idp/ca.pem"}
    assert set(services["api"]) == {"environment", "volumes", "ports"}


def test_the_page_override_sets_only_what_the_page_documents():
    """Every variable the reader's override sets is in the page's table of them."""
    page = guides.load(REPO_ROOT / "docs", stacks.SSO_GUIDE)
    table = page.section("environment-variables")
    environment = _override()["services"]["api"]["environment"]
    assert environment, "the override sets nothing"
    for name in environment:
        assert f"| `{name}` |" in table, name


def test_the_provider_is_at_one_address_for_the_browser_and_the_api():
    services = _overlay()["services"]
    idp = services["idp"]
    issuer = idp["environment"]["FAKE_OIDC_ISSUER"]
    assert issuer == "https://localhost:28443/oauth2/default"
    assert idp["network_mode"] == "service:api"
    assert idp["environment"]["FAKE_OIDC_BIND"] == "0.0.0.0"
    assert idp["entrypoint"][-2:] == ["--port", "28443"]
    assert services["api"]["ports"] == ["28443:28443"]
    journey = yaml.safe_load(JOURNEY.read_text(encoding="utf-8"))
    created = journey["steps"][0]["do"]["api"]["body"]
    assert created["sso_url"] == issuer
    assert created["provider_type"] == "okta"


def test_the_page_names_the_dashboard_origin_the_stack_opens():
    """PUBLIC_BASE_URL decides the callback's host, where the sign-in's cookie is."""
    value = _override()["services"]["api"]["environment"]["PUBLIC_BASE_URL"]
    stack = ComposeSso(REPO_ROOT, Path("/nonexistent"), {})
    port = stack.ports["FRONTEND_HOST_PORT"]
    resolved = value.replace("${FRONTEND_HOST_PORT:-3000}", str(port))
    assert resolved == f"http://{ComposeSso.HOST}:{port}"
    assert value.replace("${FRONTEND_HOST_PORT:-3000}", "3000") == (
        "http://localhost:3000"
    )


def test_the_override_is_the_first_yaml_block_of_the_compose_section(tmp_path):
    docs = tmp_path / "docs" / "auth"
    docs.mkdir(parents=True)
    (docs / "sso.md").write_text(
        "# SSO\n\n## Elsewhere\n\n```yaml\nservices: {}\n```\n\n"
        "## Trying it on the Docker Compose stack\n\n"
        "```bash\nls docs\n```\n\n```yaml\nservices:\n  api: {}\n```\n\n"
        "```yaml\nsecond: true\n```\n"
    )
    assert stacks.page_override(tmp_path) == "services:\n  api: {}\n"
    (docs / "sso.md").write_text("# SSO\n\n## Something else\n")
    with pytest.raises(stacks.StackError, match="has no section"):
        stacks.page_override(tmp_path)


# ---------------------------------------------------------------------------
# The run's certificates
# ---------------------------------------------------------------------------
@pytest.fixture
def certificates(tmp_path) -> Path:
    directory = tmp_path / "idp"
    directory.mkdir()
    stacks.make_certificates(
        directory, {"PATH": os.environ.get("PATH", "")}, tmp_path / "openssl.log"
    )
    return directory


def _handshake(server: ssl.SSLContext, client: ssl.SSLContext) -> None:
    """A TLS handshake over a socket pair; the client's error, if any, raised."""
    left, right = socket.socketpair()
    failures: List[BaseException] = []

    def serve() -> None:
        try:
            with server.wrap_socket(left, server_side=True) as tls:
                tls.recv(1)
        except (ssl.SSLError, OSError) as error:
            failures.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        with client.wrap_socket(right, server_hostname="localhost") as tls:
            tls.sendall(b"x")
    finally:
        right.close()
        thread.join(10)
        left.close()


def test_the_ca_key_is_gone_and_the_leaf_is_for_localhost(certificates):
    assert sorted(p.name for p in certificates.iterdir()) == [
        "ca.pem",
        "leaf.key",
        "leaf.pem",
    ]
    assert "PRIVATE KEY" not in (certificates / "ca.pem").read_text()
    assert "PRIVATE KEY" in (certificates / "leaf.key").read_text()
    assert stat.S_IMODE((certificates / "leaf.key").stat().st_mode) == 0o600
    assert stat.S_IMODE((certificates / "ca.pem").stat().st_mode) == 0o644
    assert stat.S_IMODE(certificates.stat().st_mode) == 0o755
    text = subprocess.run(
        ["openssl", "x509", "-in", str(certificates / "leaf.pem"), "-noout", "-text"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "DNS:localhost" in text
    assert "CA:FALSE" in text


def test_a_client_trusts_the_provider_with_the_runs_ca_and_not_without(certificates):
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(certificates / "leaf.pem", certificates / "leaf.key")
    trusting = ssl.create_default_context(cafile=str(certificates / "ca.pem"))
    _handshake(server, trusting)
    # The tamper: the same client without the run's CA (what the API is
    # without SSL_CERT_FILE) refuses the provider.
    stranger = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(server, stranger)


def test_a_failing_openssl_is_a_stack_error(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "openssl").write_text("#!/bin/sh\nexit 4\n")
    (fake / "openssl").chmod(0o755)
    (tmp_path / "idp").mkdir()
    with pytest.raises(stacks.StackError, match="openssl exited 4"):
        stacks.make_certificates(tmp_path / "idp", {"PATH": str(fake)}, tmp_path / "l")
    assert list((tmp_path / "idp").iterdir()) == []


# ---------------------------------------------------------------------------
# The browser: only compose-sso's context ignores certificate errors
# ---------------------------------------------------------------------------
def test_only_compose_sso_ignores_https_errors():
    assert Running(name="x", base_url="http://x/").ignore_https_errors is False
    flagged = [
        name
        for name, cls in stacks.STACK_CLASSES.items()
        if getattr(cls, "IGNORE_HTTPS_ERRORS", False)
    ]
    assert flagged == ["compose-sso"]


@pytest.fixture
def execute_module(monkeypatch):
    """docs_runner.execute with a stand-in for Playwright, which the unit job lacks."""
    import importlib

    sync_api = types.ModuleType("playwright.sync_api")

    class _Expect:
        def set_options(self, **kwargs):
            return None

    sync_api.Error = type("Error", (Exception,), {})
    sync_api.Browser = sync_api.Page = sync_api.Playwright = object
    sync_api.expect = _Expect()
    package = types.ModuleType("playwright")
    package.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.delitem(sys.modules, "docs_runner.execute", raising=False)
    module = importlib.import_module("docs_runner.execute")
    yield module
    sys.modules.pop("docs_runner.execute", None)


class _Stop(Exception):
    pass


class _Browser:
    def __init__(self):
        self.options: List[Dict[str, Any]] = []

    def new_context(self, **options):
        self.options.append(options)
        raise _Stop


@pytest.mark.parametrize("ignore", [False, True])
def test_the_browser_context_ignores_certificate_errors_only_when_the_stack_says(
    tmp_path, execute_module, ignore
):
    from docs_runner import log
    from docs_runner.loader import context_for, load

    journey = load(JOURNEY, context_for(REPO_ROOT))
    browser = _Browser()
    runner = execute_module.JourneyRunner(
        None,
        browser,
        log.Log(tmp_path / "results.jsonl"),
        execute_module.Settings(run_dir=tmp_path, run_id="r", sha="s"),
    )
    running = Running(
        name="compose-sso" if ignore else "compose-dev",
        base_url="http://localhost:23000/",
        api_url="http://localhost:28000",
        ignore_https_errors=ignore,
    )
    with pytest.raises(_Stop):
        runner.run(
            journey,
            "sso-sign-in",
            running,
            guides.load(REPO_ROOT / "docs", journey.guide),
        )
    assert browser.options[0].get("ignore_https_errors", False) is ignore


# ---------------------------------------------------------------------------
# The stack, against a fake docker
# ---------------------------------------------------------------------------
FAKE_DOCKER = """#!/bin/sh
here="$(dirname "$0")"
printf '%s\\n' "$*" >> "$here/calls.log"
env | grep '^DOCS_JOURNEY_IDP_' | sort >> "$here/env.log"
case " $* " in
  *" up "*) exit "$(cat "$here/up_exit")" ;;
esac
exit 0
"""
COMPOSE_FILE = """services:
  api:
    ports:
      - "${API_HOST_PORT:-8000}:8000"
  frontend:
    ports:
      - "${FRONTEND_HOST_PORT:-3000}:8080"
"""
DOWN = "compose -p docs-journeys down -v --remove-orphans"
UP = "compose -p docs-journeys up -d --wait --build"


@pytest.fixture
def tree(tmp_path) -> Path:
    """A repository with the compose file, the page, the overlay and a provider."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "docker-compose.yml").write_text(COMPOSE_FILE)
    (root / "docs" / "auth").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "docs" / stacks.SSO_GUIDE, root / "docs" / stacks.SSO_GUIDE)
    (root / stacks.SSO_OVERLAY).parent.mkdir(parents=True)
    shutil.copy(OVERLAY, root / stacks.SSO_OVERLAY)
    (root / stacks.FAKE_IDP).parent.mkdir(parents=True)
    (root / stacks.FAKE_IDP).write_text("# the provider\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(FAKE_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    (bin_dir / "up_exit").write_text("0")
    openssl = shutil.which("openssl")
    assert openssl, "openssl is needed to make the run's certificates"
    os.symlink(openssl, bin_dir / "openssl")
    return root


def _stack(cls, tree: Path, monkeypatch):
    bin_dir = tree.parent / "bin"
    environ = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    stack = cls(tree, tree.parent / "run" / "stacks", environ)
    monkeypatch.setattr(stack, "_served_profile", lambda api_url: "full")
    return stack


def _calls(tree: Path) -> List[str]:
    return (tree.parent / "bin" / "calls.log").read_text().splitlines()


@pytest.fixture(autouse=True)
def _no_stack_left_up():
    yield
    stacks._COMPOSE_UP.clear()


def test_compose_sso_comes_up_with_the_three_files_and_cleans_up(tree, monkeypatch):
    stack = _stack(ComposeSso, tree, monkeypatch)
    running = stack.up("full")
    workdir = stack.workdir
    assert workdir is not None and workdir.is_dir()
    for inside in (tree, tree.parent / "run"):
        assert not workdir.resolve().is_relative_to(inside.resolve())
    up = (
        f"compose -p docs-journeys -f {tree / 'docker-compose.yml'}"
        f" -f {workdir / 'compose.sso.yml'} -f {tree / stacks.SSO_OVERLAY}"
        " up -d --wait --build"
    )
    assert _calls(tree) == [DOWN, up]
    assert (workdir / "compose.sso.yml").read_text() == stacks.page_override(tree)
    assert sorted(p.name for p in (workdir / "idp").iterdir()) == [
        "ca.pem",
        "leaf.key",
        "leaf.pem",
    ]
    env = (tree.parent / "bin" / "env.log").read_text()
    assert f"DOCS_JOURNEY_IDP_DIR={workdir / 'idp'}" in env
    assert f"DOCS_JOURNEY_IDP_USER={os.getuid()}:{os.getgid()}" in env
    assert running.name == "compose-sso"
    assert running.base_url == "http://localhost:23000/"
    assert running.published == {
        3000: "http://localhost:23000",
        8000: "http://localhost:28000",
    }
    assert running.ignore_https_errors is True
    stack.down()
    logs = up.replace(" up -d --wait --build", " logs --no-color api idp")
    assert _calls(tree) == [DOWN, up, logs, DOWN]
    assert not workdir.exists()
    assert stack.workdir is None


def test_a_failed_up_removes_the_runs_certificates(tree, monkeypatch):
    (tree.parent / "bin" / "up_exit").write_text("5")
    stack = _stack(ComposeSso, tree, monkeypatch)
    made: List[Path] = []
    real = stacks.make_certificates
    monkeypatch.setattr(
        stacks,
        "make_certificates",
        lambda directory, env, log: (made.append(directory), real(directory, env, log)),
    )
    with pytest.raises(stacks.StackError, match=r"up \(full\) exited 5"):
        stack.up("full")
    assert made and not made[0].exists()
    assert " logs --no-color api idp" in _calls(tree)[-2]
    assert _calls(tree)[-1] == DOWN


def test_a_refused_setting_stops_the_stack_before_docker_starts_it(tree, monkeypatch):
    overlay = tree / stacks.SSO_OVERLAY
    data = yaml.safe_load(overlay.read_text())
    data["services"]["api"]["environment"]["ENVIRONMENT"] = "test"
    overlay.write_text(yaml.safe_dump(data))
    stack = _stack(ComposeSso, tree, monkeypatch)
    with pytest.raises(stacks.StackError, match="sets ENVIRONMENT on api"):
        stack.up("full")
    assert not any(" up " in f" {call} " for call in _calls(tree))
    assert stack.workdir is None


def test_compose_sso_is_the_full_profile_only(tree, monkeypatch):
    stack = _stack(ComposeSso, tree, monkeypatch)
    with pytest.raises(stacks.StackError, match="full profile"):
        stack.up("core")
    assert not (tree.parent / "bin" / "calls.log").exists()


def test_the_two_compose_stacks_bring_each_other_down(tree, monkeypatch):
    dev = _stack(ComposeDev, tree, monkeypatch)
    sso = _stack(ComposeSso, tree, monkeypatch)
    dev.up("full")
    assert _calls(tree) == [DOWN, UP]
    sso.up("full")
    # compose-dev's own down first, then compose-sso clears and starts.
    assert _calls(tree)[2:4] == [DOWN, DOWN]
    assert dev.running is None and sso.running is not None
    dev.up("full")
    assert dev.running is not None and sso.running is None
    assert sso.workdir is None
    # compose-sso's output is kept, then it and compose-dev's leftovers cleared.
    assert " logs --no-color api idp" in _calls(tree)[-4]
    assert _calls(tree)[-3:] == [DOWN, DOWN, UP]

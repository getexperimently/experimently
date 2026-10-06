"""The four stacks a journey runs against. ``conftest.py`` makes each a fixture.

* ``compose-dev``: the Docker guide's ``docker compose up -d --wait`` at the
  repository root, under its own compose project, with its own host ports.
  Defaults are well away from a developer's own stack (5432, 6379, 8000, 3000);
  each can be set in the environment:

  ======================================  ===========================  =======
  variable                                compose variable it sets     default
  ======================================  ===========================  =======
  ``DOCS_JOURNEY_COMPOSE_PROJECT``        the compose project name     ``docs-journeys``
  ``DOCS_JOURNEY_API_PORT``               ``API_HOST_PORT``            28000
  ``DOCS_JOURNEY_DASHBOARD_PORT``         ``FRONTEND_HOST_PORT``       23000
  ``DOCS_JOURNEY_POSTGRES_PORT``          ``POSTGRES_HOST_PORT``       25432
  ``DOCS_JOURNEY_REDIS_PORT``             ``REDIS_HOST_PORT``          26379
  ======================================  ===========================  =======

  Compose sees only those, ``EXPERIMENTLY_PROFILE`` (the journey's profile),
  ``EXPERIMENTLY_IMAGE_TAG`` (``<project>-<profile>``, so the images it builds
  are its own), and the few variables Docker itself needs: nothing else from the caller's
  environment, no ``.env`` file (``COMPOSE_DISABLE_ENV_FILE=1``), and no AWS
  configuration. After ``up`` the API's ``/api/v1/modules`` must report the
  journey's profile. The stack is brought down (``down -v``) when the session
  ends, or before a journey of the other profile.
* ``docs-local``: ``mkdocs build`` into a temporary directory, served by
  ``python -m http.server`` on 127.0.0.1 (``DOCS_JOURNEY_DOCS_PORT``, else a
  free port). Needs the docs toolchain (``scripts/docs_toolchain.sh``).
* ``docs-published``: ``DOCS_JOURNEY_PUBLISHED_URL``, by default the site's
  ``site_url``. Only an https URL is accepted.
* ``marketing-local``: ``npm run build:marketing`` in ``frontend/`` (which needs
  its ``node_modules``), then ``frontend/out`` served like docs-local
  (``DOCS_JOURNEY_MARKETING_PORT``, else a free port). The build writes Next's
  own output under ``frontend/`` (``.next/``, ``out/``, both ignored by git).

What each command prints goes to ``stacks/<stack>.log`` in the run directory,
never to the console.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

PUBLISHED_URL = "https://getexperimently.github.io/experimently/"

#: (our variable, the compose variable, the default host port)
COMPOSE_PORTS: Tuple[Tuple[str, str, int], ...] = (
    ("DOCS_JOURNEY_API_PORT", "API_HOST_PORT", 28000),
    ("DOCS_JOURNEY_DASHBOARD_PORT", "FRONTEND_HOST_PORT", 23000),
    ("DOCS_JOURNEY_POSTGRES_PORT", "POSTGRES_HOST_PORT", 25432),
    ("DOCS_JOURNEY_REDIS_PORT", "REDIS_HOST_PORT", 26379),
)
#: What compose and docker need from the caller's environment.
PASSED_ENV = (
    "PATH",
    "HOME",
    "USER",
    "TMPDIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
)
#: The ``demo`` seed's accounts (backend/scripts/seed_demo_data.py), which the
#: compose stack applies on its first start.
DEMO_ACCOUNTS: Dict[str, Tuple[str, str]] = {
    "admin": ("admin@demo.com", "Demo1234!"),
    "developer": ("dev@demo.com", "Demo1234!"),
    "analyst": ("analyst@demo.com", "Demo1234!"),
    "viewer": ("viewer@demo.com", "Demo1234!"),
}


class StackError(RuntimeError):
    """The stack did not come up; the message says where its output is."""


@dataclass(frozen=True)
class Running:
    """A stack that answers: where its pages are, and its API if it has one."""

    name: str
    base_url: str
    api_url: str = ""
    profile: str = ""
    accounts: Mapping[str, Tuple[str, str]] = field(default_factory=dict)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, "")
    if not raw:
        return default
    if not raw.isdigit() or not 0 < int(raw) < 65536:
        raise StackError(f"{name}={raw!r} is not a port")
    return int(raw)


def wait_until_answering(url: str, seconds: float) -> None:
    """Poll *url* until it answers at all (any HTTP status), or StackError."""
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except urllib.error.HTTPError:
            return
        except (urllib.error.URLError, OSError) as error:
            last = str(error)
        time.sleep(0.5)
    raise StackError(f"{url} did not answer within {seconds:.0f} s ({last})")


def _run_logged(argv, *, cwd: Path, env: Mapping[str, str], log: Path, timeout: float):
    """Run *argv*, its output appended to *log*; the exit status, or None on timeout."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(argv)}\n")
        handle.flush()
        try:
            done = subprocess.run(
                argv,
                cwd=cwd,
                env=dict(env),
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            handle.write(f"(stopped after {timeout:.0f} s)\n")
            return None
    return done.returncode


class _StaticServer:
    """``python -m http.server`` over a directory, on 127.0.0.1."""

    def __init__(self, root: Path, port: int):
        self.root = root
        self.port = port
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> str:
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "http.server",
                str(self.port),
                "--bind",
                "127.0.0.1",
                "--directory",
                str(self.root),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        url = f"http://127.0.0.1:{self.port}/"
        wait_until_answering(url, 30)
        return url

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class ComposeDev:
    def __init__(self, repo_root: Path, logs: Path, environ: Mapping[str, str]):
        self.repo_root = repo_root
        self.logs = logs
        self.project = environ.get("DOCS_JOURNEY_COMPOSE_PROJECT", "docs-journeys")
        self.ports = {
            compose: _port(environ, ours, default)
            for ours, compose, default in COMPOSE_PORTS
        }
        self.timeout = float(environ.get("DOCS_JOURNEY_COMPOSE_TIMEOUT", "1800"))
        self.passed = {key: environ[key] for key in PASSED_ENV if key in environ}
        self.running: Optional[Running] = None

    def env(self, profile: str) -> Dict[str, str]:
        env = dict(self.passed)
        env.update(
            {
                "COMPOSE_PROJECT_NAME": self.project,
                "COMPOSE_DISABLE_ENV_FILE": "1",
                "AWS_CONFIG_FILE": os.devnull,
                "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                "EXPERIMENTLY_PROFILE": profile,
                # Images of their own, so a developer's experimently-api:core
                # and experimently-web:core are not rebuilt under them.
                "EXPERIMENTLY_IMAGE_TAG": f"{self.project}-{profile}",
            }
        )
        env.update({name: str(port) for name, port in self.ports.items()})
        return env

    def _compose(self, profile: str, *args: str, timeout: float) -> Optional[int]:
        return _run_logged(
            ["docker", "compose", "-p", self.project, *args],
            cwd=self.repo_root,
            env=self.env(profile),
            log=self.logs / "compose-dev.log",
            timeout=timeout,
        )

    def up(self, profile: str) -> Running:
        if self.running is not None and self.running.profile == profile:
            return self.running
        self.down()
        status = self._compose(profile, "up", "-d", "--wait", timeout=self.timeout)
        if status != 0:
            raise StackError(
                f"docker compose up ({profile}) "
                + ("timed out" if status is None else f"exited {status}")
                + "; its output is in stacks/compose-dev.log"
            )
        api_url = f"http://127.0.0.1:{self.ports['API_HOST_PORT']}"
        self.running = Running(
            name="compose-dev",
            base_url=f"http://127.0.0.1:{self.ports['FRONTEND_HOST_PORT']}/",
            api_url=api_url,
            profile=profile,
            accounts=DEMO_ACCOUNTS,
        )
        served = self._served_profile(api_url)
        if served != profile:
            raise StackError(f"the stack serves the {served} profile, not {profile}")
        return self.running

    @staticmethod
    def _served_profile(api_url: str) -> str:
        try:
            with urllib.request.urlopen(
                f"{api_url}/api/v1/modules", timeout=10
            ) as answer:
                return str(json.load(answer).get("profile"))
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise StackError(f"GET /api/v1/modules did not answer: {error}") from None

    def down(self) -> None:
        if self.running is None:
            return
        profile = self.running.profile
        self.running = None
        self._compose(profile, "down", "-v", "--remove-orphans", timeout=600)


class DocsLocal:
    def __init__(self, repo_root: Path, logs: Path, environ: Mapping[str, str]):
        self.repo_root = repo_root
        self.logs = logs
        self.port = _port(environ, "DOCS_JOURNEY_DOCS_PORT", 0)
        self.site: Optional[Path] = None
        self.server: Optional[_StaticServer] = None
        self.running: Optional[Running] = None

    def up(self, profile: str = "") -> Running:
        if self.running is not None:
            return self.running
        self.site = Path(tempfile.mkdtemp(prefix="docs-journeys-site-"))
        status = _run_logged(
            [sys.executable, "-m", "mkdocs", "build", "--site-dir", str(self.site)],
            cwd=self.repo_root,
            env=os.environ,
            log=self.logs / "docs-local.log",
            timeout=600,
        )
        if status != 0:
            raise StackError(
                "mkdocs build "
                + ("timed out" if status is None else f"exited {status}")
                + "; its output is in stacks/docs-local.log"
            )
        self.server = _StaticServer(self.site, self.port or free_port())
        self.running = Running(name="docs-local", base_url=self.server.start())
        return self.running

    def down(self) -> None:
        if self.server is not None:
            self.server.stop()
        if self.site is not None:
            shutil.rmtree(self.site, ignore_errors=True)
        self.server = self.site = self.running = None


class DocsPublished:
    def __init__(self, repo_root: Path, logs: Path, environ: Mapping[str, str]):
        url = environ.get("DOCS_JOURNEY_PUBLISHED_URL", PUBLISHED_URL)
        if not url.startswith("https://"):
            raise StackError(f"DOCS_JOURNEY_PUBLISHED_URL={url!r} is not an https URL")
        self.url = url if url.endswith("/") else url + "/"

    def up(self, profile: str = "") -> Running:
        return Running(name="docs-published", base_url=self.url)

    def down(self) -> None:
        return None


class MarketingLocal:
    def __init__(self, repo_root: Path, logs: Path, environ: Mapping[str, str]):
        self.frontend = repo_root / "frontend"
        self.logs = logs
        self.port = _port(environ, "DOCS_JOURNEY_MARKETING_PORT", 0)
        self.server: Optional[_StaticServer] = None
        self.running: Optional[Running] = None

    def up(self, profile: str = "") -> Running:
        if self.running is not None:
            return self.running
        status = _run_logged(
            ["npm", "run", "build:marketing"],
            cwd=self.frontend,
            env=os.environ,
            log=self.logs / "marketing-local.log",
            timeout=1200,
        )
        if status != 0:
            raise StackError(
                "npm run build:marketing "
                + ("timed out" if status is None else f"exited {status}")
                + "; its output is in stacks/marketing-local.log"
            )
        self.server = _StaticServer(self.frontend / "out", self.port or free_port())
        self.running = Running(name="marketing-local", base_url=self.server.start())
        return self.running

    def down(self) -> None:
        if self.server is not None:
            self.server.stop()
        self.server = self.running = None


STACK_CLASSES = {
    "compose-dev": ComposeDev,
    "docs-local": DocsLocal,
    "docs-published": DocsPublished,
    "marketing-local": MarketingLocal,
}

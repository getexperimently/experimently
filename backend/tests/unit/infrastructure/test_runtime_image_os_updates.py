"""The shipped API image takes Debian's updates at build time.

The ``runtime`` stage of ``backend/Dockerfile`` (the parent of ``core`` and
``full``, the two images release.yml publishes and security-scan.yml runs Trivy
over) starts from ``python:*-slim``. That base is rebuilt on its own schedule,
so between a Debian security release and the rebuild it ships the old
package. With OpenSSL 3.5.7-1~deb13u2 (fixed in deb13u3) that turned the
required "Security Scan Summary" check red on every pull request: Trivy fails
on any HIGH with a fix available, and the image never asked apt for the fix.

The guard: the runtime stage's apt layer runs ``apt-get upgrade`` after
``apt-get update`` and before it installs anything. The end-to-end proof is a
built image scanned by Trivy; this is the cheap check that fails the moment
the upgrade is dropped.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

import pytest
import yaml

from backend.tests.unit.infrastructure._workflow_graph import load

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"


def _stage_instructions(text: str, stage: str) -> list[str]:
    """The instructions of one named stage, continuation lines joined."""
    joined = re.sub(r"\\\n", " ", text)
    instructions: list[str] = []
    current: str | None = None
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE)
        if match:
            current = match.group(1)
            continue
        if current == stage:
            instructions.append(line)
    return instructions


@pytest.mark.unit
@pytest.mark.regression
def test_runtime_stage_upgrades_debian_packages_before_installing():
    runs = [
        i
        for i in _stage_instructions(DOCKERFILE.read_text(), "runtime")
        if i.upper().startswith("RUN ")
    ]
    apt_runs = [r for r in runs if "apt-get install" in r]
    assert apt_runs, "the runtime stage has no apt-get install layer to check"
    for run in apt_runs:
        update = run.find("apt-get update")
        upgrade = run.find("apt-get upgrade -y")
        install = run.find("apt-get install")
        assert 0 <= update < upgrade < install, (
            "the runtime stage must run `apt-get update && apt-get upgrade -y` before "
            "`apt-get install`, so the shipped image carries Debian's security fixes "
            f"even when the python:*-slim base lags behind them:\n{run}"
        )


@pytest.mark.unit
def test_core_and_full_both_inherit_the_runtime_stage():
    """The upgrade covers both published images only while both build FROM runtime."""
    froms = re.findall(
        r"^FROM\s+(\S+)\s+AS\s+(\S+)",
        DOCKERFILE.read_text(),
        re.IGNORECASE | re.MULTILINE,
    )
    parents = {name: base for base, name in froms}
    assert parents.get("core") == "runtime", parents
    assert parents.get("full") == "runtime", parents


WEB_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile"


@pytest.mark.unit
@pytest.mark.regression
def test_web_runtime_stage_upgrades_alpine_packages():
    """The dashboard image's runtime stage (nginx on Alpine) runs ``apk upgrade``.

    Same reason as the API image: the base lags Alpine's security releases, and
    the scan fails on any HIGH with a fix available until the image asks for it.
    """
    runs = [
        i
        for i in _stage_instructions(WEB_DOCKERFILE.read_text(), "runtime")
        if i.upper().startswith("RUN ")
    ]
    assert any("apk upgrade" in r for r in runs), (
        "the dashboard image's runtime stage must run `apk upgrade --no-cache`, so "
        "the shipped image carries Alpine's security fixes even when the base lags"
    )


# -- a cached upgrade layer is refreshed daily --------------------------------
#
# The upgrade above runs only when its layer is rebuilt. The workflows build
# with a GitHub Actions layer cache, and a cached layer is reused for as long as
# nothing it depends on changes; the Alpine and Debian archives are not among
# those things. So the dashboard image security-scan.yml builds for the full
# profile reused an `apk upgrade` layer from before an Alpine package update the
# scan requires, and failed, while in the same run Docker Smoke rebuilt the layer
# and took the update. The fix: an ARG directly before each upgrade RUN, referenced in it,
# and every workflow build of the two Dockerfiles passes it the UTC date, so a
# cached copy of the layer is reused only by builds of the same day.

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
COMPOSE = REPO_ROOT / "docker-compose.yml"
ARG_NAME = "OS_PACKAGES_REFRESHED"
DATE_STEP_ID = "os-packages"
DATE_VALUE = "${{ steps.os-packages.outputs.date }}"
DATE_RUN = """printf 'date=%s\\n' "$(date -u +%Y-%m-%d)" >> "$GITHUB_OUTPUT\""""
#: The two Dockerfiles whose runtime stage upgrades the OS packages.
UPGRADING = {
    "backend/Dockerfile": "apt-get upgrade",
    "frontend/Dockerfile": "apk upgrade",
}


def _upgrade_layer(path: Path, needle: str) -> tuple[str, str]:
    """``(instruction before, the upgrade RUN)`` of *path*'s runtime stage."""
    instructions = _stage_instructions(path.read_text(), "runtime")
    index = [i for i, line in enumerate(instructions) if needle in line]
    assert len(index) == 1, f"{path.name}: expected one `{needle}` RUN, got {index}"
    assert index[0] > 0, f"{path.name}: the upgrade RUN opens the stage"
    return instructions[index[0] - 1], instructions[index[0]]


@pytest.mark.unit
@pytest.mark.regression
@pytest.mark.parametrize("relative", sorted(UPGRADING))
def test_the_upgrade_layer_is_keyed_on_the_refresh_date(relative):
    before, run = _upgrade_layer(REPO_ROOT / relative, UPGRADING[relative])
    assert re.fullmatch(rf"ARG\s+{ARG_NAME}(=\S*)?", before), (
        f"{relative}: the instruction directly before the upgrade RUN must be "
        f"`ARG {ARG_NAME}=...`, so a new value re-runs exactly that layer; "
        f"it is {before!r}"
    )
    assert f"${{{ARG_NAME}}}" in run or f"${ARG_NAME}" in run, (
        f"{relative}: the upgrade RUN must reference {ARG_NAME}: {run}"
    )


def _workflows() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def _dockerfile(path: str, where: str) -> str | None:
    """The repository-relative Dockerfile *path* names, if it is one of ours.

    deploy.yml builds from a second checkout under ``release/``."""
    assert "${{" not in path, f"{where}: an expression in the Dockerfile path"
    normal = posixpath.normpath(path)
    for name in UPGRADING:
        if normal in (name, f"release/{name}"):
            return name
    return None


def _compose_dockerfiles() -> dict[str, str]:
    """``{service: Dockerfile}`` for docker-compose.yml's services that build."""
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    found = {}
    for name, service in services.items():
        build = service.get("build")
        if isinstance(build, str):
            found[name] = posixpath.join(build, "Dockerfile")
        elif isinstance(build, dict):
            context = build.get("context", ".")
            found[name] = posixpath.join(context, build.get("dockerfile", "Dockerfile"))
    return found


def _set_lines(step: dict) -> list[str]:
    return [
        line.strip()
        for line in str(step.get("with", {}).get("set") or "").splitlines()
        if line.strip()
    ]


def _arg_lines(step: dict) -> list[str]:
    return [
        line.strip()
        for line in str(step.get("with", {}).get("build-args") or "").splitlines()
        if line.strip()
    ]


_DOCKER_BUILD = re.compile(r"\bdocker\s+(?:buildx\s+)?build\b")


def _docker_builds(script: str) -> list[str]:
    """Every ``docker build`` / ``docker buildx build`` command of *script*,
    continuation lines joined."""
    joined = re.sub(r"\\\n", " ", script)
    return [line for line in joined.splitlines() if _DOCKER_BUILD.search(line)]


def _builds() -> list[tuple[str, str, str, dict, int, str]]:
    """``(where, kind, Dockerfile, job, index, how)`` for every step of every
    workflow that builds one of the two Dockerfiles. *how* is the line that
    must carry the date: the build-arg, the bake ``set`` or the command."""
    compose = _compose_dockerfiles()
    builds = []
    for path in _workflows():
        workflow = load(path)
        for job_name, job in (workflow.get("jobs") or {}).items():
            for index, step in enumerate(job.get("steps") or []):
                where = f"{path.name}:{job_name}:{step.get('name') or step.get('uses')}"
                uses = str(step.get("uses") or "")
                with_ = step.get("with") or {}
                if uses.startswith("docker/build-push-action"):
                    file = with_.get("file") or posixpath.join(
                        str(with_.get("context", ".")), "Dockerfile"
                    )
                    dockerfile = _dockerfile(str(file), where)
                    if dockerfile:
                        builds.append(
                            (where, "build-push-action", dockerfile, job, index, "")
                        )
                elif uses.startswith("docker/bake-action"):
                    files = [
                        f.strip()
                        for f in re.split(r"[,\n]", str(with_.get("files") or ""))
                        if f.strip()
                    ]
                    assert files == ["docker-compose.yml"], (
                        f"{where}: bake reads {files!r}; this test models "
                        "docker-compose.yml only -- teach it the new file"
                    )
                    targets = [
                        t.strip()
                        for t in str(with_.get("targets") or "").split(",")
                        if t.strip()
                    ]
                    assert targets, f"{where}: bake with no explicit targets"
                    for target in targets:
                        dockerfile = _dockerfile(compose[target], where)
                        if dockerfile:
                            builds.append(
                                (where, "bake", dockerfile, job, index, target)
                            )
                elif "run" in step:
                    for command in _docker_builds(str(step["run"])):
                        match = re.search(r"(?<!\S)(?:-f|--file)[\s=]+(\S+)", command)
                        assert match, (
                            f"{where}: `docker build` with no -f; this test "
                            f"cannot tell which Dockerfile it builds: {command}"
                        )
                        dockerfile = _dockerfile(match.group(1).strip("\"'"), where)
                        if dockerfile:
                            builds.append(
                                (where, "docker build", dockerfile, job, index, command)
                            )
    return builds


_needs_workflows = pytest.mark.skipif(
    not WORKFLOWS.is_dir(), reason="this tree has no .github/workflows"
)


@pytest.mark.unit
@_needs_workflows
def test_the_reader_finds_every_kind_of_build():
    """A positive control: a reader that found nothing would pass vacuously."""
    builds = _builds()
    found = {
        (where.split(":")[0], kind, dockerfile)
        for where, kind, dockerfile, *_ in builds
    }
    for expected in [
        ("security-scan.yml", "build-push-action", "backend/Dockerfile"),
        ("security-scan.yml", "build-push-action", "frontend/Dockerfile"),
        ("pr-qa-gate.yml", "build-push-action", "backend/Dockerfile"),
        ("pr-qa-gate.yml", "build-push-action", "frontend/Dockerfile"),
        ("release.yml", "build-push-action", "backend/Dockerfile"),
        ("release.yml", "build-push-action", "frontend/Dockerfile"),
        ("deploy.yml", "docker build", "backend/Dockerfile"),
        ("deploy.yml", "docker build", "frontend/Dockerfile"),
        ("doc-examples.yml", "bake", "backend/Dockerfile"),
        ("doc-examples.yml", "bake", "frontend/Dockerfile"),
    ]:
        assert expected in found, (
            f"the reader no longer finds {expected}: {sorted(found)}"
        )


@pytest.mark.unit
@pytest.mark.regression
@_needs_workflows
def test_every_workflow_build_passes_the_refresh_date():
    """security-scan.yml's dashboard build (full) passed no date and reused an
    upgrade layer cached before the fix the scan required."""
    missing = []
    for where, kind, _dockerfile, job, index, how in _builds():
        steps = job["steps"]
        step = steps[index]
        if kind == "build-push-action":
            ok = f"{ARG_NAME}={DATE_VALUE}" in _arg_lines(step)
        elif kind == "bake":
            ok = any(
                line
                in (
                    f"*.args.{ARG_NAME}={DATE_VALUE}",
                    f"{how}.args.{ARG_NAME}={DATE_VALUE}",
                )
                for line in _set_lines(step)
            )
        else:
            ok = (
                re.search(
                    rf'--build-arg[\s=]+{ARG_NAME}="?\$\{{?{ARG_NAME}\}}?"?(\s|$)', how
                )
                is not None
                and (step.get("env") or {}).get(ARG_NAME) == DATE_VALUE
            )
        dates = [i for i, s in enumerate(steps) if s.get("id") == DATE_STEP_ID]
        dated = (
            len(dates) == 1
            and dates[0] < index
            and str(steps[dates[0]].get("run", "")).strip() == DATE_RUN
        )
        if not (ok and dated):
            missing.append(f"{where} ({kind}): date passed={ok}, date step={dated}")
    assert not missing, (
        f"every build of {sorted(UPGRADING)} must pass {ARG_NAME}={DATE_VALUE}, "
        f"from a step `id: {DATE_STEP_ID}` earlier in the same job that runs "
        f"`{DATE_RUN}`; otherwise a cached OS package layer is reused for ever:\n"
        + "\n".join(missing)
    )


@pytest.mark.unit
def test_compose_builds_read_no_remote_cache():
    """Builds through docker compose (Docs Journeys, Doc Examples off a pull
    request) are not held to the date: docker-compose.yml names no cache to
    import, so they start from a fresh runner's empty cache. That stays true
    only while no service there names one."""
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name, dockerfile in _compose_dockerfiles().items():
        if posixpath.normpath(dockerfile) in UPGRADING:
            assert "cache_from" not in services[name]["build"], (
                f"docker-compose.yml's {name} imports a build cache; pass it "
                f"{ARG_NAME} as the workflows do"
            )

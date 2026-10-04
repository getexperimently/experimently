"""The security scanners must walk the tree the security code lives in.

Issue #89 moved 58 files -- the SAML XML parser, the PHI encryption, the
SQL-string-building warehouse connectors and the platform's only anonymous
write path -- out of ``backend/app`` and into ``modules/backend/app``.  Every
scanner in ``security-scan.yml`` was pointed at ``backend/`` and stayed there,
so that code went from scanned to unscanned in one commit with nothing to say
so.  The asymmetry was even measurable: five files under ``backend/app`` carry
a ``# nosemgrep`` justification and none under ``modules/backend/app`` does,
because nothing had ever raised a finding there.

Bandit was widened first; Semgrep (a **required** gate -- the summary job has
it in ``needs``) and Trivy were not.  These checks are cheap YAML reads that
fail when a scanner is narrowed back to one tree.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
import yaml

from backend.tests.unit.infrastructure.test_release_credential_scan import (
    check_install,
    trivy_commands,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"

#: A distribution that does not ship the workflows has nothing here to check.
pytestmark = pytest.mark.skipif(
    not WORKFLOW.is_file(), reason="this tree has no .github/workflows"
)


def _workflow(text: Optional[str] = None) -> Dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text() if text is None else text)


def _runs(job_name: str) -> List[str]:
    """Every ``run:`` script of *job_name*."""
    job = _workflow()["jobs"][job_name]
    return [str(step["run"]) for step in job["steps"] if "run" in step]


def _script(job_name: str, needle: str) -> str:
    """The one ``run:`` script of *job_name* that mentions *needle*."""
    matching = [run for run in _runs(job_name) if needle in run]
    assert matching, f"no step in {job_name!r} runs {needle!r}"
    return "\n".join(matching)


class TestEveryScannerSeesBothTrees:
    @pytest.mark.regression
    def test_semgrep_scans_the_modules_tree(self):
        """Semgrep is a required gate and it scanned `backend/app/` only."""
        script = _script("semgrep", "semgrep scan")
        assert "backend/app/" in script
        assert "modules/backend/app" in script, (
            "Semgrep does not reach modules/backend/app: the SAML parser, the "
            "PHI encryption and the inbound webhooks are not scanned at all"
        )

    def test_semgrep_tolerates_a_core_checkout(self):
        """`modules/` is deleted in a core build, so it must be conditional."""
        script = _script("semgrep", "semgrep scan")
        assert "if [ -d modules/backend/app ]" in script

    @pytest.mark.regression
    def test_bandit_scans_the_modules_tree(self):
        script = _script("python-security", "bandit -r")
        assert "modules/backend/app" in script
        assert "if [ -d modules/backend/app ]" in script

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", ["modules-vuln", "modules-secret"])
    def test_trivy_scans_the_modules_dependencies(self, kind):
        """The full image installs modules/requirements.txt on top of the core
        closure, and that file was in no HIGH/CRITICAL gate. Both scanners run
        over modules/, one step each."""
        (scan,) = _commands_of(_workflow(), kind)
        assert (
            scan.argv[-1] == "modules/" and _flags(scan.argv)[0]["--exit-code"] == "1"
        )
        assert scan.guards == [MODULES_GUARD], (
            "the modules scan is not inside the core-checkout branch"
        )

    @pytest.mark.regression
    def test_the_sbom_covers_the_modules_dependencies(self):
        sboms = {
            c.argv[-1]: (c, _flags(c.argv)[0])
            for c in _commands_of(_workflow(), "sbom")
        }
        assert set(sboms) == {"backend/", "modules/"}, sboms
        assert sboms["modules/"][1]["--output"] == "sbom-modules.json", (
            "the published SBOM describes the core image only"
        )
        assert sboms["backend/"][1]["--output"] == "sbom.json"
        assert sboms["modules/"][0].guards == [MODULES_GUARD]
        assert sboms["backend/"][0].guards == []

    def test_the_sbom_upload_survives_a_core_checkout(self):
        """One of the two SBOMs is absent in a core build."""
        job = _workflow()["jobs"]["container-security"]
        upload = [
            step
            for step in job["steps"]
            if "upload-artifact" in str(step.get("uses", ""))
        ]
        assert upload, "the SBOM is never uploaded"
        assert upload[0]["with"].get("if-no-files-found") == "warn"

    def test_semgrep_is_still_a_required_gate(self):
        """These checks are only worth anything while the job blocks."""
        summary = _workflow()["jobs"]["security-summary"]
        assert "semgrep" in summary["needs"]
        assert "container-security" in summary["needs"]
        assert "python-security" in summary["needs"]


# -- every published image is scanned (#77) -----------------------------------

RELEASE = REPO_ROOT / ".github" / "workflows" / "release.yml"
BUILD_ACTION = "docker/build-push-action"
MATRIX_PROFILE = "${{ matrix.profile }}"

#: What makes an image: its Dockerfile, its stage, and its profile build-arg.
ImageKey = Tuple[str, Optional[str], Optional[str]]


def _build_args(step: Dict[str, Any]) -> Dict[str, str]:
    raw = str(step.get("with", {}).get("build-args") or "")
    pairs = (line.strip().split("=", 1) for line in raw.splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def _expand(value: Any, profile: Optional[str], where: str) -> Optional[str]:
    """``${{ matrix.profile }}`` replaced by *profile*; ``None`` stays ``None``."""
    if value is None:
        return None
    text = str(value)
    if MATRIX_PROFILE in text:
        assert profile is not None, f"{where}: {text!r} outside a profile matrix"
        text = text.replace(MATRIX_PROFILE, profile)
    return text


def _built_images(
    workflow: Dict[str, Any], job_names: List[str]
) -> Dict[ImageKey, str]:
    """``{(file, target, profile): tags}`` for every build-push-action step of
    *job_names*, with ``${{ matrix.profile }}`` expanded over the job's matrix."""
    images: Dict[ImageKey, str] = {}
    for name in job_names:
        job = workflow["jobs"][name]
        profiles = job.get("strategy", {}).get("matrix", {}).get("profile") or [None]
        for step in job["steps"]:
            if BUILD_ACTION not in str(step.get("uses", "")):
                continue
            with_ = step["with"]
            for profile in profiles:
                key = (
                    str(_expand(with_["file"], profile, name)),
                    _expand(with_.get("target"), profile, name),
                    _expand(
                        _build_args(step).get("EXPERIMENTLY_PROFILE"), profile, name
                    ),
                )
                images[key] = str(_expand(with_.get("tags", ""), profile, name))
    return images


def _release_images() -> Dict[ImageKey, str]:
    release = yaml.safe_load(RELEASE.read_text())
    publishing = [
        name
        for name, job in release["jobs"].items()
        if any(BUILD_ACTION in str(s.get("uses", "")) for s in job.get("steps", []))
    ]
    return _built_images(release, publishing)


class TestEveryPublishedImageIsScanned:
    """release.yml publishes four images, and the Trivy gate scanned two (#77).

    The set of images is read from release.yml's own build steps rather than
    typed here, so a fifth published image fails these tests until the scan
    builds and scans it too.
    """

    def test_the_release_reader_finds_the_published_images(self):
        """A positive control: if release.yml changes shape so that the reader
        finds nothing, the comparison below would pass vacuously."""
        images = _release_images()
        assert len(images) == 4, images
        files = {key[0] for key in images}
        assert files == {"backend/Dockerfile", "frontend/Dockerfile"}, images

    @pytest.mark.regression
    def test_the_scan_builds_every_image_release_publishes(self):
        scanned = _built_images(_workflow(), ["container-security"])
        missing = sorted(set(_release_images()) - set(scanned), key=str)
        assert not missing, (
            "release.yml publishes images that security-scan.yml's "
            "container-security job never builds, so Trivy never scans them: "
            f"{missing}"
        )

    @pytest.mark.regression
    @pytest.mark.parametrize("kind", ["image-vuln", "image-secret"])
    def test_trivy_scans_every_image_the_job_builds(self, kind):
        """Each image step's OWN loop names every built tag: a tag assembled at
        run time (`...:scan-$target`) cannot be checked here, a tag that
        appears only in log text does not count, and a tag in the other
        scanner's loop does not count either."""
        built = _built_images(_workflow(), ["container-security"])
        assert len(set(built.values())) == len(built), built
        (scan,) = _commands_of(_workflow(), kind)
        assert _image_loop(scan.run) == sorted(built.values()), (
            f"the {kind} loop does not name exactly the tags the job builds"
        )

    def test_the_two_image_scans_are_separate_steps(self):
        (vuln,) = _commands_of(_workflow(), "image-vuln")
        (secret,) = _commands_of(_workflow(), "image-secret")
        assert vuln.step is not secret.step

    def test_the_image_scans_block(self):
        """One policy for every image: HIGH/CRITICAL with a fix fails, and a
        credential in any one of the four fails the step."""
        (vuln,) = _commands_of(_workflow(), "image-vuln")
        assert vuln.tail == ["||", "failed=1"], vuln.tail
        (secret,) = _commands_of(_workflow(), "image-secret")
        assert secret.tail == ["||", "status=$?"], secret.tail
        assert (
            'if [ "$status" -ne 0 ] || [ "$render" -ne 0 ]; then failed=1; fi'
            in secret.run
        )
        for scan in (vuln, secret):
            assert scan.run.rstrip().endswith('exit "$failed"'), scan.run
            assert not scan.step.get("continue-on-error"), (
                "the image scan does not block"
            )


# -- every trivy command, parsed (#772) -----------------------------------------
#
# The checks above used to search run scripts for the text "trivy image",
# which a `::group::trivy image ...` log line satisfies on its own. These
# parse each command instead (``trivy_commands``, shared with
# test_release_credential_scan.py) and classify every one of them; there is
# no class for "anything else".

#: The job that installs trivy and runs every scan.
SCAN_JOB = "container-security"

MODULES_GUARD = "[ -d modules ]"

#: Flags that take no value, so the parser does not read the next token.
BOOLEAN_FLAGS = {"--skip-version-check", "--ignore-unfixed"}

#: The flags of every credential scan: the secret scanner alone, written as
#: JSON to the step's report file, which the renderer reads.
SECRET_FLAGS: Dict[str, Any] = {
    "--skip-version-check": True,
    "--scanners": "secret",
    "--severity": "HIGH,CRITICAL",
    "--exit-code": "1",
    "--format": "json",
    "--output": "$report",
}

#: The flags of every advisory scan: trivy's `vuln` scanner alone, as
#: a table in the log.
VULN_FLAGS: Dict[str, Any] = {
    "--skip-version-check": True,
    "--scanners": "vuln",
    "--severity": "HIGH,CRITICAL",
    "--exit-code": "1",
    "--format": "table",
}

#: Each class of trivy command the workflow runs, with its exact flags, target
#: and core-checkout guard.
EXPECTED: Dict[str, List[Tuple[Dict[str, Any], str, List[str]]]] = {
    "backend-secret": [(SECRET_FLAGS, "backend/", [])],
    "modules-secret": [(SECRET_FLAGS, "modules/", [MODULES_GUARD])],
    "modules-vuln": [(VULN_FLAGS, "modules/", [MODULES_GUARD])],
    "image-secret": [
        ({**SECRET_FLAGS, "--image-src": "docker"}, "$image", []),
    ],
    "image-vuln": [
        (
            {**VULN_FLAGS, "--image-src": "docker", "--ignore-unfixed": True},
            "$image",
            [],
        ),
    ],
    "sbom": [
        (
            {
                "--skip-version-check": True,
                "--format": "cyclonedx",
                "--output": "sbom.json",
            },
            "backend/",
            [],
        ),
        (
            {
                "--skip-version-check": True,
                "--format": "cyclonedx",
                "--output": "sbom-modules.json",
            },
            "modules/",
            [MODULES_GUARD],
        ),
    ],
}

#: Every trivy command in the whole workflow, across every job.
EXPECTED_COUNT = sum(len(v) for v in EXPECTED.values())

INSTALL_NAME = "Install trivy (pinned, checksum-verified)"


class Command:
    """One parsed trivy command and where it sits."""

    def __init__(self, job: str, step: Dict[str, Any], line: str, guards: List[str]):
        argv = trivy_commands(line)[0]
        cut = argv.index("||") if "||" in argv else len(argv)
        self.job, self.step, self.run = job, step, str(step["run"])
        self.line, self.guards = line, guards
        self.argv, self.tail = argv[:cut], argv[cut:]

    def __repr__(self) -> str:
        return f"Command({self.job}: {self.line!r}, guards={self.guards})"


def _flags(argv: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    """``(flags, positionals)`` of ``argv[2:]``."""
    flags: Dict[str, Any] = {}
    positionals: List[str] = []
    rest = list(argv[2:])
    while rest:
        arg = rest.pop(0)
        if not arg.startswith("--"):
            positionals.append(arg)
        elif arg in BOOLEAN_FLAGS or "=" in arg:
            name, _, value = arg.partition("=")
            flags[name] = value or True
        else:
            flags[arg] = rest.pop(0) if rest else None
    return flags, positionals


def _commands(workflow: Dict[str, Any]) -> List[Command]:
    """Every trivy command of every step, with the ``if`` tests around it."""
    found = []
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            guards: List[str] = []
            for line in str(step.get("run", "")).replace("\\\n", " ").splitlines():
                stripped = line.strip()
                opened = re.match(r"^if (.+); then$", stripped)
                if opened:
                    guards.append(opened.group(1))
                elif stripped == "fi" and guards:
                    guards.pop()
                elif stripped == "else" and guards:
                    guards[-1] = f"! {guards[-1]}"
                elif trivy_commands(stripped):
                    found.append(Command(job_name, step, stripped, list(guards)))
    return found


def _classify(command: Command) -> Optional[str]:
    flags, positionals = _flags(command.argv)
    kind = command.argv[1] if len(command.argv) > 1 else None
    scanners = flags.get("--scanners")
    if kind == "image":
        return {"secret": "image-secret", "vuln": "image-vuln"}.get(str(scanners))
    if kind != "fs":
        return None
    if flags.get("--format") == "cyclonedx":
        return "sbom"
    return {
        ("secret", "backend/"): "backend-secret",
        ("secret", "modules/"): "modules-secret",
        ("vuln", "modules/"): "modules-vuln",
    }.get((str(scanners), positionals[0] if len(positionals) == 1 else ""))


def _commands_of(workflow: Dict[str, Any], kind: str) -> List[Command]:
    return [c for c in _commands(workflow) if _classify(c) == kind]


def _image_loop(run: str) -> List[str]:
    """The words of the image step's ``for image in ...; do`` list."""
    joined = run.replace("\\\n", " ")
    loops = re.findall(r"^\s*for image in (.+?); do$", joined, flags=re.M)
    assert len(loops) == 1, f"expected one `for image in` loop, found {loops}"
    return sorted(loops[0].split())


def _install_step(workflow: Dict[str, Any], job: str) -> Optional[Dict[str, Any]]:
    steps = [
        s
        for s in workflow["jobs"][job].get("steps", [])
        if s.get("name") == INSTALL_NAME
    ]
    return steps[0] if len(steps) == 1 else None


def check_scan_shape(workflow: Dict[str, Any]) -> List[str]:
    """Today's scans, command by command: every one classified, each class with
    its exact flags, target and guard."""
    problems = []
    commands = _commands(workflow)
    for command in commands:
        if command.job != SCAN_JOB:
            problems.append(f"{command}: trivy runs outside {SCAN_JOB}")
        if _classify(command) is None:
            problems.append(f"{command}: matches no expected class")
    for kind, expected in EXPECTED.items():
        actual = sorted(
            (
                (_flags(c.argv)[0], c.argv[-1], c.guards)
                for c in commands
                if _classify(c) == kind
            ),
            key=repr,
        )
        if actual != sorted(expected, key=repr):
            problems.append(f"{kind}: expected {expected}, found {actual}")
    for command in _commands_of(workflow, "image-vuln") + _commands_of(
        workflow, "image-secret"
    ):
        built = _built_images(workflow, [SCAN_JOB])
        try:
            loop = _image_loop(command.run)
        except AssertionError as error:
            problems.append(str(error))
            continue
        if loop != sorted(built.values()):
            problems.append(
                f"image loop names {loop}, the job builds {sorted(built.values())}"
            )
    return problems


def check_binary(workflow: Dict[str, Any]) -> List[str]:
    """Every call is ``"$TRIVY"``, and the parser sees every call there is."""
    problems = []
    commands = _commands(workflow)
    for command in commands:
        if command.argv[0] != "$TRIVY" or not command.line.startswith('"$TRIVY" '):
            problems.append(f'{command}: argv[0] is not "$TRIVY"')
    if len(commands) != EXPECTED_COUNT:
        problems.append(
            f"{len(commands)} trivy commands parsed, expected {EXPECTED_COUNT}"
        )
    # A call the line parser cannot see (`status=0; "$TRIVY" ...`,
    # `x=$("$TRIVY" ...)`) still counts here.
    references = 0
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            references += len(re.findall(r"\$\{?TRIVY\b\}?", run))
            if step.get("name") == INSTALL_NAME:
                continue
            bare = re.findall(r"\btrivy\b", run)
            if bare:
                problems.append(
                    f'{job_name}: {step.get("name")} names trivy outside "$TRIVY"'
                )
    if references != EXPECTED_COUNT:
        problems.append(f"{references} references to $TRIVY, expected {EXPECTED_COUNT}")
    install = _install_step(workflow, SCAN_JOB)
    if install is None:
        problems.append(f"{SCAN_JOB} has no single pinned install step")
    else:
        steps = workflow["jobs"][SCAN_JOB]["steps"]
        first_scan = min(steps.index(c.step) for c in commands) if commands else 0
        if steps.index(install) > first_scan:
            problems.append("the pinned install step runs after a trivy command")
    return problems


def check_pins(workflow: Dict[str, Any], release: Dict[str, Any]) -> List[str]:
    """The same two pins and the same install step as release.yml."""
    problems = []
    for name in ("TRIVY_VERSION", "TRIVY_SHA256"):
        ours = str((workflow.get("env") or {}).get(name))
        theirs = str((release.get("env") or {}).get(name))
        if ours != theirs:
            problems.append(f"{name} is {ours!r} here and {theirs!r} in release.yml")
    install = _install_step(workflow, SCAN_JOB)
    released = [
        s
        for job in release["jobs"].values()
        for s in job.get("steps", [])
        if s.get("name") == INSTALL_NAME
    ]
    if not released:
        problems.append("release.yml has no pinned install step to compare with")
    elif install is None or any(s["run"] != install["run"] for s in released):
        problems.append("the install step is not release.yml's, verbatim")
    return problems


#: The backend credential scan, as the workflow spells it.
BACKEND_SCAN = (
    '"$TRIVY" fs --skip-version-check --scanners secret --severity HIGH,CRITICAL'
    ' --exit-code 1 --format json --output "$report" backend/'
)

#: The end of the credential loop's tag list, which the advisory loop
#: does not share.
SECRET_LOOP_END = (
    "experimently-web:scan-core experimently-web:scan-full; do\n"
    "            n=$((n + 1))"
)

#: The install before #772, in outline: the apt package, no pins.
APT_INSTALL = """\
sudo apt-get install -y wget apt-transport-https gnupg lsb-release
sudo apt-get update
sudo apt-get install -y trivy
"""


def _tampered(old: str, new: str) -> Dict[str, Any]:
    text = WORKFLOW.read_text()
    assert text.count(old) == 1, f"tamper anchor not found once: {old!r}"
    return _workflow(text.replace(old, new))


class TestTrivyIsThePinnedBinary:
    """The container scans install trivy the way release.yml does (#772)."""

    @pytest.mark.regression
    def test_trivy_is_the_pinned_checksummed_binary(self):
        assert check_install(_workflow()) == []

    @pytest.mark.regression
    def test_the_pins_and_the_install_step_are_release_yml_s(self):
        assert check_pins(_workflow(), yaml.safe_load(RELEASE.read_text())) == []

    def test_every_trivy_command_is_the_pinned_binary(self):
        assert check_binary(_workflow()) == []

    def test_every_trivy_command_is_one_of_today_s_scans(self):
        assert check_scan_shape(_workflow()) == []

    def test_the_parser_classifies_each_command(self):
        """A positive control: the classes are not empty by accident."""
        counts = Counter(_classify(c) for c in _commands(_workflow()))
        assert counts == {
            "backend-secret": 1,
            "modules-secret": 1,
            "modules-vuln": 1,
            "image-secret": 1,
            "image-vuln": 1,
            "sbom": 2,
        }, counts

    @pytest.mark.regression
    def test_the_apt_install_fails_the_check(self):
        """The file before #772: no pins, and trivy from apt."""
        workflow = _workflow()
        workflow.pop("env")
        install = _install_step(workflow, SCAN_JOB)
        assert install is not None
        install["run"] = APT_INSTALL
        assert check_install(workflow) == [
            "TRIVY_VERSION is None, not 0.74.0",
            "TRIVY_SHA256 is not the 0.74.0 Linux-64bit tarball's",
            f"{SCAN_JOB}: trivy installed with apt",
        ]

    @pytest.mark.parametrize(
        ("old", "new", "check", "expected"),
        [
            (
                "4371a'",
                "4371b'",
                "pins",
                "TRIVY_SHA256 is",
            ),
            (
                BACKEND_SCAN,
                BACKEND_SCAN.replace('"$TRIVY"', "trivy"),
                "binary",
                'argv[0] is not "$TRIVY"',
            ),
            (
                BACKEND_SCAN,
                "status=0; " + BACKEND_SCAN,
                "binary",
                "6 trivy commands parsed",
            ),
            (
                "          fi\n\n      - name: Upload SBOM",
                '          fi\n          x=$("$TRIVY" --version)\n\n      - name: Upload SBOM',
                "binary",
                "8 references to $TRIVY",
            ),
            (
                # One tag dropped from the credential loop only: the
                # advisory loop still names all four.
                SECRET_LOOP_END,
                SECRET_LOOP_END.replace(" experimently-web:scan-full", ""),
                "shape",
                "image loop names",
            ),
            (
                "--ignore-unfixed --exit-code 1",
                "--exit-code 1",
                "shape",
                "image-vuln: expected",
            ),
            (
                BACKEND_SCAN,
                BACKEND_SCAN.replace("--severity HIGH,CRITICAL ", ""),
                "shape",
                "backend-secret: expected",
            ),
            (
                "--image-src docker --scanners secret",
                "--scanners secret",
                "shape",
                "image-secret: expected",
            ),
        ],
    )
    def test_a_planted_defect_turns_the_check_red(self, old, new, check, expected):
        workflow = _tampered(old, new)
        problems = {
            "pins": lambda: check_pins(workflow, yaml.safe_load(RELEASE.read_text())),
            "binary": lambda: check_binary(workflow),
            "shape": lambda: check_scan_shape(workflow),
        }[check]()
        assert any(expected in p for p in problems), problems


# -- every credential report stays on the runner (#772) -------------------------
#
# Each credential scan writes trivy's JSON report to a file under $RUNNER_TEMP,
# and the only thing that reads it is scripts/render_secret_findings.py, which
# prints path, rule, severity and line. These checks hold that shape for every
# trivy command in the workflow, whichever scanners it names.

UPLOAD_ACTION = "actions/upload-artifact"

#: The one way a report is read: the renderer, with the ci wording, keeping its
#: own exit status.
RENDER_CALL = re.compile(
    r'^python3 "\$GITHUB_WORKSPACE/scripts/render_secret_findings\.py" '
    r'"(?P<report>[^"]+)" --stage ci --label "[^"]+" \|\| render=\$\?$'
)

#: How a step ends: trivy's status first, then the renderer's; or, in a loop
#: over images, either one marks the step failed.
EXIT_PATTERNS = (
    'if [ "$status" -ne 0 ]; then exit "$status"; fi\nexit "$render"',
    'if [ "$status" -ne 0 ] || [ "$render" -ne 0 ]; then failed=1; fi',
)

#: Text in an upload path that could reach a report.
UPLOAD_REFUSED = ("RUNNER_TEMP", "runner.temp", "_temp", "secrets-", "*", "?")


def _scanners(flags: Dict[str, Any]) -> set:
    """The scanners a command runs; trivy's default is vuln and secret."""
    value = flags.get("--scanners")
    return set(str(value).split(",")) if value else {"vuln", "secret"}


def _resolve(run: str, value: str) -> str:
    """*value*, or the one ``name="..."`` assignment it names in *run*."""
    named = re.fullmatch(r"\$\{?(\w+)\}?", value)
    if not named:
        return value
    assigned = re.findall(rf'^\s*{named.group(1)}="([^"]*)"\s*$', run, flags=re.M)
    return assigned[0] if len(assigned) == 1 else ""


def _stripped_lines(run: str) -> List[str]:
    return [line.strip() for line in run.replace("\\\n", " ").splitlines()]


def check_reports(workflow: Dict[str, Any]) -> List[str]:
    """Every credential scan writes JSON under $RUNNER_TEMP, only the renderer
    reads it, nothing uploads it, and no step of the scan job may fail
    quietly."""
    problems = []
    for command in _commands(workflow):
        flags, _ = _flags(command.argv)
        if flags.get("--format") == "cyclonedx":
            if "--scanners" in flags:
                problems.append(f"{command}: an SBOM command names scanners")
            continue
        if "--scanners" not in flags:
            problems.append(f"{command}: no --scanners, so trivy runs vuln and secret")
        scanners = _scanners(flags)
        if "secret" not in scanners:
            continue
        if scanners != {"secret"}:
            problems.append(
                f"{command}: the secret scanner shares a command with "
                f"{sorted(scanners - {'secret'})}"
            )
        if flags.get("--format") != "json":
            problems.append(
                f"{command}: runs the secret scanner with --format "
                f"{flags.get('--format')}"
            )
        output = str(flags.get("--output") or "")
        path = _resolve(command.run, output)
        if not path.startswith("$RUNNER_TEMP/"):
            problems.append(
                f"{command}: the report {output!r} ({path!r}) is not under $RUNNER_TEMP"
            )
        if command.tail != ["||", "status=$?"]:
            problems.append(f"{command}: trivy's status is not kept")
        lines = _stripped_lines(command.run)
        rendered = [m.group("report") for m in map(RENDER_CALL.match, lines) if m]
        if output not in rendered:
            problems.append(f"{command}: the report is not rendered in the same step")
        if f'rm -f "{output}"' not in lines or lines.index(
            f'rm -f "{output}"'
        ) > lines.index(command.line):
            problems.append(f"{command}: the report is not removed before the scan")
        uses = command.run.count(f'"{output}"')
        if uses != 3:
            problems.append(
                f"{command}: the report is used {uses} times; only rm, --output "
                "and the renderer may name it"
            )
        if not any(pattern in "\n".join(lines) for pattern in EXIT_PATTERNS):
            problems.append(f"{command}: the step does not end on both statuses")
    for job_name, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            if UPLOAD_ACTION not in str(step.get("uses", "")):
                continue
            paths = str((step.get("with") or {}).get("path", "")).splitlines()
            for path in filter(None, (p.strip() for p in paths)):
                if any(s in path for s in UPLOAD_REFUSED) or path.startswith(
                    ("/", "~", "..")
                ):
                    problems.append(f"{job_name}: {step.get('name')} uploads {path}")
    for step in workflow["jobs"][SCAN_JOB]["steps"]:
        if step.get("continue-on-error", False) not in (False, "false"):
            problems.append(f"{SCAN_JOB}: {step.get('name')} has continue-on-error")
    return problems


#: The credential and advisory scans as #772 found them: one command per
#: tree or image, both scanners, a table in the log.
TABLE_SCANS = {
    "Scan the backend tree for credentials": (
        '"$TRIVY" fs --skip-version-check --scanners secret --severity HIGH,CRITICAL'
        " --exit-code 1 --format table backend/\n"
    ),
    "Scan the module tree for credentials": (
        "if [ -d modules ]; then\n"
        '  "$TRIVY" fs --skip-version-check --severity HIGH,CRITICAL --exit-code 1'
        " --format table modules/\n"
        "fi\n"
    ),
    "Scan the built images for credentials": (
        "set -euo pipefail\n"
        "failed=0\n"
        "for image in experimently-api:scan-core experimently-api:scan-full"
        " experimently-web:scan-core experimently-web:scan-full; do\n"
        '  "$TRIVY" image --skip-version-check --severity HIGH,CRITICAL'
        ' --ignore-unfixed --exit-code 1 --format table "$image" || failed=1\n'
        "done\n"
        'exit "$failed"\n'
    ),
}


class TestEveryCredentialReportStaysOnTheRunner:
    def test_every_credential_report_stays_on_the_runner(self):
        assert check_reports(_workflow()) == []

    def test_the_check_sees_every_credential_scan(self):
        """A positive control: three credential scans, each rendered."""
        secret = [
            c
            for c in _commands(_workflow())
            if "secret" in _scanners(_flags(c.argv)[0])
            and _flags(c.argv)[0].get("--format") != "cyclonedx"
        ]
        assert len(secret) == 3, secret

    @pytest.mark.regression
    def test_the_table_scans_fail_the_check(self):
        """The three scans as #772 found them, each a table in the log."""
        workflow = _workflow()
        for step in workflow["jobs"][SCAN_JOB]["steps"]:
            if step.get("name") in TABLE_SCANS:
                step["run"] = TABLE_SCANS[step["name"]]
        problems = check_reports(workflow)
        for target in ("backend/", "modules/", "$image"):
            assert any(f"{target}" in p and "--format table" in p for p in problems), (
                target,
                problems,
            )
        assert any("no --scanners" in p for p in problems), problems

    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            (
                '--format json --output "$report" backend/',
                "--format table backend/",
                "runs the secret scanner with --format table",
            ),
            (
                '--label "backend/ (source tree)" || render=$?',
                '--label "backend/ (source tree)" || render=$?\n          cat "$report"',
                "the report is used 4 times",
            ),
            (
                '--label "backend/ (source tree)" || render=$?',
                "",
                "is not rendered in the same step",
            ),
            (
                'report="$RUNNER_TEMP/secrets-backend.json"',
                'report="secrets-backend.json"',
                "is not under $RUNNER_TEMP",
            ),
            (
                'rm -f "$report"\n          status=0',
                "status=0",
                "is not removed before the scan",
            ),
            (
                "backend/ || status=$?",
                "backend/",
                "trivy's status is not kept",
            ),
            (
                'if [ "$status" -ne 0 ]; then exit "$status"; fi\n          exit "$render"\n'
                "        continue-on-error: false\n\n      # `modules/",
                'exit "$render"\n        continue-on-error: false\n\n      # `modules/',
                "does not end on both statuses",
            ),
            (
                "            sbom-modules.json\n",
                "            sbom-modules.json\n"
                "            ${{ runner.temp }}/secrets-backend.json\n",
                "uploads ${{ runner.temp }}/secrets-backend.json",
            ),
            (
                'exit "$render"\n        continue-on-error: false\n\n      # `modules/',
                'exit "$render"\n        continue-on-error: true\n\n      # `modules/',
                "has continue-on-error",
            ),
            (
                "--image-src docker --scanners secret",
                "--image-src docker --scanners vuln,secret",
                "the secret scanner shares a command with ['vuln']",
            ),
            (
                "--scanners vuln --severity HIGH,CRITICAL --exit-code 1"
                " --format table modules/",
                "--severity HIGH,CRITICAL --exit-code 1 --format table modules/",
                "no --scanners",
            ),
        ],
    )
    def test_a_planted_defect_turns_the_check_red(self, old, new, expected):
        problems = check_reports(_tampered(old, new))
        assert any(expected in p for p in problems), problems

#!/usr/bin/env python3
"""Audit the dependency closures, in two tiers, without ``continue-on-error``.

The tiers exist because "does this ship?" is the question that decides how much
an advisory matters, and the answer is knowable:

* **shipped** -- ``backend/requirements/runtime.lock`` and
  ``modules/requirements.lock``, the hashed closures the images install
  verbatim. Any advisory here fails, and no exception can be written for one:
  shipping a known vulnerability is not a decision a config file should be able
  to express.
* **development** -- ``backend/requirements.txt``, what every test job and
  developer venv installs. Advisories here may be accepted, one at a time, in
  ``security/dependency-audit.toml``, with a reason and a review date.

Both tiers used to be a single ``pip-audit`` step with
``continue-on-error: true``, which is the same as not running it.

Three things make the exception list a gate rather than a sink:

1. an advisory in the development closure that is *not* listed fails;
2. a listed advisory that no longer fires fails -- a stale exception outliving
   its reason is how these lists rot;
3. a listed package that appears in a **shipped** closure fails -- "it is only
   a test dependency" is checked, not believed.

Usage::

    python scripts/audit_dependencies.py            # both tiers
    python scripts/audit_dependencies.py --tier shipped
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A pinned line, with any extras group captured separately -- the same shapes
#: ``scripts/check_requirements_lock.py`` uses, and for the same reason. The
#: first version of this split on ``==`` and lower-cased, which meant
#: ``databricks-sql-connector[pyarrow]==4.5.0`` -- a pin *this* change
#: introduced -- produced the key ``databricks-sql-connector[pyarrow]``, which
#: no exception name could ever match, and ``zope.interface`` never matched an
#: exception written ``zope-interface``. Both made the "does this package
#: actually ship?" check fail open, which is the one check that is supposed to
#: stop "it is only a test dependency" from being taken on trust.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)")


def canonical(name: str) -> str:
    """PEP 503 normalisation: ``Zope.Interface`` and ``zope_interface`` agree."""
    return re.sub(r"[-_.]+", "-", name.split("[", 1)[0]).lower()


IGNORE_FILE = ROOT / "security" / "dependency-audit.toml"

#: Everything that is deployed somewhere. The two image locks are hashed and
#: are the exact artefacts pip installs; the Lambda closures are zipped and
#: uploaded to AWS by CDK, which makes them shipped by any reading of the word
#: even though no image contains them (.dockerignore excludes backend/lambda).
#: They were in neither tier, so nothing audited them at all.
#:
#: Note what that is worth today: all three Lambda files are comments only --
#: the handlers use the standard library and the boto3 the runtime provides.
#: So the audit of them currently reports zero packages because there are zero
#: packages, which is not the same statement as "clean". Listing them is still
#: the right thing: the day one of them declares a dependency, it is audited
#: from the first commit rather than from whenever somebody remembers.
SHIPPED_FILES = (
    Path("backend/requirements/runtime.lock"),
    Path("modules/requirements.lock"),
    Path("backend/lambda/assignment/requirements.txt"),
    Path("backend/lambda/event_processor/requirements.txt"),
    Path("backend/lambda/feature_flag_evaluation/requirements.txt"),
)

#: What test jobs, developer venvs and the deployment toolchain install, on top
#: of which nothing is served. modules/requirements.txt is deliberately *not*
#: here -- it is a shipped closure's input, covered above through
#: modules/requirements.lock. infrastructure/cdk/requirements.txt is: CDK runs
#: on a laptop or a CI runner and synthesises templates; it is not deployed,
#: but it does hold credentials while it runs, so it is audited rather than
#: ignored.
DEVELOPMENT_FILES = (
    Path("backend/requirements.txt"),
    Path("infrastructure/cdk/requirements.txt"),
)


class Advisory(tuple):
    """``(package, version, id)`` -- what pip-audit reports, flattened."""

    __slots__ = ()

    @property
    def package(self) -> str:
        return self[0]

    @property
    def id(self) -> str:
        return self[2]

    def __str__(self) -> str:
        return f"{self[0]} {self[1]}: {self[2]}"


#: Files that cannot be audited as written because they are not pinned to
#: exact versions, and so must be resolved first. Exactly one today:
#: ``infrastructure/cdk/requirements.txt`` carries ranges
#: (``constructs>=10.0.0,<11.0.0``), and pip-audit refuses ``--disable-pip`` on
#: it with "requirement constructs is not pinned to an exact version".
#:
#: The cost is the one ``--disable-pip`` exists to avoid: the verdict depends
#: on what resolves at the time, so this file can go red without anyone
#: changing the repository. That is a property of the file, not of the gate --
#: pinning it (and generating a lock, as the other closures have) is what would
#: move it onto the same footing as everything else.
RESOLVED_FILES = frozenset({Path("infrastructure/cdk/requirements.txt")})


def run_pip_audit(requirements: Path) -> list[Advisory]:
    """Every advisory pip-audit reports for *requirements*.

    ``--disable-pip``, not ``--no-deps``. This was ``--no-deps`` with a comment
    claiming it stopped pip resolving, and that is not what the flag does:
    ``--no-deps`` only *permits* auditing an unhashed file; resolution still
    happens. Measured on ``backend/requirements.txt``: 75 pins, **179**
    dependencies audited, including ``ecdsa``, which that file does not pin.
    Two things followed from it. The tier boundary was fiction -- a development
    advisory could arrive from a transitive nobody pinned, turning the gate red
    with no change to the repository -- and three full pip resolutions
    (aws-cdk-lib, pandas/scipy, lxml/xmlsec) ran on every pull request.
    ``--disable-pip`` audits exactly the versions written down, which is the
    premise of auditing a lock file at all.

    The exit status is *checked*. It was discarded, which made ``--strict``
    inert: pip-audit reports a package it could not resolve as
    ``{"skip_reason": ...}`` with no ``vulns``, so the loop below saw an empty
    list and the gate printed "no unaccepted advisories" while a package had
    gone unaudited.
    """
    try:
        relative = (
            requirements.relative_to(ROOT)
            if requirements.is_absolute()
            else requirements
        )
    except ValueError:
        # Outside the tree: never a RESOLVED_FILES entry, and not a reason to
        # raise. `_display()` exists 100 lines below for exactly this, and this
        # construct was left behind when it was added.
        relative = requirements
    # See RESOLVED_FILES: pinned closures are audited exactly as written,
    # unpinned ones have to be resolved or they cannot be audited at all.
    pinning_flags = [] if relative in RESOLVED_FILES else ["--no-deps", "--disable-pip"]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--requirement",
            str(requirements),
            *pinning_flags,
            # Both, and the order of the words matters less than the fact that
            # neither works alone: --disable-pip is what actually stops
            # resolution, and pip-audit refuses it on an unhashed file unless
            # --no-deps is also given ("the --disable-pip flag can only be used
            # with a hashed requirements files or if the --no-deps flag has
            # been provided"). --no-deps by itself, which is what this had,
            # only permits the unhashed file and resolves anyway.
            "--strict",
            "--progress-spinner",
            "off",
            "--format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        raise SystemExit(
            f"pip-audit produced no output for {requirements}:\n"
            f"{result.stderr.strip()[-2000:]}"
        )
    report = json.loads(result.stdout)

    skipped = [
        f"{d['name']}: {d['skip_reason']}"
        for d in report.get("dependencies", [])
        if d.get("skip_reason")
    ]
    if skipped:
        raise SystemExit(
            f"pip-audit could not audit {len(skipped)} package(s) in "
            f"{requirements} -- an unaudited package is not an audited one:\n  "
            + "\n  ".join(skipped)
        )

    advisories: list[Advisory] = []
    for dependency in report.get("dependencies", []):
        for vuln in dependency.get("vulns", []):
            advisories.append(
                Advisory(
                    (dependency["name"], dependency.get("version", "?"), vuln["id"])
                )
            )

    # pip-audit exits 1 both for "found something" and for "could not run".
    # Non-zero with nothing found and nothing skipped is the second, and must
    # never read as clean.
    if result.returncode != 0 and not advisories:
        raise SystemExit(
            f"pip-audit exited {result.returncode} for {requirements} with no "
            f"findings:\n{result.stderr.strip()[-2000:]}"
        )
    return advisories


def _display(path: Path) -> str:
    """A path to show a human: repository-relative when it is inside the tree.

    ``relative_to`` raises when it is not, which is not a thing an error
    message should be able to do -- the tests point ``IGNORE_FILE`` at a
    temporary file, and this turned every failure path into a ValueError
    instead of the message it was supposed to print.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_ignores() -> list[dict]:
    if not IGNORE_FILE.is_file():
        return []
    data = tomllib.loads(IGNORE_FILE.read_text(encoding="utf-8"))
    entries = data.get("ignore", [])
    for entry in entries:
        missing = {"id", "package", "reason", "review_by"} - set(entry)
        if missing:
            raise SystemExit(
                f"{IGNORE_FILE.name}: entry {entry.get('id', '?')} is missing "
                f"{sorted(missing)}. Every exception needs a reason and a review date."
            )
        if not entry["reason"].strip():
            raise SystemExit(
                f"{IGNORE_FILE.name}: entry {entry['id']} has an empty reason."
            )
        # `review_by` was required to be *present* and never read, so
        # `review_by = "whenever"` was accepted and a date that had passed kept
        # suppressing advisories forever -- the rot the file's own header says
        # it prevents. Parsed, and enforced.
        raw = entry["review_by"]
        try:
            # datetime FIRST: TOML's `2030-01-01T00:00:00Z` parses to a
            # datetime, which is a subclass of date, so the isinstance shortcut
            # accepted it and the comparison below then raised
            # "can't compare datetime.datetime to datetime.date" -- a traceback
            # where the ISO-date message belongs.
            if isinstance(raw, datetime):
                review_by = raw.date()
            elif isinstance(raw, date):
                review_by = raw
            else:
                review_by = date.fromisoformat(str(raw).strip())
        except ValueError:
            raise SystemExit(
                f"{IGNORE_FILE.name}: entry {entry['id']} has review_by={raw!r}, "
                "which is not an ISO date (YYYY-MM-DD)."
            ) from None
        if review_by < date.today():
            raise SystemExit(
                f"{IGNORE_FILE.name}: the exception for {entry['id']} "
                f"({entry['package']}) was due for review on {review_by} and is "
                "still here. Re-read it: upgrade the pin, or move the date and "
                "say why it is still acceptable."
            )
        entry["review_by"] = review_by

    # A repeated (id, package) pair is an authoring mistake, and it used to
    # vanish: entries were keyed by id alone, so a second one replaced the
    # first. That became load-bearing when acceptance started matching on the
    # id AND the package -- two legitimate entries for one advisory attributed
    # to two packages (the same CVE against a package and its fork, or a
    # rename) collapsed, and the survivor's sibling was then reported both as
    # a package mismatch and as unlisted, with a message accusing the author
    # of writing the wrong name.
    seen: dict[tuple[str, str], dict] = {}
    for entry in entries:
        key = (entry["id"], canonical(entry["package"]))
        if key in seen:
            first = seen[key]["package"]
            spellings = (
                f"{first!r}"
                if first == entry["package"]
                else f"{first!r} and {entry['package']!r}, which normalise to "
                f"{canonical(entry['package'])!r}"
            )
            raise SystemExit(
                f"{IGNORE_FILE.name}: {entry['id']} is listed twice for "
                f"{spellings}. Two entries for one advisory and one package "
                "cannot both be the reason; merge them."
            )
        seen[key] = entry
    return entries


def audit(files: tuple[Path, ...]) -> tuple[list[Advisory], list[Path]]:
    """Advisories across *files*, and which of them were actually present."""
    found: list[Advisory] = []
    scanned: list[Path] = []
    for relative in files:
        path = ROOT / relative
        if not path.is_file():
            # modules/ is absent in a core checkout; that is not a failure.
            print(f"  {relative}: absent (core checkout)")
            continue
        scanned.append(relative)
        advisories = run_pip_audit(path)
        print(
            f"  {relative}: {len(advisories)} advisor{'y' if len(advisories) == 1 else 'ies'}"
        )
        found.extend(advisories)
    return found, scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        choices=["shipped", "development", "both"],
        default="both",
        help="Which closure to audit (default: both).",
    )
    args = parser.parse_args()

    failures: list[str] = []

    # The shipped tier is self-contained. The development tier is not: its
    # stale-exception check needs the shipped advisories (an exception whose
    # advisory fires only there is not dead), and its ship check needs the
    # shipped package names. So `--tier development` runs the shipped audit
    # too, deliberately -- that is a dependency, not the tier leak this
    # script was fixing. `--tier shipped` runs nothing of the development
    # tier, which is the direction that was leaking.
    print("shipped closures (no exceptions possible):")
    shipped, shipped_scanned = audit(SHIPPED_FILES)

    if args.tier in ("shipped", "both") and shipped:
        failures.append(
            "advisories in a SHIPPED closure -- these reach the images:\n"
            + "\n".join(f"    {a}" for a in shipped)
        )

    ignores: list[dict] = []
    development: list[Advisory] = []
    if args.tier in ("development", "both"):
        ignores = load_ignores()
        # (id, package) is what acceptance matches on, so it is what every
        # check below keys on. A set, not a second dict: `load_ignores`
        # already built this index to detect duplicates, and two derivations
        # of "what a key is" would let acceptance and duplicate-detection
        # drift apart.
        accepted_keys = {(e["id"], canonical(e["package"])) for e in ignores}

        # Read only here: the ship check is the only consumer, and computing
        # it under `--tier shipped` was work for a branch that never runs.
        shipped_packages = set()
        for relative in shipped_scanned:
            for line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
                match = _PIN.match(line.split("#", 1)[0].strip())
                if match:
                    shipped_packages.add(canonical(match.group(1)))

        print("development closure:")
        development, _ = audit(DEVELOPMENT_FILES)

        # Computed from `ignores` directly, NOT from `accepted_keys` and NOT
        # as `not accepted(a)`: deriving it from the same lookup acceptance
        # uses means neutering that lookup disables this check too, so the
        # test for it passes against a broken gate. (Caught once by
        # tamper-testing the test; nearly reintroduced while rekeying.)
        mismatched = []
        mismatched_ids = set()
        for advisory in development:
            listed = [e["package"] for e in ignores if e["id"] == advisory.id]
            if not listed:
                continue
            if canonical(advisory.package) in {canonical(name) for name in listed}:
                continue
            mismatched_ids.add(advisory.id)
            mismatched.append(
                f"{advisory}: accepted for package(s) {sorted(listed)!r}, but "
                f"pip-audit attributes it to {advisory.package!r}"
            )
        if mismatched:
            failures.append(
                "exception(s) whose package does not match the advisory:\n"
                + "\n".join(f"    {m}" for m in mismatched)
            )

        # Excluding the mismatched ones. They were reported above with the
        # remedy that applies -- fix the package name -- and reporting them
        # again here told the author to "add an entry", which they already
        # had.
        unlisted = [
            a
            for a in development
            if (a.id, canonical(a.package)) not in accepted_keys
            and a.id not in mismatched_ids
        ]
        if unlisted:
            failures.append(
                "advisories in the development closure with no accepted exception:\n"
                + "\n".join(f"    {a}" for a in unlisted)
                + f"\n  Upgrade the pin, or add an entry to {_display(IGNORE_FILE)} "
                "with a reason and a review date."
            )

        # Keyed on (id, package), like acceptance. Keyed on the id alone, a
        # dead entry survived for ever as soon as any sibling entry with the
        # same id was live -- which only became reachable when this file
        # started allowing several entries per id.
        live = {(a.id, canonical(a.package)) for a in development} | {
            (a.id, canonical(a.package)) for a in shipped
        }
        stale = [
            entry
            for entry in ignores
            if (entry["id"], canonical(entry["package"])) not in live
        ]
        if stale:
            failures.append(
                "exceptions that no longer match any advisory (remove them):\n"
                + "\n".join(f"    {e['id']} ({e['package']})" for e in stale)
            )

        # "It is only a test dependency" is checked, not believed.
        shipped_exceptions = [
            entry
            for entry in ignores
            if canonical(entry["package"]) in shipped_packages
        ]
        if shipped_exceptions:
            failures.append(
                "exceptions for packages that DO ship -- an advisory in an image "
                "cannot be accepted here:\n"
                + "\n".join(
                    f"    {e['id']} ({e['package']})" for e in shipped_exceptions
                )
            )

    if failures:
        print()
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1

    # Each tier reports only what it actually judged. "no unaccepted
    # advisories" after a run that found some in a closure it was not asked
    # about reads as a clean result, and a shipped run saying "accepted: none"
    # reads as "there are none" for a file it never opened.
    if args.tier == "shipped":
        print("\nno advisories in the shipped closures.")
    else:
        accepted_ids = ", ".join(sorted({e["id"] for e in ignores})) or "none"
        if args.tier == "development":
            print(
                "\nno unaccepted advisories in the development closure "
                f"(accepted: {accepted_ids}). The shipped closures were "
                "audited to resolve those exceptions and NOT judged; run "
                "--tier both or --tier shipped for a verdict on them."
            )
        else:
            print(
                "\nno unaccepted advisories. Accepted in the development "
                f"closure: {accepted_ids}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

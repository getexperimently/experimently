"""The values a run makes up or reads, and keeping them out of its run directory.

The run directory is uploaded as a public artifact (``docs-journeys.yml``), so
no credential a run handles may be written there. A run handles three kinds:

* the passwords a journey makes up (its file's ``passwords``), fresh each run;
* the values a ``keep`` step reads from a screen (the one-time password the
  dashboard shows when an administrator invites a user);
* the access tokens the runner signs in for, for an ``api`` step's caller.

Two things keep them out of the files. Every text the runner writes (ARIA
snapshots, api answers, the results log, the reports built from them) passes
through ``Redactor.redact``, which writes ``(redacted)`` where any of them
stood; a screenshot masks any element whose text holds one; and an api step's
value at a JSON path whose last key is in ``REDACTED_KEYS`` is written as
``(redacted)`` unless it is the value the journey file expects there (which is
public already). A value at a path in ``CREDENTIAL_KEYS`` is also kept out of
every later file; ``key`` is not one of those, because an experiment's or a
flag's ``key`` is no credential. Then, at the end of the run, ``clear`` reads
every file of the run directory, binary ones included, for each value (and its
JSON-escaped form): a file holding one is removed, the run fails
(``conftest.py``), and ``SCAN_RECORD`` is written last, naming only counts and
the removed files' paths. ``docs-journeys.yml`` uploads the run directory only
when that record exists, so a run that stopped before its scan uploads nothing.

The demo accounts' password is not one of these: the quick start prints it, and
a step may type it where its screen is kept.
"""

from __future__ import annotations

import json
import secrets
import string
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

REDACTED = "(redacted)"
#: An api step's value at a JSON path ending in one of these keys is never written.
REDACTED_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "key",
        "api_key",
        "password",
        "secret",
        "client_secret",
    }
)
#: Of those, the keys whose value is a credential, kept out of every later file too.
CREDENTIAL_KEYS = REDACTED_KEYS - {"key"}
#: Written last into the run directory by ``clear``: what the scan read and removed.
SCAN_RECORD = "secret-scan.json"
#: The shortest value a run keeps: a shorter one would redact ordinary words.
MIN_LENGTH = 8
PASSWORD_LENGTH = 20


def make_password(length: int = PASSWORD_LENGTH) -> str:
    """A fresh password that meets the account rules: upper, lower and a digit.

    The rules are ``docs/auth/auth-user-guide.md``'s: at least 8 characters, at
    most 72 bytes, an upper-case letter, a lower-case letter and a digit.
    """
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in value)
            and any(c.islower() for c in value)
            and any(c.isdigit() for c in value)
        ):
            return value


def redacted_path(path: str) -> bool:
    """True when an api step's value at *path* is written only if expected."""
    return path.rsplit(".", 1)[-1].lower() in REDACTED_KEYS


def credential_path(path: str) -> bool:
    """True when an api step's value at *path* is a credential, kept out of every file."""
    return path.rsplit(".", 1)[-1].lower() in CREDENTIAL_KEYS


class Redactor:
    """Every value the run must not write, and the text with them taken out."""

    def __init__(self) -> None:
        self.values: Set[str] = set()

    def add(self, value: str) -> None:
        """Keep *value* out of every file; ValueError when it is too short to."""
        if len(value) < MIN_LENGTH:
            raise ValueError(
                f"a value shorter than {MIN_LENGTH} characters cannot be kept out"
                " of the run's files"
            )
        self.values.add(value)

    def redact(self, text: str) -> str:
        for value in sorted(self.values, key=len, reverse=True):
            text = text.replace(value, REDACTED)
            escaped = json.dumps(value, ensure_ascii=False)[1:-1]
            if escaped != value:
                text = text.replace(escaped, REDACTED)
        return text


def _needles(values: Iterable[str]) -> Set[bytes]:
    found: Set[bytes] = set()
    for value in values:
        found.add(value.encode("utf-8"))
        found.add(json.dumps(value, ensure_ascii=False)[1:-1].encode("utf-8"))
        found.add(json.dumps(value)[1:-1].encode("utf-8"))
    return found


def scan(run_dir: Path, values: Iterable[str]) -> Tuple[int, List[str]]:
    """(files read, the files holding any of *values*): paths relative to *run_dir*."""
    needles = _needles(values)
    read = 0
    holding: List[str] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        read += 1
        data = path.read_bytes()
        if any(needle in data for needle in needles):
            holding.append(path.relative_to(run_dir).as_posix())
    return read, holding


def clear(run_dir: Path, values: Iterable[str]) -> Dict[str, object]:
    """Remove every file holding one of *values*, then write ``SCAN_RECORD``.

    The record names how many files were read, how many values were looked
    for and which files were removed; never a value.
    """
    kept = list(values)
    stale = run_dir / SCAN_RECORD
    if stale.is_file():
        stale.unlink()
    read, holding = scan(run_dir, kept)
    for name in holding:
        (run_dir / name).unlink()
    record: Dict[str, object] = {
        "files_read": read,
        "values": len(kept),
        "removed": holding,
    }
    stale.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record

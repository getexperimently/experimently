"""The values a run makes up or reads, and keeping them out of its run directory.

The run directory is uploaded as a public artifact (``docs-journeys.yml``), so
no credential a run handles may be written there. A run handles three kinds:

* the passwords a journey makes up (its file's ``passwords``), fresh each run;
* the values a ``keep`` step reads from a screen (the one-time password the
  dashboard shows when an administrator invites a user);
* credentials an api step is given: the access token the runner signs in for,
  for an ``api`` step's caller, and every value under a credential's key
  (``CREDENTIAL_KEYS``) anywhere in an api step's answer.

What keeps them out, in the order it acts:

1. Text. Every text the runner writes (ARIA snapshots, api answers, the results
   log, the reports built from them) passes through ``Redactor.redact``, which
   writes ``(redacted)`` where any of them stood: as written, JSON-escaped, or
   with its spaces changed to other whitespace (a line break, a run of spaces).
   An error line is redacted before it is cut to length, so a value is never
   cut in two and then missed. An api step's answer is written through
   ``scrub``: every value under a key in ``REDACTED_KEYS``, at any depth, in
   objects and in lists, is ``(redacted)`` unless it is the value the journey
   file expects there (which is public already); ``key`` is redacted that way
   but not looked for elsewhere, because an experiment's or a flag's ``key``
   is no credential.
2. Screens. A screenshot cannot be read for a value. So no screen is kept for a
   step that types a secret, for a ``keep`` step, or for the step right before
   one (the step whose screen shows what the keep reads); the loader refuses a
   journey that says otherwise. Any other screenshot masks every element whose
   text holds a kept value. A journey with a secret is never recorded whole
   (``video``); its walkthrough (``recording``) is recorded only over steps
   that cannot draw one (the loader's rules), and ``on_screen`` checks the page
   before the segment and after each of its steps: a value drawn anywhere but
   as a password field's dots fails the step and drops the recording.
3. The scan. At the end of the run ``clear`` reads every file of the run
   directory, byte by byte, for each value in the forms ``_needles`` lists. A
   file holding one is removed, and so are the screenshot beside it and the
   recordings of its journey (its video, and its walkthrough under
   ``recordings/``: ``owners`` says whose each is); the journeys it belongs to
   are reported FAIL in ``verdicts.json``, and the run fails
   (``conftest.py``). ``SCAN_RECORD`` is written last, naming only counts and
   paths. ``docs-journeys.yml`` uploads the run directory only when that record
   exists and names no removed file.

What the scan does not see: a value drawn in a screenshot or a video (pixels,
not bytes; rule 2 is what keeps screens clean), and a value written encoded
(base64, hex, URL-encoded), split across lines or fields, or cut short. Those
are kept out by rule 1, which writes no value at all, not by the scan. A
recording's caption bar draws only text the results log also holds (each
step's heading, action, and, for a step off the screen, its observed line,
all redacted), so the scan of ``results.jsonl`` reads what the captions drew.

The demo accounts' password is not one of these: the quick start prints it, and
a step may type it where its screen is kept.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

REDACTED = "(redacted)"
#: Under these keys, at any depth, an api step's value is written only if expected.
REDACTED_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "key",
        "api_key",
        "password",
        "new_password",
        "current_password",
        "temporary_password",
        "secret",
        "client_secret",
        "private_key",
    }
)
#: Of those, the keys whose value is a credential: also looked for in every file.
CREDENTIAL_KEYS = REDACTED_KEYS - {"key"}
#: Written last into the run directory by ``clear``: what the scan read and removed.
SCAN_RECORD = "secret-scan.json"
#: The shortest value a run keeps: a shorter one would redact ordinary words.
MIN_LENGTH = 8
PASSWORD_LENGTH = 20
#: The files a step's screen is kept in beside its text: removed with them.
TEXT_SUFFIXES = (
    ".expected.aria.yml",
    ".aria.yml",
    ".expected.json",
    ".observed.json",
    ".api.json",
    ".crawl.json",
)
_SPACE = re.compile(r"\s+")


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


def redacted_key(name: str) -> bool:
    return name.lower() in REDACTED_KEYS


def credential_key(name: str) -> bool:
    return name.lower() in CREDENTIAL_KEYS


def _last(path: str) -> str:
    return path.rsplit(".", 1)[-1]


def redacted_path(path: str) -> bool:
    """True when an api step's value at *path* is written only if expected."""
    return redacted_key(_last(path))


def credential_path(path: str) -> bool:
    """True when an api step's value at *path* is a credential, kept out of every file."""
    return credential_key(_last(path))


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

    def add_all(self, node: Any) -> None:
        """Keep every string of at least ``MIN_LENGTH`` in *node* out of every file."""
        if isinstance(node, str):
            if len(node) >= MIN_LENGTH:
                self.values.add(node)
        elif isinstance(node, dict):
            for value in node.values():
                self.add_all(value)
        elif isinstance(node, list):
            for value in node:
                self.add_all(value)

    def redact(self, text: str) -> str:
        for value in sorted(self.values, key=len, reverse=True):
            text = text.replace(value, REDACTED)
            escaped = json.dumps(value, ensure_ascii=False)[1:-1]
            if escaped != value:
                text = text.replace(escaped, REDACTED)
            parts = _SPACE.split(value.strip())
            if len(parts) > 1:
                # The same value with its spaces as any other whitespace: the
                # pieces are literal, so this cannot backtrack.
                pattern = r"\s+".join(re.escape(part) for part in parts)
                text = re.sub(pattern, REDACTED, text)
        return text


_ABSENT = object()


def _same(seen: Any, wanted: Any) -> bool:
    """Equal as JSON values, ``true`` not ``1`` (``checks.same_json``, recursive)."""
    if wanted is _ABSENT:
        return False
    if isinstance(seen, bool) or isinstance(wanted, bool):
        return isinstance(seen, bool) and isinstance(wanted, bool) and seen == wanted
    if isinstance(seen, dict) and isinstance(wanted, dict):
        return seen.keys() == wanted.keys() and all(
            _same(seen[k], wanted[k]) for k in seen
        )
    if isinstance(seen, list) and isinstance(wanted, list):
        return len(seen) == len(wanted) and all(
            _same(a, b) for a, b in zip(seen, wanted)
        )
    return seen == wanted


def scrub(
    path: str, value: Any, wanted: Any = _ABSENT, redactor: Optional[Redactor] = None
) -> Any:
    """*value*, found at *path* of an api step's answer, as it may be written.

    Every part of it under a key in ``REDACTED_KEYS`` (the path's own last key
    included), at any depth and in lists, becomes ``(redacted)`` unless it
    equals what the journey expects there (*wanted*, matched part by part). A
    part under a key in ``CREDENTIAL_KEYS`` also goes to *redactor*, so no
    later file holds it either.
    """

    def walk(node: Any, want: Any, name: Optional[str]) -> Any:
        if name is not None and redacted_key(name) and not _same(node, want):
            if redactor is not None and credential_key(name):
                redactor.add_all(node)
            return REDACTED
        if isinstance(node, dict):
            return {
                k: walk(
                    v, want.get(k, _ABSENT) if isinstance(want, dict) else _ABSENT, k
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [
                walk(
                    v,
                    want[i] if isinstance(want, list) and i < len(want) else _ABSENT,
                    None,
                )
                for i, v in enumerate(node)
            ]
        return node

    last = _last(path)
    return walk(value, wanted, None if last.isdigit() else last)


def register_credentials(document: Any, redactor: Redactor) -> None:
    """Send every value under a credential's key in *document* to *redactor*.

    An api step's whole answer goes through this, written or not, so a token a
    route answers with is looked for in every file the run writes after it.
    """
    if isinstance(document, dict):
        for key, value in document.items():
            if credential_key(str(key)):
                redactor.add_all(value)
            else:
                register_credentials(value, redactor)
    elif isinstance(document, list):
        for value in document:
            register_credentials(value, redactor)


def _needles(values: Iterable[str]) -> Set[bytes]:
    """The forms of each value the scan looks for: as written, JSON-escaped (with
    and without non-ASCII escaped), and with each run of whitespace made one
    space. Not base64, hex or URL-encoded forms, and not a value split across
    lines or cut short: see the module's docstring."""
    found: Set[bytes] = set()
    for value in values:
        for form in (
            value,
            json.dumps(value, ensure_ascii=False)[1:-1],
            json.dumps(value)[1:-1],
            _SPACE.sub(" ", value.strip()),
        ):
            if form:
                found.add(form.encode("utf-8"))
    return found


def scan(run_dir: Path, values: Iterable[str]) -> Tuple[int, List[str]]:
    """(files read, the files holding any of *values*): paths relative to *run_dir*.

    Byte for byte, in every file, in the forms ``_needles`` lists. A value drawn
    in a PNG or a video is pixels, not bytes, so it is not found here.
    """
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


#: The directory of the launch walkthroughs (``recordings.toml``) in a run.
RECORDINGS = "recordings"


def on_screen(
    text: str, fields: Sequence[Tuple[str, str]], values: Iterable[str]
) -> Optional[str]:
    """Where a page draws one of *values*, or None.

    *text* is the page's rendered text, *fields* each input's and text area's
    (type, value). A value typed into a ``password`` field is drawn as dots;
    in any other field, or in the text, it is drawn as it is. The answer names
    the place, never the value.
    """
    flat = _SPACE.sub(" ", text)
    for value in values:
        if not value:
            continue
        if value in text or _SPACE.sub(" ", value.strip()) in flat:
            return "the page's text"
        for kind, typed in fields:
            if value in typed and kind != "password":
                return f"a field of type {kind or 'text'}"
    return None


def _journey_of(name: str, owners: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """The journey a run-directory file belongs to, or None for a shared one.

    A walkthrough under ``recordings/`` is the journey *owners* names for it.
    """
    parts = name.split("/")
    if owners and name in owners:
        return owners[name]
    if len(parts) == 2 and parts[0] == "videos" and parts[1].endswith(".webm"):
        return parts[1][: -len(".webm")]
    if len(parts) > 1 and parts[0] not in ("videos", "stacks", RECORDINGS):
        return parts[0]
    for suffix in (".md", ".html"):
        if len(parts) == 1 and name.endswith(suffix) and name != "summary.md":
            return name[: -len(suffix)]
    return None


def journeys_of(
    removed: Sequence[str],
    journeys: Iterable[str],
    owners: Optional[Mapping[str, str]] = None,
) -> Set[str]:
    """The journeys whose files these are; every journey for a shared file."""
    known = set(journeys)
    found: Set[str] = set()
    for name in removed:
        journey = _journey_of(name, owners)
        if journey in known:
            found.add(journey)
        else:
            return known
    return found


def files_of(
    removed: Sequence[str], journey: str, owners: Optional[Mapping[str, str]] = None
) -> Tuple[str, ...]:
    """The removed files that are *journey*'s own, or shared by every journey."""
    return tuple(
        name for name in removed if _journey_of(name, owners) in (journey, None)
    )


def _screens_of(
    run_dir: Path, name: str, owners: Optional[Mapping[str, str]] = None
) -> List[Path]:
    """The screenshot beside a removed file, and its journey's recordings (or all)."""
    found: List[Path] = []
    for suffix in TEXT_SUFFIXES:
        if name.endswith(suffix):
            found.append(run_dir / (name[: -len(suffix)] + ".png"))
            break
    journey = _journey_of(name, owners)
    if journey is not None:
        found.append(run_dir / "videos" / f"{journey}.webm")
        found.extend(
            run_dir / file
            for file, owner in sorted((owners or {}).items())
            if owner == journey
        )
    else:
        found.extend(sorted((run_dir / "videos").glob("*.webm")))
        found.extend(sorted((run_dir / RECORDINGS).glob("*.webm")))
    return found


def clear(
    run_dir: Path,
    values: Iterable[str],
    earlier: Optional[Dict[str, Any]] = None,
    owners: Optional[Mapping[str, str]] = None,
) -> Dict[str, object]:
    """Remove every file holding one of *values*, with its screens; write ``SCAN_RECORD``.

    The record names how many files were read, how many values were looked
    for, which files held one (``removed``) and which screenshots and
    recordings went with them (``screens_removed``), with those of an
    *earlier* pass's record; never a value. *owners* maps each walkthrough
    under ``recordings/`` to the journey that recorded it.
    """
    earlier = earlier or {}
    kept = list(values)
    stale = run_dir / SCAN_RECORD
    if stale.is_file():
        stale.unlink()
    read, holding = scan(run_dir, kept)
    screens: Set[str] = set()
    for name in holding:
        (run_dir / name).unlink(missing_ok=True)
    for name in holding:
        for screen in _screens_of(run_dir, name, owners):
            if screen.is_file():
                screen.unlink()
                screens.add(screen.relative_to(run_dir).as_posix())
    record: Dict[str, object] = {
        "files_read": read,
        "values": len(kept),
        "removed": sorted(set(earlier.get("removed", [])) | set(holding)),
        "screens_removed": sorted(set(earlier.get("screens_removed", [])) | screens),
    }
    stale.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record

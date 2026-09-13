#!/usr/bin/env python3
"""Print the Python packages the *full* API image ships and the *core* one must not.

The set is derived, never hand-kept: it is every distribution pinned in
``modules/requirements.lock`` that ``backend/requirements/runtime.lock`` does
not pin.  Those two locks are exactly what ``backend/Dockerfile`` installs --
the ``core`` stage installs the first, the ``full`` stage installs both -- so
the difference between them *is* "what the full profile adds".

Why derive it.  The ``docker-smoke`` job used to assert the core image carried
none of six names typed out by hand (``onelogin``, ``authlib``, ``pymysql``,
``clickhouse_connect``, ``databricks``, ``modules``).  A hand-kept list goes
stale the moment a dependency moves, and it had: ``requests`` and
``defusedxml`` sat in the core image although their only runtime importer is
``modules/backend/app/services/sso_service.py``, and neither name was on the
list to catch it.  Derived, the same check also covers the transitive closure
(``lxml``, ``xmlsec``, ``pyarrow``, ``thrift``, ``oauthlib`` ...), which no one
would have typed out.

Names are distribution names (``python3-saml``), canonicalised the way
:pep:`503` says, not import names (``onelogin``) -- so the check that consumes
this list asks ``importlib.metadata`` what is installed rather than trying to
import a guessed module name.

Usage::

    python scripts/module_only_packages.py          # one name per line
    python scripts/module_only_packages.py --oneline  # space-separated

Exit status 0 with the list, 1 when either lock is missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_requirements_lock import ROOT, lock_entries

CORE_LOCK = ROOT / "backend" / "requirements" / "runtime.lock"
MODULES_LOCK = ROOT / "modules" / "requirements.lock"


def module_only_packages() -> list[str]:
    """Canonical distribution names only the full image installs."""
    core, _ = lock_entries(CORE_LOCK)
    modules, _ = lock_entries(MODULES_LOCK)
    return sorted(set(modules) - set(core))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--oneline",
        action="store_true",
        help="print the names space-separated on a single line",
    )
    args = parser.parse_args()

    for lock in (CORE_LOCK, MODULES_LOCK):
        if not lock.exists():
            print(
                f"{lock.relative_to(ROOT)} is missing; run `make lock`", file=sys.stderr
            )
            return 1

    names = module_only_packages()
    if not names:
        print(
            "the modules lock adds nothing the core lock does not already pin; "
            "that cannot be right while modules/requirements.txt has pins",
            file=sys.stderr,
        )
        return 1
    print(" ".join(names) if args.oneline else "\n".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())

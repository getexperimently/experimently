"""Seal a core tree off from the checkout it was copied from.

Not a test module.  ``tree_profiles.core_tree`` copies this file into the tree
it builds as ``sitecustomize.py``, which ``site`` imports in every interpreter
started there -- after it has processed the ``.pth`` files, so after an editable
install has appended its finder to ``sys.meta_path``.  :func:`seal` then takes
away every route to the checkout's ``modules`` package and ``backend.*``
children the copy does not have.

Two rules shape it:

* **It may only fail by ``SystemExit``.**  ``site`` catches ``Exception`` from
  a ``sitecustomize``, prints "Error in sitecustomize" and carries on -- with
  the leak intact and exit status 0.  An ``assert`` is worse still: ``-O``
  deletes it.  So the whole body is wrapped and every failure leaves as
  ``SystemExit``, which ``site`` does not catch.
* **It does not import ``backend``.**  It locates packages and asks finders,
  and runs no package code, so what it checks is the tree before anything
  in it has run.

Standard library only: it runs before anything else is importable on purpose.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys

#: What a core tree must not reach outside itself.  ``backend.tests`` stands for
#: the ``backend.*`` children the copy leaves out; setuptools' editable finder
#: maps any child of a package it knows back into the checkout.
_NAMES = ("modules", "backend", "backend.tests")


def _inside(path: str, root: str) -> bool:
    real = os.path.realpath(path)
    return real == root or real.startswith(root + os.sep)


def _foreign_finders(root: str) -> list:
    """Every meta-path finder but ``PathFinder`` that resolves one of _NAMES."""
    found = []
    for finder in sys.meta_path:
        if finder is importlib.machinery.PathFinder:
            continue
        find = getattr(finder, "find_spec", None)
        if find is None:
            continue
        if any(find(name, None) is not None for name in _NAMES):
            found.append(finder)
    return found


def _seal(root: str) -> None:
    if os.path.isdir(os.path.join(root, "modules")):
        raise SystemExit(
            f"core-tree guard: {root} has a modules directory; a core tree must not"
        )

    sys.path[:] = [
        entry
        for entry in sys.path
        if _inside(entry or os.curdir, root)
        or not os.path.isdir(os.path.join(entry, "modules"))
    ]
    for finder in _foreign_finders(root):
        sys.meta_path.remove(finder)
    importlib.invalidate_caches()

    spec = importlib.util.find_spec("modules")
    if spec is not None:
        raise SystemExit(f"core-tree guard: `modules` still resolves, to {spec.origin}")
    spec = importlib.util.find_spec("backend")
    outside = [
        p
        for p in (spec.submodule_search_locations if spec else None) or []
        if not _inside(p, root)
    ]
    if spec is None or outside:
        raise SystemExit(f"core-tree guard: `backend` resolves outside {root}: {spec}")
    if _foreign_finders(root):
        raise SystemExit(f"core-tree guard: a finder outside {root} survived removal")


def seal(root: str) -> None:
    """Make *root* the only place ``modules`` and ``backend`` can come from."""
    try:
        _seal(os.path.realpath(root))
    except SystemExit:
        raise
    except BaseException as exc:
        raise SystemExit(f"core-tree guard: {type(exc).__name__}: {exc}") from None


if __name__ == "sitecustomize":
    seal(os.path.dirname(os.path.abspath(__file__)))

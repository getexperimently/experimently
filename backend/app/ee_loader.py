"""Load the Enterprise Edition into the Community application, if present.

This is the only module in ``backend/app`` that knows the ``ee`` package can
exist, and it never imports anything from it by name: it imports the top-level
package and calls its ``register(hooks)`` entry point, which fills in the hooks
in :mod:`backend.app.core.hooks`.  A Community build has no ``ee`` package,
:func:`load_enterprise` finds nothing, and every hook keeps its CE default.

Called from the four places that build an application or a schema:

* ``backend/app/main.py``       — the running API,
* ``backend/app/db/bootstrap.py`` — ``create_all`` on a fresh database,
* ``backend/app/db/migrations/env.py`` — alembic's ``target_metadata``,
* ``backend/tests/conftest.py`` — the test schema.

Loading is idempotent and never raises: an Enterprise package that fails to
import must not take the Community API down with it, so the failure is logged
at ERROR -- with the traceback, because an Enterprise deployment silently
degrading to Community is not a state an operator should have to discover from
a 403 -- and the process continues as Community.

TRANSITIONAL: while the Enterprise modules still live in this tree (issue
#89), ``ee/`` holds only a LICENSE and imports as a namespace package with no
``register``.  The loader then falls back to ``backend.app.ee_transitional``,
which has the shape ``ee/backend/app/register.py`` will have and is listed in
``ee-manifest.txt`` so a Community build deletes it.  Once the move lands, the
fallback finds nothing and this paragraph goes.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: Top-level package name of the Enterprise Edition.
EE_PACKAGE = "ee"

_lock = threading.RLock()
_state: Optional[bool] = None
#: Set when Enterprise code was *found* but failed to register; None when it
#: loaded or when there was nothing to load.  Schema builders read this.
_failure: Optional[str] = None


def load_enterprise(force: bool = False) -> bool:
    """Register the Enterprise edition's hooks. Returns True when it loaded.

    Idempotent: the result is cached so the call sites can each call it
    unconditionally.  Pass ``force=True`` to re-run it (tests).  Never raises
    -- see :func:`require_enterprise_or_absent` for the callers that must not
    continue on a failure.
    """
    global _state
    with _lock:
        if _state is not None and not force:
            return _state

        _state = _load()
        return _state


def enterprise_failure() -> Optional[str]:
    """Why the Enterprise edition did not load, or None."""
    with _lock:
        return _failure


def require_enterprise_or_absent() -> bool:
    """Load the Enterprise edition, and raise if it was found but failed.

    For the callers that build a *schema* from ``Base.metadata`` -- alembic's
    ``env.py``, ``db/bootstrap.py``, the test conftest.  The running API may
    degrade to Community when the Enterprise registration fails; a schema
    tool must not: with only the Community models registered, ``alembic
    revision --autogenerate`` proposes dropping every Enterprise table and
    ``upgrade head`` then does it, and a bootstrap creates a database the
    Enterprise routers cannot serve.  Silence there is data loss.

    Returns True when Enterprise loaded and False when there was nothing to
    load (a Community tree); raises RuntimeError otherwise.
    """
    loaded = load_enterprise()
    failure = enterprise_failure()
    if failure is not None:
        raise RuntimeError(
            "Enterprise code is present but failed to register, so Base.metadata "
            "holds only the Community tables; refusing to build a schema from "
            f"it. Cause: {failure}"
        )
    return loaded


#: Dotted path of the in-tree fallback (see the module docstring).
TRANSITIONAL_MODULE = "backend.app.ee_transitional"


def _find_register() -> tuple[Optional[Callable[[Any], None]], Optional[str]]:
    """The ``register(hooks)`` callable to run, and where it came from.

    Never raises.  Importing the Enterprise package runs Enterprise code, and
    a SyntaxError or a RuntimeError from a missing optional dependency must
    not take ``import backend.app.main`` down with it.  A
    ``ModuleNotFoundError`` for *another* module raised from inside the
    package is a broken Enterprise install, not the absence of one, and is
    logged as such rather than mistaken for Community.
    """
    global _failure
    try:
        ee = importlib.import_module(EE_PACKAGE)
    except ModuleNotFoundError as exc:
        if exc.name == EE_PACKAGE:
            logger.debug("No %s package on the path", EE_PACKAGE)
            ee = None
        else:
            # A module *inside* the package is missing: a broken Enterprise
            # install, not the absence of one.  Do not fall through to the
            # in-tree code -- serving that in place of the package the operator
            # installed would hide the breakage behind an "Enterprise edition
            # loaded" line.
            _failure = f"{EE_PACKAGE} imports {exc.name!r}, which is not installed"
            logger.exception(
                "%s is present but importing it failed on %r; continuing as "
                "Community edition",
                EE_PACKAGE,
                exc.name,
            )
            return None, None
    except Exception as exc:
        _failure = f"{EE_PACKAGE} could not be imported: {exc!r}"
        logger.exception(
            "%s is present but could not be imported; continuing as Community edition",
            EE_PACKAGE,
        )
        return None, None
    else:
        register = getattr(ee, "register", None)
        if register is not None:
            return register, EE_PACKAGE
        # The entry point may live in the package's application module rather
        # than be re-exported from the top level: ee/backend/app/register.py.
        try:
            module = importlib.import_module(f"{EE_PACKAGE}.backend.app.register")
        except ModuleNotFoundError as exc:
            if exc.name not in (
                f"{EE_PACKAGE}.backend",
                f"{EE_PACKAGE}.backend.app",
                f"{EE_PACKAGE}.backend.app.register",
            ):
                _failure = f"{EE_PACKAGE}.backend.app.register imports {exc.name!r}"
                logger.exception("%s.backend.app.register failed to import", EE_PACKAGE)
                return None, None
        except Exception as exc:
            _failure = (
                f"{EE_PACKAGE}.backend.app.register could not be imported: {exc!r}"
            )
            logger.exception("%s.backend.app.register failed to import", EE_PACKAGE)
            return None, None
        else:
            register = getattr(module, "register", None)
            if register is not None:
                return register, f"{EE_PACKAGE}.backend.app.register"
        # A bare `ee/` directory (the repository keeps one holding only the
        # Enterprise LICENSE) imports as a namespace package.  That is the
        # normal Community state.  A package that *has* code but no entry
        # point anywhere is a misconfiguration and is said so at WARNING: a
        # licensed deployment would otherwise start as Community with only a
        # DEBUG line to explain it.
        if _has_python_code(ee):
            logger.warning(
                "%s has code but exposes no register(hooks) entry point (looked "
                "at %s.register and %s.backend.app.register); running Community "
                "edition",
                EE_PACKAGE,
                EE_PACKAGE,
                EE_PACKAGE,
            )
        else:
            logger.debug(
                "%s is a bare directory; running Community edition", EE_PACKAGE
            )

    # TRANSITIONAL fallback: the Enterprise modules still in this tree.  A
    # failure to import it is recorded in `_failure` exactly like a broken
    # `ee` package: it is the one registration path this tree has, and the
    # strict schema builders must refuse rather than build 37 tables.
    try:
        transitional = importlib.import_module(TRANSITIONAL_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name == TRANSITIONAL_MODULE:
            return None, None  # deleted: a Community tree
        _failure = f"{TRANSITIONAL_MODULE} imports {exc.name!r}, which is not installed"
        logger.exception("%s failed to import", TRANSITIONAL_MODULE)
        return None, None
    except Exception as exc:
        _failure = f"{TRANSITIONAL_MODULE} could not be imported: {exc!r}"
        logger.exception("%s failed to import", TRANSITIONAL_MODULE)
        return None, None
    return getattr(transitional, "register", None), TRANSITIONAL_MODULE


def _has_python_code(package: Any) -> bool:
    """Whether *package* (a namespace package, usually) holds any ``.py`` file."""
    for location in getattr(package, "__path__", None) or ():
        for root, _dirs, files in os.walk(location):
            if any(name.endswith(".py") for name in files):
                return True
    return False


def _load() -> bool:
    global _failure
    from backend.app.core import hooks

    _failure = None
    register, origin = _find_register()
    if register is None:
        logger.debug("Running Community edition")
        return False

    # Everything from here on is Enterprise code running inside the Community
    # process.  *Any* exception -- ImportError from a model module, a missing
    # optional dependency raised as RuntimeError, a SyntaxError -- is caught:
    # the loader's one promise is that the Community API starts.
    try:
        register(hooks)
        # Model modules are imported here rather than by the EE package so
        # that a loader run before `Base.metadata` is consumed still registers
        # the tables.
        hooks.import_registered_models()
    except Exception as exc:
        _failure = f"{origin}.register(hooks) raised {exc!r}"
        logger.exception(
            "%s.register(hooks) failed; continuing as Community edition. "
            "Enterprise features will answer 403/501 until this is fixed.",
            origin,
        )
        # Clear the registries so no router is served against tables that do
        # not exist.  This cannot un-import a model module that was imported
        # before the failing one -- Python has no such thing -- so
        # Base.metadata may still carry some Enterprise tables; that is why
        # schema builders go through require_enterprise_or_absent() and refuse
        # to build from a metadata in this state.
        hooks.reset()
        return False

    logger.info("Enterprise edition loaded (from %s)", origin)
    return True


def reset() -> None:
    """Forget the cached load result (tests only)."""
    global _state, _failure
    with _lock:
        _state = None
        _failure = None

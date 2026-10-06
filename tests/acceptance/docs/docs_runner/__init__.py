"""The docs-journey runner (#939): walks a guide in a browser against a stack.

A journey is one YAML file under ``tests/acceptance/docs/journeys/``, written
before the first run, that says for each step of a guide what to do, what the
reader should then see, and what failure looks like. ``model`` is its schema,
``loader`` reads one and refuses what the runner will not run, ``log`` and
``report`` write the results, ``stacks`` brings up what a journey runs
against, ``execute`` drives the browser, and ``checks`` holds what it writes
and compares without one.

``model``, ``registry``, ``guide``, ``loader``, ``checks``, ``log``, ``report``
and ``oracles`` import neither Playwright nor anything from ``backend``, so
their unit tests run in the backend's unit job
(``backend/tests/unit/docs/test_docs_journey_runner.py``).
"""

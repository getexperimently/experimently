"""Showcase videos (#1066): a local tool that records captioned product walkthroughs.

It runs on a developer's own machine, never in CI. Two halves meet at one
directory, described and checked by ``showcase.contract``:

* the capture records a walkthrough against a throwaway local stack and writes
  a capture directory (frames, cues, the values it must never show, and the
  numbers of its own gates);
* the render (``showcase.render``) turns that directory into a captioned
  1920x1080 MP4, a WebVTT file from the same cues, and a review page.

Import it as ``showcase`` with ``tests/acceptance`` on ``sys.path`` (the unit
tests under ``backend/tests/unit/showcase`` do exactly that), for example::

    cd tests/acceptance && python -m showcase.render <capture dir> --out <dir>
"""

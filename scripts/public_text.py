"""What a deploy script may print where anyone can read it.

The deploy, rollback and migration workflows run in a public repository, so
their logs, annotations and step summaries are public. The account ID is an
environment secret, which the runner masks in the log, but whether that mask
also reaches annotations and step summaries is not something these scripts
rely on. So a script that prints a resource names it without the account:

* ``short_arn``: a task definition by ``family:revision``, any other ARN by
  its resource part (``targetgroup/name/id``, ``service/cluster/name``);
* ``short_image``: an image by ``repository@sha256:...`` or
  ``repository:tag``, with the registry host (``<account>.dkr.ecr...``)
  removed;
* ``redact``: free text from AWS -- an error message, a stopped task's
  reason -- with every run of exactly twelve digits replaced.
"""

from __future__ import annotations

import re

#: Twelve digits with no word character on either side: an account ID in an
#: ARN (between colons) or a registry host (before a dot). Not a run inside a
#: longer number, and not one inside a hex digest.
_ACCOUNT_ID = re.compile(r"(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])")


def redact(text: object) -> str:
    """``text`` with every account-ID-shaped run of digits replaced."""
    return _ACCOUNT_ID.sub("<account>", str(text))


def short_arn(arn: object) -> str:
    """A task definition's ``family:revision``; any other ARN's resource part."""
    text = str(arn or "")
    if not text.startswith("arn:"):
        return redact(text)
    resource = text.split(":", 5)[-1]
    if resource.startswith("task-definition/"):
        return resource.rsplit("/", 1)[-1]
    return redact(resource)


def short_image(image: object) -> str:
    """The image without its registry host: ``repository@sha256:...``."""
    text = str(image or "")
    first, sep, rest = text.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return redact(rest)
    return redact(text)

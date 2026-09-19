#!/usr/bin/env python3
"""Assert a published image's OCI labels, from the registry.

``.github/workflows/release.yml`` runs this against every image it has just
pushed, before signing it.  The labels are the only place the version appears
outside the tag -- ``docker inspect`` is what an operator reaches for to answer
"what is this container" -- and they are set from a build argument, so a
renamed ``ARG`` in either Dockerfile would leave every released image labelled
``0.0.0+unknown`` with nothing else in the pipeline noticing.

Input is ``docker buildx imagetools inspect <ref> --format '{{ json .Image }}'``,
whose shape depends on the manifest:

* single platform -> one image config object (``{"created":…, "config":…}``);
* several         -> a map of ``"linux/amd64"`` -> that object.

Both are handled, and every platform is checked: an image whose arm64 variant
was built without the argument is exactly the defect this catches.  Verified
against a real registry in both shapes -- and buildx's provenance and SBOM
attestation manifests, which ride along in the same index, do *not* appear
here, so they need no special case.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: The label an image built with no ``--build-arg VERSION`` carries. Refused
#: explicitly rather than merely failing the comparison, so the error says what
#: went wrong instead of only that two strings differ.
PLACEHOLDER_VERSION = "0.0.0+unknown"


def image_configs(data: object) -> list[dict]:
    """The per-platform image configs in ``{{ json .Image }}`` output."""
    if not isinstance(data, dict):
        raise SystemExit(f"expected a JSON object, got {type(data).__name__}")
    # A single-platform config has "config" at the top level; a multi-platform
    # map has platform strings as its keys.
    if "config" in data or "rootfs" in data:
        return [data]
    configs = [value for value in data.values() if isinstance(value, dict)]
    if not configs:
        raise SystemExit(f"no image configs in {sorted(data)}")
    return configs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="The imagetools JSON.")
    parser.add_argument("--version", required=True, help="The version the tag claims.")
    parser.add_argument("--profile", required=True, choices=["core", "full"])
    args = parser.parse_args()

    if args.version == PLACEHOLDER_VERSION:
        print(
            f"error: asked to confirm the placeholder version {PLACEHOLDER_VERSION!r}, "
            "which no release may carry.",
            file=sys.stderr,
        )
        return 1

    configs = image_configs(json.loads(args.file.read_text(encoding="utf-8")))
    wanted = {
        "org.opencontainers.image.version": args.version,
        "org.opencontainers.image.licenses": "Apache-2.0",
        "io.experimently.profile": args.profile,
    }

    failures: list[str] = []
    for index, config in enumerate(configs):
        platform = f"{config.get('os', '?')}/{config.get('architecture', '?')}"
        labels = (config.get("config") or {}).get("Labels") or {}
        for key, value in wanted.items():
            actual = labels.get(key)
            if actual != value:
                failures.append(
                    f"  {platform} (#{index}): {key} = {actual!r}, expected {value!r}"
                )

    if failures:
        print("error: image labels are wrong:", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1

    print(f"{len(configs)} platform config(s) carry the expected labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())

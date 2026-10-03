#!/usr/bin/env python3
"""Assert that the image a release pushed is the image it scanned.

``.github/workflows/release.yml`` builds each image twice in one builder: once
with ``load: true`` into the runner's Docker, where the credential scans read
it, and once with ``push: true`` to the registry. The second build is served
from the first one's cache, so the layers should be the same bytes -- but
"should" is the kind of claim this repository keeps finding false, and a cache
miss between the two would push layers nobody scanned. So, after the push,
this compares

* the loaded image's layer list, ``docker image inspect <tag>`` ->
  ``[0].RootFS.Layers``, with
* the pushed image's, ``docker buildx imagetools inspect <ref>@<digest>
  --format '{{ json .Image }}'`` -> ``rootfs.diff_ids``.

Both are uncompressed layer digests (diff IDs), so they are comparable
directly. They must be non-empty and equal, in order.

The registry's view is one image config at the top level for a
single-platform image, or a map of platform -> config for several. The load
build holds one platform, so a map with more than one config is refused: which
of them was scanned would be a guess.

Exit status: 0 equal; 1 different; 2 an input it cannot read. Fails closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"::error::cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def _digests(value: object, where: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(
            isinstance(item, str) and item.startswith("sha256:") for item in value
        )
    ):
        print(
            f"::error::{where} is not a non-empty list of sha256 digests",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return list(value)


def loaded_layers(data: object) -> list[str]:
    """``RootFS.Layers`` from ``docker image inspect`` output (a one-item list)."""
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        print(
            "::error::expected `docker image inspect` output for exactly one image",
            file=sys.stderr,
        )
        raise SystemExit(2)
    rootfs = data[0].get("RootFS")
    return _digests(
        rootfs.get("Layers") if isinstance(rootfs, dict) else None,
        "the loaded image's RootFS.Layers",
    )


def pushed_layers(data: object) -> list[str]:
    """``rootfs.diff_ids`` from ``imagetools inspect --format '{{ json .Image }}'``."""
    if not isinstance(data, dict):
        print(
            "::error::expected the registry's image config as a JSON object",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if "rootfs" in data:
        config = data
    else:
        configs = [
            value
            for value in data.values()
            if isinstance(value, dict) and "rootfs" in value
        ]
        if len(configs) != 1:
            print(
                f"::error::the pushed image has {len(configs)} platform configs; the scanned image had one",
                file=sys.stderr,
            )
            raise SystemExit(2)
        config = configs[0]
    rootfs = config.get("rootfs")
    return _digests(
        rootfs.get("diff_ids") if isinstance(rootfs, dict) else None,
        "the pushed image's rootfs.diff_ids",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--loaded", type=Path, required=True, help="docker image inspect output"
    )
    parser.add_argument(
        "--pushed", type=Path, required=True, help="imagetools inspect .Image output"
    )
    args = parser.parse_args(argv)

    loaded = loaded_layers(_read(args.loaded))
    pushed = pushed_layers(_read(args.pushed))
    if loaded == pushed:
        print(f"the pushed image is the scanned image: {len(pushed)} layers, identical")
        return 0
    print(
        f"::error title=Pushed image differs from the scanned image::"
        f"scanned {len(loaded)} layers, pushed {len(pushed)}; the pushed layers were not scanned"
    )
    width = max(len(loaded), len(pushed))
    for index in range(width):
        left = loaded[index] if index < len(loaded) else "-"
        right = pushed[index] if index < len(pushed) else "-"
        mark = "  " if left == right else "!="
        print(f"{mark} {index:3d} scanned {left}  pushed {right}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

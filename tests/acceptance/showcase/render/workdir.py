"""The render's work directory, and the one place the render deletes anything (EM condition 7e).

Everything the render makes goes into its work directory first: the caption
PNGs, the frame sequence, the OCR batches, the ``.partial`` MP4 and WebVTT
file and the review page. The finished files reach the output directory only
by a hard link or a rename, after every gate passed, and the render never
deletes anything there. So the paths gate keeps the two apart (neither may be
inside the other, and they must be one filesystem for the link), and
``WorkDir.remove`` is the only code in the render that deletes. It refuses:

* anything that is not the work directory or inside it, except the capture's
  ``needles.txt``, the one file the contract hands the render to delete
  (matched as that exact path; a link there is removed, never followed);
* anything at all while the work directory is inside a git checkout, or is
  the filesystem root or the home directory.

A symbolic link is removed as a link: what it points to is never followed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional

from showcase.render.gates import Refused


def git_checkout_above(path: Path) -> Optional[Path]:
    """The git checkout a path is inside, if any (a ``.git`` in it or an ancestor)."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _where(path: Path) -> Path:
    """Where *path* is on disk; for a link, where the link itself is."""
    path = Path(path)
    if path.is_symlink():
        return Path(os.path.realpath(path.parent)) / path.name
    return Path(os.path.realpath(path))


class WorkDir:
    """The render's scratch directory: ``work.path`` to write in, ``work.remove`` to delete."""

    def __init__(self, path: Path, *, needles: Path) -> None:
        self.path = Path(os.path.realpath(Path(path).expanduser()))
        self.needles = _where(needles)

    def remove(self, target: Path) -> None:
        """Delete *target* (a file, a link or a tree), or refuse."""
        target = Path(target)
        where = _where(target)
        if where == self.needles:
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                raise Refused(
                    "delete", f"refusing to delete {target}: needles.txt is not a file"
                )
            return
        checkout = git_checkout_above(self.path)
        if checkout is not None:
            raise Refused(
                "delete",
                f"refusing to delete {target}: the work directory {self.path} "
                f"is inside the git checkout at {checkout}",
            )
        if self.path == Path(self.path.anchor) or self.path == Path(
            os.path.realpath(Path.home())
        ):
            raise Refused(
                "delete",
                f"refusing to delete {target}: the work directory {self.path} is too broad",
            )
        if where != self.path and self.path not in where.parents:
            raise Refused(
                "delete",
                f"refusing to delete {target}: it is not in the work directory {self.path}",
            )
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

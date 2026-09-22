#!/usr/bin/env python3
"""Every commit in a pull request carries a Developer Certificate of Origin sign-off.

``CONTRIBUTING.md`` tells contributors "A pull request with unsigned commits
will be blocked by the DCO check until every commit carries a sign-off".  Until
this script existed, that sentence was false: there was no DCO check anywhere
in the repository and no app installed.  A contributor-facing promise about
observable behaviour has to be enforced or rewritten as intent, and the promise
is the one we want, so this enforces it.

WHAT IS CHECKED

Each non-merge commit in the range must carry a ``Signed-off-by:`` trailer
whose e-mail matches the commit's author.  That is the whole of the DCO: the
author asserts they have the right to submit the change under the licence of
the file they are touching.

Merge commits are exempt.  A contributor who merges ``main`` into their branch
authored none of the content, and requiring a sign-off there would teach people
to sign off on other people's work -- the opposite of what the certificate
says.

**Named bot commits are exempt.**  Dependabot *does* add a trailer, but it does
not match its own author: the commit is authored by
``49699333+dependabot[bot]@users.noreply.github.com`` and signed off by
``support@github.com``.  A strict comparison therefore rejects every Dependabot
pull request, which this repository has a great many of -- measured, not
assumed; the first version of this script did exactly that.  A bot also cannot
certify the origin of anything: the human who reviews and merges the pull
request is the one taking responsibility.

The exemption is an explicit list of author addresses (``_BOT_AUTHORS``), not a
pattern.  An earlier version exempted anything matching ``*[bot]@users.noreply.github.com``
and claimed that could not be spoofed.  That was wrong, and measurably so::

    GIT_AUTHOR_EMAIL='evil[bot]@users.noreply.github.com' git commit -m 'no signoff'
    check_dco.py --range main~1..main
    -> bot  b67a17d4 evil[bot]@users.noreply.github.com
       all 0 commit(s) carry a matching sign-off (1 bot commit(s) exempt)
       exit 0

One environment variable turned the gate off.  The list closes that; adding a
bot to it is a reviewed change to this file.

**What this check is and is not.**  Git metadata is self-asserted: nothing here
verifies that an author address belongs to whoever pushed it, and a sign-off is
a line of text anybody can type.  That is true of the DCO GitHub App too, and
of the certificate itself -- the DCO is a *statement* a contributor makes, and
the check exists so the statement is present and attributable, not so it is
cryptographically proven.  Treat it as a process gate, not an access control.

Comparison is on the **e-mail**, case-insensitively, and not on the display
name.  Names legitimately differ in punctuation between a git config and a
sign-off (``O'Brien`` vs ``OBrien``, ``Ana María`` vs ``Ana Maria``), and
rejecting those teaches contributors that the gate is broken rather than that
their commit is.  The e-mail is the identifier the certificate turns on.

Usage::

    scripts/check_dco.py <base> <head>      # a commit range, as CI passes it
    scripts/check_dco.py --range main..HEAD # the same thing, spelled as a range

Exit status is 0 when every commit is signed, 1 when any is not, and 2 when the
range could not be read -- an unreadable range is never a pass.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import List

#: Separates the fields of one commit in the `git log` format below.  A unit
#: separator because it is vanishingly unlikely in a commit message -- not
#: impossible: git permits any byte but NUL, so the split below is bounded by
#: maxsplit rather than trusting this.
_FIELD = "\x1f"
#: Separates commits.  A record separator, for the same reason.
_RECORD = "\x1e"

#: Author addresses whose commits do not need a sign-off, by name rather than
#: by pattern -- see the module docstring for why a pattern was wrong. These
#: are the GitHub apps that open pull requests against this repository;
#: `git log main --format=%ae | grep 'bot]' | sort -u` lists what is actually
#: in the history.
_BOT_AUTHORS = frozenset(
    {
        "49699333+dependabot[bot]@users.noreply.github.com",
        "dependabot[bot]@users.noreply.github.com",
        "41898282+github-actions[bot]@users.noreply.github.com",
        "github-actions[bot]@users.noreply.github.com",
    }
)


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    committer_email: str
    signoffs: List[str]

    @property
    def is_bot(self) -> bool:
        """Is this commit authored by one of the named GitHub apps?"""
        return self.author_email.strip().lower() in _BOT_AUTHORS

    @property
    def is_signed(self) -> bool:
        """Does any sign-off match the author **or** the committer?

        Either, not just the author, for a reason the first version got wrong:
        ``git commit -s`` writes the *committer's* identity into the trailer.
        On a commit whose author is someone else -- a maintainer rebasing a
        contributor's branch, ``git commit --author=``, a patch applied with
        ``git am`` -- author and sign-off differ by construction, and the
        remedy this script prints (``git rebase --signoff``) cannot fix it,
        because that writes the committer too. A contributor would be left with
        a red required check and no documented way out.

        The DCO GitHub App accepts author or committer for the same reason, so
        this keeps the two interchangeable.
        """
        identities = {
            self.author_email.strip().lower(),
            self.committer_email.strip().lower(),
        }
        return any(s.strip().lower() in identities for s in self.signoffs)

    @property
    def needs_signoff(self) -> bool:
        return not self.is_bot

    @property
    def short(self) -> str:
        return self.sha[:8]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.stdout


def _emails_from_trailers(raw: str) -> List[str]:
    """Pull the e-mail out of each ``Signed-off-by`` trailer value.

    `git log --format=%(trailers:key=Signed-off-by,valueonly)` gives one value
    per line, each shaped ``Some Name <addr@example.com>``.
    """
    emails = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        start, end = line.rfind("<"), line.rfind(">")
        if start != -1 and end > start:
            emails.append(line[start + 1 : end])
    return emails


def commits_in(base: str, head: str) -> List[Commit]:
    """Every non-merge commit reachable from *head* but not *base*."""
    fmt = (
        _FIELD.join(
            ["%H", "%ae", "%an", "%ce", "%(trailers:key=Signed-off-by,valueonly)"]
        )
        + _RECORD
    )
    out = _git("log", "--no-merges", f"--format={fmt}", f"{base}..{head}")

    commits = []
    for record in out.split(_RECORD):
        record = record.strip("\n")
        if not record.strip():
            continue
        # maxsplit: a trailer VALUE may contain the separator. Git permits any
        # byte but NUL in a commit message, so the earlier comment claiming
        # otherwise was wrong and an unlucky message crashed the gate with a
        # traceback as its contributor-facing output.
        sha, email, name, committer, trailers = record.split(_FIELD, 4)
        commits.append(
            Commit(
                sha=sha,
                author_name=name,
                author_email=email,
                committer_email=committer,
                signoffs=_emails_from_trailers(trailers),
            )
        )
    return commits


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", nargs="?", help="the base commit (exclusive)")
    parser.add_argument("head", nargs="?", help="the head commit (inclusive)")
    parser.add_argument("--range", dest="rev_range", help="base..head")
    args = parser.parse_args(argv)

    if args.rev_range:
        # `...` is git's symmetric difference, and `"a...b".split("..", 1)`
        # gives ("a", ".b"), which re-joins to `a...b` -- which git accepts.
        # The result was "no non-merge commits; nothing to sign off", exit 0:
        # the vacuous pass this script has an explicit test against.
        if "..." in args.rev_range:
            print(
                f"--range takes a two-dot range, got {args.rev_range!r}. `...` is "
                "a symmetric difference and would silently check nothing.",
                file=sys.stderr,
            )
            return 2
        if ".." not in args.rev_range:
            print(f"--range needs base..head, got {args.rev_range!r}", file=sys.stderr)
            return 2
        base, head = args.rev_range.split("..", 1)
        if not base or not head:
            print(f"--range needs both ends, got {args.rev_range!r}", file=sys.stderr)
            return 2
    elif args.base and args.head:
        base, head = args.base, args.head
    else:
        parser.print_usage(sys.stderr)
        return 2

    try:
        commits = commits_in(base, head)
    except RuntimeError as exc:
        print(f"could not read {base}..{head}: {exc}", file=sys.stderr)
        return 2

    if not commits:
        # Nothing to certify.  A pull request of only merge commits is the
        # normal way this happens.
        print(f"no non-merge commits in {base}..{head}; nothing to sign off")
        return 0

    unsigned = [c for c in commits if c.needs_signoff and not c.is_signed]

    for commit in commits:
        if not commit.needs_signoff:
            mark = "bot "
        elif commit.is_signed:
            mark = "ok  "
        else:
            mark = "MISSING"
        print(f"{mark} {commit.short} {commit.author_email}")

    if not unsigned:
        human = sum(1 for c in commits if c.needs_signoff)
        bots = len(commits) - human
        summary = f"\nall {human} commit(s) carry a matching sign-off"
        if bots:
            summary += f" ({bots} bot commit(s) exempt)"
        print(summary)
        return 0

    # One stream, in order. Split across stdout and stderr, the failure report
    # reached an Actions log BEFORE the per-commit listing it explains, because
    # stdout is block-buffered when it is a pipe and stderr is not -- for a gate
    # whose only job is to explain itself, the output read backwards.
    print(
        f"\n{len(unsigned)} of {sum(1 for c in commits if c.needs_signoff)} commit(s) "
        "have no `Signed-off-by:` matching their author or committer:\n"
    )
    for commit in unsigned:
        found = ", ".join(commit.signoffs) or "none"
        print(
            f"  {commit.short} authored by {commit.author_email} "
            f"(sign-offs found: {found})"
        )
    print(
        "\nSign off every commit with `git commit -s`. To fix a branch you have\n"
        "already written, without changing anything else:\n\n"
        "    git rebase --signoff <base>\n\n"
        "A sign-off matching the commit's author OR its committer is accepted,\n"
        "so `--signoff` works even on a commit you did not author.\n"
        "See CONTRIBUTING.md."
    )
    sys.stdout.flush()
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""The DCO gate, exercised against real git repositories.

``CONTRIBUTING.md`` promises "A pull request with unsigned commits will be
blocked by the DCO check until every commit carries a sign-off".  That sentence
was false for as long as it existed -- no workflow, no app.  These tests are
what make it true, and they build actual repositories rather than feeding
strings to a parser, because every interesting case here is a property of what
``git log`` emits: trailer formatting, merge commits, author identity.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "check_dco.py"

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dco.yml"

# NOT a skipif. `scripts/` ships (it is on scripts/publish/ships-manifest.txt),
# so there is no distribution in which this script is legitimately absent --
# which means a skip here could only ever fire on the one tamper that matters,
# deleting the gate. Twelve silent skips and a green Unit Tests job is exactly
# the vacuous pass this repository keeps rediscovering.


def test_the_gate_exists() -> None:
    assert SCRIPT.is_file(), f"{SCRIPT} is missing: the DCO gate has no implementation"


HUMAN = ("Ada Lovelace", "ada@example.com")
BOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


def _git(repo: Path, *args: str, **env: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={**_base_env(), **env},
    )
    return result.stdout


def _base_env() -> dict:
    import os

    env = dict(os.environ)
    # A repository built in a test must not inherit the developer's identity,
    # and must not read ~/.gitconfig -- `commit.gpgsign = true` there would
    # make every test hang on a passphrase prompt.
    env.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        }
    )
    return env


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", HUMAN[0])
    _git(path, "config", "user.email", HUMAN[1])
    _commit(path, "base", "base\n")
    return path


def _commit(
    repo: Path,
    filename: str,
    message: str,
    *,
    author: tuple[str, str] = HUMAN,
    signoff: tuple[str, str] | None = None,
) -> str:
    (repo / filename).write_text(message)
    _git(repo, "add", "-A")
    # A trailer is only a trailer when it is the last paragraph, so the blank
    # line matters: `git commit -s` always leaves one, and without it
    # `%(trailers:...)` reports nothing and every sign-off test "fails" for a
    # reason that has nothing to do with the code under test.
    body = message.rstrip("\n")
    if signoff is not None:
        body += f"\n\nSigned-off-by: {signoff[0]} <{signoff[1]}>\n"
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        body,
        GIT_AUTHOR_NAME=author[0],
        GIT_AUTHOR_EMAIL=author[1],
        GIT_COMMITTER_NAME=author[0],
        GIT_COMMITTER_EMAIL=author[1],
    )
    return _git(repo, "rev-parse", "HEAD").strip()


def _check(
    repo: Path, rev_range: str, form: str = "--range"
) -> subprocess.CompletedProcess:
    """Run the gate over *rev_range*.

    `form` exists because CI runs the POSITIONAL form
    (`check_dco.py "$BASE_SHA" "$HEAD_SHA"`) while every test here used
    `--range`. A regression in the positional branch would have passed the
    whole suite and broken only in Actions.
    """
    base, head = rev_range.split("..", 1)
    argv = (
        [str(SCRIPT), "--range", rev_range]
        if form == "--range"
        else [str(SCRIPT), base, head]
    )
    return subprocess.run(
        [sys.executable, *argv],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_base_env(),
    )


@pytest.mark.parametrize("form", ["--range", "positional"])
def test_a_signed_commit_passes(repo: Path, form: str) -> None:
    _commit(repo, "a.txt", "signed", signoff=HUMAN)
    result = _check(repo, "main~1..main", form)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "carry a matching sign-off" in result.stdout


@pytest.mark.parametrize("form", ["--range", "positional"])
def test_an_unsigned_commit_fails(repo: Path, form: str) -> None:
    _commit(repo, "a.txt", "unsigned")
    result = _check(repo, "main~1..main", form)
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "have no `Signed-off-by:` matching their author" in combined
    assert "git rebase --signoff" in combined


def test_one_unsigned_commit_among_signed_ones_fails(repo: Path) -> None:
    """The gate is per-commit, not per-pull-request."""
    _commit(repo, "a.txt", "signed", signoff=HUMAN)
    _commit(repo, "b.txt", "unsigned")
    _commit(repo, "c.txt", "signed too", signoff=HUMAN)
    result = _check(repo, "main~3..main")
    assert result.returncode == 1
    assert (result.stdout + result.stderr).count("authored by") == 1


def test_a_signoff_from_someone_else_does_not_count(repo: Path) -> None:
    """Signing off on another person's commit is the thing DCO forbids."""
    _commit(
        repo,
        "a.txt",
        "signed by the wrong person",
        signoff=("Grace Hopper", "grace@example.com"),
    )
    result = _check(repo, "main~1..main")
    assert result.returncode == 1
    assert "grace@example.com" in result.stdout + result.stderr


def test_the_signoff_email_is_compared_case_insensitively(repo: Path) -> None:
    _commit(repo, "a.txt", "shouty", signoff=(HUMAN[0], HUMAN[1].upper()))
    assert _check(repo, "main~1..main").returncode == 0


def test_a_different_display_name_is_accepted(repo: Path) -> None:
    """Names differ in punctuation legitimately; the e-mail is the identity."""
    _commit(repo, "a.txt", "renamed", signoff=("A. Lovelace", HUMAN[1]))
    assert _check(repo, "main~1..main").returncode == 0


def test_a_bot_commit_is_exempt(repo: Path) -> None:
    """Dependabot signs off as support@github.com, not as its author.

    Measured on this repository: commit 8936bdb is authored by
    `49699333+dependabot[bot]@users.noreply.github.com` and carries
    `Signed-off-by: dependabot[bot] <support@github.com>`. A strict comparison
    rejects every Dependabot pull request.
    """
    _commit(
        repo,
        "a.txt",
        "bump",
        author=BOT,
        signoff=("dependabot[bot]", "support@github.com"),
    )
    result = _check(repo, "main~1..main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bot commit(s) exempt" in result.stdout


def test_a_display_name_ending_in_bot_does_not_exempt(repo: Path) -> None:
    """`git config user.name 'me [bot]'` must not opt out of the DCO."""
    _commit(repo, "a.txt", "sneaky", author=("Ada [bot]", "ada@example.com"))
    result = _check(repo, "main~1..main")
    assert result.returncode == 1, "a display name ending in [bot] must not exempt"


@pytest.mark.parametrize(
    "email",
    [
        "evil[bot]@users.noreply.github.com",
        "1234+evil[bot]@users.noreply.github.com",
        "dependabot[bot]@evil.example.com",
    ],
)
def test_an_unlisted_bot_address_does_not_exempt(repo: Path, email: str) -> None:
    """The exemption is a named list, not a pattern.

    An earlier version matched `*[bot]@users.noreply.github.com` and the
    docstring claimed it could not be spoofed. Measured, it could -- one
    environment variable turned the whole gate off:

        GIT_AUTHOR_EMAIL='evil[bot]@users.noreply.github.com' git commit -m x
        -> bot  b67a17d4 evil[bot]@users.noreply.github.com
           all 0 commit(s) carry a matching sign-off (1 bot exempt)
           exit 0

    Git metadata is self-asserted and this does not change that; what it does
    is stop an unreviewed address claiming the exemption.
    """
    _commit(repo, "a.txt", "unsigned", author=("Evil", email))
    result = _check(repo, "main~1..main")
    assert result.returncode == 1, (
        f"{email} claimed the bot exemption; it is not in the named list"
    )


def test_a_signoff_matching_the_committer_is_accepted(repo: Path) -> None:
    """`git commit -s` writes the COMMITTER's identity, not the author's.

    A maintainer who rebases a contributor's branch, or uses
    `git commit --author=`, produces a commit whose author and sign-off differ
    by construction. Rejecting that leaves the contributor with a red required
    check and no way out: the remedy this script prints, `git rebase
    --signoff`, writes the committer too and changes nothing. The DCO GitHub
    App accepts author or committer for the same reason.
    """
    (repo / "a.txt").write_text("contributed")
    _git(repo, "add", "-A")
    _git(
        repo,
        "commit",
        "-q",
        "-m",
        "work by someone else\n\nSigned-off-by: Ada Lovelace <ada@example.com>\n",
        "--author=Contrib <contrib@example.com>",
    )
    result = _check(repo, "main~1..main")
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_workflow_runs_the_script(repo: Path) -> None:
    """The gate has to be wired in, not merely present.

    Deleting `.github/workflows/dco.yml` broke no test: the script kept its
    twelve green tests while nothing ran it on a pull request.
    """
    import yaml

    if not WORKFLOW.is_file():
        pytest.skip("this tree has no .github/workflows")
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = document.get("on") or document.get(True)
    assert "pull_request" in triggers, (
        f"dco.yml does not run on pull requests: {triggers}"
    )
    runs = "\n".join(
        step["run"]
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step.get("run"), str)
    )
    assert "scripts/check_dco.py" in runs, (
        "dco.yml does not invoke scripts/check_dco.py, so the gate is not wired in"
    )


def test_merge_commits_are_exempt(repo: Path) -> None:
    """Merging main into a branch is not authorship."""
    _commit(repo, "a.txt", "signed", signoff=HUMAN)
    _git(repo, "checkout", "-q", "-b", "side", "main~1")
    _commit(repo, "b.txt", "also signed", signoff=HUMAN)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
    result = _check(repo, "main~2..main")
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_empty_range_is_not_a_failure(repo: Path) -> None:
    result = _check(repo, "main..main")
    assert result.returncode == 0
    assert "nothing to sign off" in result.stdout


def test_an_unreadable_range_is_not_a_pass(repo: Path) -> None:
    """A gate that cannot run must never report success.

    This is the vacuity failure that keeps recurring in this repository: a
    check whose traversal breaks and whose exit status says everything is fine.
    """
    result = _check(repo, "main..no-such-ref")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "could not read" in result.stdout + result.stderr


def test_a_multiline_message_with_a_trailing_signoff_is_read(repo: Path) -> None:
    """The trailer is at the end of a real commit message, not on line one."""
    message = "feat: a thing\n\nA paragraph explaining it.\n\nAnother paragraph.\n"
    _commit(repo, "a.txt", message, signoff=HUMAN)
    assert _check(repo, "main~1..main").returncode == 0

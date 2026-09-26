"""`scripts/doc_examples.py` — the contract for the documentation's shell examples.

Every refusal is driven with a fixture page; the render rules are driven with
HTML produced by the same Markdown extensions MkDocs uses (read from
``mkdocs.yml``), never hand-written HTML; and the real repository's enrolment is
checked as it stands, so a page edit that breaks the contract fails here too.
No Docker, no git, no network: the repository root comes from this file's path,
so the tests also run in ``scripts/core_build.sh``'s copy.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REPO = pathlib.Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "doc_examples", REPO / "scripts" / "doc_examples.py"
)
dx = importlib.util.module_from_spec(_spec)
sys.modules["doc_examples"] = dx  # dataclasses look their module up while loading
_spec.loader.exec_module(dx)

FENCE = "`" * 3


def page(*blocks: str) -> str:
    return (
        "# Page\n\n"
        + "\n\n".join(textwrap.dedent(b).strip("\n") for b in blocks)
        + "\n"
    )


def blocks(text: str):
    return [
        b
        for f in dx.parse_fences(text, "p.md")
        if (b := dx.classify(f, "p.md")) is not None
    ]


def refused(text: str) -> str:
    with pytest.raises(dx.Refused) as excinfo:
        for block in blocks(text):
            dx.lint_block(block, "p.md")
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# The tag grammar
# ---------------------------------------------------------------------------


def test_exec_and_skip_blocks_are_read_with_their_expectations():
    text = page(
        f"""
        {FENCE}{{.bash exec timeout=30}}
        echo hi
        {FENCE}
        <!-- expect: hi -->
        <!-- expect: there -->
        """,
        f"""
        {FENCE}{{.bash skip reason="demo: needs a browser"}}
        open http://localhost:3000
        {FENCE}
        """,
        f"""
        {FENCE}json
        {{"a": 1}}
        {FENCE}
        """,
    )
    run, skip = blocks(text)
    assert (run.kind, run.timeout, run.expects) == ("exec", 30, ["hi", "there"])
    assert (skip.kind, skip.reason) == ("skip", "demo: needs a browser")


@pytest.mark.parametrize(
    "info, message",
    [
        ("bash", "untagged shell fence"),
        ("sh", "'sh' names a shell the runner does not know"),
        ("bash exec", "not brace form"),
        ("{bash exec}", "without '.'"),
        ("{.bash exec} trailing", "text after '}'"),
        ("{.bash exec skip}", "exactly one of exec or skip"),
        ("{.bash}", "exactly one of exec or skip"),
        ("{.bash skip}", 'skip needs reason="..."'),
        ('{.bash exec reason="x"}', "reason on a block that runs"),
        ("{.bash exec title=x}", "unknown attribute"),
        ('{.bash exec hl_lines="1"}', "unknown attribute"),
        ("{.bash exec foo}", "unknown attribute"),
        ("{.bash exec timeout=0}", "timeout must be 1-3600"),
        ("{.bash exec timeout=9999}", "timeout must be 1-3600"),
        ("{.sh exec}", "'sh' names a shell the runner does not know"),
        ("{.python exec}", "not shell"),
        ("{.bash .python exec}", "exactly one language class"),
    ],
)
def test_malformed_tags_are_refused(info, message):
    text = page(f"{FENCE}{info}\necho hi\n{FENCE}")
    assert message in refused(text)


def test_an_expectation_after_a_skip_or_a_json_block_is_refused():
    skip = page(
        f'{FENCE}{{.bash skip reason="dev: x"}}\necho\n{FENCE}\n<!-- expect: y -->'
    )
    json_ = page(f"{FENCE}json\n{{}}\n{FENCE}\n<!-- expect: y -->")
    assert "does not run" in refused(skip)
    assert "does not run" in refused(json_)


def test_an_unclosed_fence_is_refused():
    with pytest.raises(dx.Refused, match="unclosed fence"):
        dx.parse_fences(f"text\n\n{FENCE}python\nprint(1)\n", "p.md")


def test_a_fence_nested_in_a_list_is_still_a_shell_block():
    text = "1. Start it:\n\n    ```bash\n    echo hi\n    ```\n"
    assert "untagged shell fence" in refused(text)


def test_a_four_backtick_fence_holds_examples_as_text():
    text = page(f"````markdown\n{FENCE}bash exec\necho hi\n{FENCE}\n````")
    assert blocks(text) == []


# ---------------------------------------------------------------------------
# What may be in a block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        'curl -s localhost:8000/health/ready | jq .status  # "healthy"',
        "# a whole-line comment",
        "echo hi; # after a semicolon",
    ],
)
def test_a_shell_comment_is_refused(line):
    text = page(f"{FENCE}{{.bash exec}}\n{line}\n{FENCE}")
    assert "shell comment" in refused(text)


@pytest.mark.parametrize(
    "line",
    [
        "curl http://localhost:8000/docs#/flags",
        "echo a#b",
        "echo $#",
        "echo ${#PATH}",
        '[[ "$x" == *#* ]] && echo match',
        """curl -d '{"colour":"#00ff00"}' localhost:8000""",
        'echo "# not a comment"',
    ],
)
def test_a_hash_that_is_not_a_comment_is_allowed(line):
    assert dx.comment_lines(line) == []


def test_a_here_document_body_is_data():
    body = "cat <<'EOF' > config.yml\n# PORT is the listen port\nport: 8000  # default\nEOF\n"
    assert dx.comment_lines(body) == []
    assert dx.comment_lines(body + "echo done  # after\n") == [4]


@pytest.mark.parametrize(
    "body, message",
    [
        ("export TOKEN=$(false)", "masks the substitution"),
        ("local x=$(false)", "masks the substitution"),
        ("echo a \\", "ends in '\\'"),
        ('echo "unterminated', "bash -n"),
        ("if true; then", "bash -n"),
        ("cat <<EOF\nhello", "bash -n"),
        ("unset COMPOSE_PROJECT_NAME; docker compose --dry-run down -v", "COMPOSE"),
        (
            "COMPOSE_PROJECT_NAME=experimently docker compose down -v",
            "COMPOSE_PROJECT_NAME",
        ),
        ("docker compose -p experimently down -v", "names a compose project"),
        (
            "docker compose --project-name=experimently down -v",
            "names a compose project",
        ),
        ("env -u HOME docker compose down", "rewrites the environment"),
        ("env -i docker compose down", "rewrites the environment"),
        ("docker volume rm experimently_postgres_data", "removes Docker resources"),
        ("docker system prune -f", "removes Docker resources"),
        ("docker rm -f some-container", "removes containers"),
    ],
)
def test_blocks_that_hide_a_failure_or_escape_the_project_are_refused(body, message):
    text = page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}")
    assert message in refused(text)


def test_the_quick_starts_own_down_is_allowed():
    text = page(f"{FENCE}{{.bash exec}}\ndocker compose down -v\n{FENCE}")
    (block,) = blocks(text)
    dx.lint_block(block, "p.md")  # does not raise


def test_an_empty_run_block_is_refused():
    assert "empty block" in refused(page(f"{FENCE}{{.bash exec}}\n\n{FENCE}"))


# ---------------------------------------------------------------------------
# Enrolment and counts
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A scratch repository root with one enrolled page, and no pending list."""
    monkeypatch.setattr(dx, "ROOT", tmp_path)
    monkeypatch.setattr(dx, "ENROLMENT", tmp_path / "scripts" / "doc_examples.toml")
    monkeypatch.setattr(dx, "PENDING_FROZEN", {}, raising=False)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_text(
        page(
            f"{FENCE}{{.bash exec}}\necho hi\n{FENCE}\n<!-- expect: hi -->",
            f'{FENCE}{{.bash skip reason="dev: x"}}\necho no\n{FENCE}',
        )
    )
    return tmp_path


def write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def enrol(root, body: str) -> pathlib.Path:
    path = root / "scripts" / "doc_examples.toml"
    path.write_text(textwrap.dedent(body))
    return path


def problems_of(path: pathlib.Path) -> list[str]:
    with pytest.raises(dx.Refused) as excinfo:
        dx.check(path)
    return excinfo.value.problems


GOOD = """
    [meta]
    documents = 1
    exec = 1
    universe = ["docs/p.md"]

    [[document]]
    path = "docs/p.md"
    environment = "bare"
    exec = 1
    skip = 1
    expects = 1
"""


def test_exact_counts_pass(repo, capsys):
    counts = dx.check(enrol(repo, GOOD))
    assert counts == {"docs/p.md": {"exec": 1, "skip": 1, "expects": 1}}
    assert (
        "universe: 1 pages; 1 enrolled, 0 exempt, 0 pending" in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "old, new, message",
    [
        (
            "expects = 1\n",
            "expects = 2\n",
            "docs/p.md: found 1 expectations; the enrolment says 2. If you added or "
            "removed one on purpose, set expects = 1.",
        ),
        (
            "    exec = 1\n    skip",
            "    exec = 0\n    skip",
            "docs/p.md: found 1 exec blocks; the enrolment says 0.",
        ),
        (
            "documents = 1",
            "documents = 2",
            "scripts/doc_examples.toml lists 1 documents but [meta] documents = 2; "
            "set it to 1.",
        ),
        (
            "exec = 1\n    universe",
            "exec = 2\n    universe",
            "the documents' exec counts add up to 1 but [meta] exec = 2; set it to 1.",
        ),
        ('environment = "bare"', 'environment = "local"', "'local' is not implemented"),
        ('environment = "bare"', 'environment = "cloud"', "is not one of"),
        (
            'path = "docs/p.md"',
            'path = "docs/missing.md"',
            "docs/missing.md is enrolled but does not exist. Renamed? Change the path.",
        ),
        ('path = "docs/p.md"', 'path = "../p.md"', "is not a markdown file"),
    ],
)
def test_enrolment_mismatches_are_refused(repo, old, new, message):
    body = GOOD.replace(old, new, 1)
    assert body != GOOD
    assert any(message in p for p in problems_of(enrol(repo, body))), message


def test_working_instructions_cannot_be_enrolled(repo):
    (repo / "CLAUDE.md").write_text("# x\n")
    assert any(
        "working instructions" in p
        for p in problems_of(
            enrol(repo, GOOD.replace('path = "docs/p.md"', 'path = "CLAUDE.md"'))
        )
    )


def test_a_stack_page_needs_exactly_one_stack_start(repo):
    qs = repo / "docs" / "getting-started"
    qs.mkdir()
    one = f"{FENCE}{{.bash exec}}\ndocker compose up -d --wait\n{FENCE}"
    two = one + "\n\n" + one
    body = textwrap.dedent(
        """
        [meta]
        documents = 2
        exec = {total}
        universe = ["docs/getting-started/quick-start.md", "docs/p.md"]

        [[document]]
        path = "docs/p.md"
        environment = "stack"
        exec = 1
        skip = 1
        expects = 1

        [[document]]
        path = "docs/getting-started/quick-start.md"
        environment = "bare"
        exec = {n}
        skip = 0
        expects = 0
        """
    )
    (qs / "quick-start.md").write_text(page(one))
    dx.check(enrol(repo, body.format(n=1, total=2)))
    (qs / "quick-start.md").write_text(page(two))
    assert any(
        "2 exec blocks equal" in p
        for p in problems_of(enrol(repo, body.format(n=2, total=3)))
    )


# ---------------------------------------------------------------------------
# The universe: every page the walk finds is under the contract
# ---------------------------------------------------------------------------


def test_the_walk_prunes_by_name_at_any_depth(tmp_path):
    for rel in (
        "README.md",
        "docs/a.md",
        ".github/pull_request_template.md",
        "frontend/node_modules/pkg/README.md",
        "sdk/js/node_modules/x/y/README.md",
        "node_modules/z.md",
        "venv/lib/x.md",
        "demo/app/venv/x.md",
        "site/index.md",
        "docs/site/built.md",
        ".claude/worktrees/w/docs/a.md",
        ".pytest_cache/README.md",
        "frontend/.next/x.md",
        "CLAUDE.md",
        "backend/CLAUDE.md",
        "notes.txt",
    ):
        write(tmp_path, rel, "# x\n")
    assert dx.walk(tmp_path) == {
        "README.md",
        "docs/a.md",
        ".github/pull_request_template.md",
    }


def test_a_new_page_the_universe_does_not_list_is_refused(repo):
    write(repo, "docs/guides/new.md", "# New\n\nNo code at all.\n")
    assert problems_of(enrol(repo, GOOD)) == [
        "docs/guides/new.md: a page scripts/doc_examples.toml does not know. Add it "
        "to [meta] universe (docs/development/doc-examples.md#enrolling-a-page)."
    ]


def test_a_listed_page_the_walk_does_not_find_is_refused(repo):
    body = GOOD.replace(
        'universe = ["docs/p.md"]', 'universe = ["docs/gone.md", "docs/p.md"]'
    )
    assert problems_of(enrol(repo, body)) == [
        "docs/gone.md is in [meta] universe but the walk does not find it. Renamed? "
        "Change the path. Deleted? Remove it."
    ]


def test_a_page_in_a_pruned_directory_cannot_be_enrolled(repo):
    write(repo, "docs/site/p.md", (repo / "docs" / "p.md").read_text())
    body = GOOD.replace('path = "docs/p.md"', 'path = "docs/site/p.md"')
    found = problems_of(enrol(repo, body))
    assert any(
        "docs/site/p.md is listed but is outside the universe" in p for p in found
    )


@pytest.mark.regression
def test_a_document_dropped_with_its_count_is_refused(repo):
    """R-E1 (E-T1): deleting an entry together with its count used to pass."""
    write(
        repo,
        "docs/q.md",
        page(f"{FENCE}{{.bash exec}}\necho q\n{FENCE}\n<!-- expect: q -->"),
    )
    both = textwrap.dedent(GOOD).replace(
        'universe = ["docs/p.md"]', 'universe = ["docs/p.md", "docs/q.md"]'
    ).replace("documents = 1", "documents = 2").replace(
        "exec = 1\nuniverse", "exec = 2\nuniverse"
    ) + textwrap.dedent(
        """
        [[document]]
        path = "docs/q.md"
        environment = "bare"
        exec = 1
        skip = 0
        expects = 1
        """
    )
    dx.check(enrol(repo, both))
    dropped = both.split('[[document]]\npath = "docs/q.md"')[0]
    dropped = dropped.replace("documents = 2", "documents = 1").replace(
        "exec = 2\nuniverse", "exec = 1\nuniverse"
    )
    assert problems_of(enrol(repo, dropped)) == [
        "docs/q.md: 1 shell block, and the page is not enrolled. Add it to "
        "scripts/doc_examples.toml (docs/development/doc-examples.md#enrolling-a-page), "
        "or list it as exempt with a reason."
    ]


@pytest.mark.regression
def test_a_zero_fence_document_cannot_hold_a_place(repo):
    """R-E2 (E-T1b): swapping a real page for one with no shell block kept the count."""
    write(repo, "docs/empty.md", "# Empty\n\n```json\n{}\n```\n")
    body = GOOD.replace(
        'universe = ["docs/p.md"]', 'universe = ["docs/empty.md", "docs/p.md"]'
    )
    swapped = (
        body.replace('path = "docs/p.md"', 'path = "docs/empty.md"')
        .replace(
            "exec = 1\n    skip = 1\n    expects = 1",
            "exec = 0\n    skip = 0\n    expects = 0",
        )
        .replace("exec = 1\n    universe", "exec = 0\n    universe")
    )
    found = problems_of(enrol(repo, swapped))
    assert (
        "docs/empty.md is listed as enrolled but has no shell blocks; remove the entry "
        "and set [meta] documents to match."
    ) in found
    assert any(
        p.startswith("docs/p.md: 2 shell blocks, and the page is not enrolled")
        for p in found
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    "language",
    [
        "zsh",
        "sh-session",
        "shell-session",
        "console",
        "shell",
        "sh",
        "fish",
        "powershell",
        "ps1",
        "Bash",
    ],
)
@pytest.mark.parametrize("enrolled", [True, False], ids=["enrolled", "unlisted"])
def test_a_shell_fence_in_an_unknown_shell_language_is_refused(
    repo, language, enrolled
):
    """R-E3 (E-T6): a block retagged ```zsh left the check, counts and all."""
    target = "docs/p.md" if enrolled else "docs/other.md"
    if not enrolled:
        write(repo, target, "# Other\n")
    body = (
        GOOD
        if enrolled
        else GOOD.replace(
            'universe = ["docs/p.md"]', 'universe = ["docs/other.md", "docs/p.md"]'
        )
    )
    path = repo / target
    lines = path.read_text().split("\n")
    lines += ["", f"{FENCE}{language}", "echo retagged", FENCE, ""]
    path.write_text("\n".join(lines))
    line = len(lines) - 3
    assert (
        f"{target}:{line}: '{language}' names a shell the runner does not know; use {{.bash …}}"
        in problems_of(enrol(repo, body))
    )


def test_a_fence_that_names_no_language_is_refused_on_every_page(repo):
    write(repo, "README.md", "# Readme\n\n```\nsome output\n```\n")
    body = GOOD.replace(
        'universe = ["docs/p.md"]', 'universe = ["README.md", "docs/p.md"]'
    )
    assert problems_of(enrol(repo, body)) == [
        "README.md:3: the fence names no language; name one (`text` for output) "
        "(docs/development/doc-examples.md#tagging-a-shell-block)"
    ]


def test_the_lists_are_disjoint(repo):
    body = GOOD + textwrap.dedent(
        """
        [[exempt]]
        path = "docs/p.md"
        reason = "x"
        """
    )
    assert any(
        "docs/p.md is listed 2 times (enrolled, exempt)" in p
        for p in problems_of(enrol(repo, body))
    )


def test_an_exempt_page_needs_a_reason_and_a_shell_block_and_obeys_the_rules(repo):
    write(
        repo,
        "docs/ops.md",
        "# Ops\n\n```bash\naws s3 ls  # lists\n```\n\n```bash\necho 'x\n```\n",
    )
    write(repo, "docs/none.md", "# None\n")
    body = GOOD.replace(
        'universe = ["docs/p.md"]',
        'universe = ["docs/none.md", "docs/ops.md", "docs/p.md"]',
    ) + textwrap.dedent(
        """
        [[exempt]]
        path = "docs/ops.md"
        reason = "operator runbook, run by hand"

        [[exempt]]
        path = "docs/none.md"
        reason = "x"
        """
    )
    found = problems_of(enrol(repo, body))
    assert (
        "docs/none.md is listed as exempt but has no shell blocks; remove the entry."
        in found
    )
    assert any(p.startswith('docs/ops.md:4: shell comment "# lists"') for p in found)
    assert any(p.startswith("docs/ops.md:7: syntax (bash -n)") for p in found)
    assert len(found) == 3, found
    assert any(
        "exempt needs a reason" in p
        for p in problems_of(enrol(repo, body.replace('reason = "x"', 'reason = " "')))
    )


# ---------------------------------------------------------------------------
# Pending: the rollout list, frozen in code, only shrinks
# ---------------------------------------------------------------------------

PENDING_PAGE = (
    "# Ops\n\n```bash\naws s3 ls  # lists the buckets\n```\n\n```\nout\n```\n"
)
WITH_PENDING = (
    GOOD.replace('universe = ["docs/p.md"]', 'universe = ["docs/ops.md", "docs/p.md"]')
    + """
    [pending]
    "docs/ops.md" = { comments = 1, unlabelled = 1, syntax = 0 }
"""
)


@pytest.fixture
def pending_repo(repo, monkeypatch):
    write(repo, "docs/ops.md", PENDING_PAGE)
    monkeypatch.setattr(dx, "PENDING_FROZEN", {"docs/ops.md": (1, 1, 0)})
    return repo


def test_a_pending_page_carries_its_exact_residual(pending_repo, capsys):
    dx.check(enrol(pending_repo, WITH_PENDING))
    assert (
        "pending residual: 1 comment lines, 1 unlabelled fences, 0 bash -n failures"
        in capsys.readouterr().out
    )
    found = problems_of(
        enrol(pending_repo, WITH_PENDING.replace("comments = 1", "comments = 0"))
    )
    assert found == [
        "docs/ops.md: found 1 shell comment lines; [pending] says 0. Set comments = 1."
    ]


def test_pending_cannot_grow(pending_repo):
    write(pending_repo, "docs/new.md", "# New\n\n```bash\necho new\n```\n")
    body = (
        WITH_PENDING.replace(
            '"docs/ops.md", "docs/p.md"]', '"docs/new.md", "docs/ops.md", "docs/p.md"]'
        )
        + '    "docs/new.md" = { comments = 0, unlabelled = 0, syntax = 0 }\n'
    )
    found = problems_of(enrol(pending_repo, body))
    assert len(found) == 1 and found[0].startswith(
        "docs/new.md: pending cannot grow, and this page was not pending when the list "
        "was frozen (PENDING_FROZEN in scripts/doc_examples.py)."
    ), found


def test_a_pending_residual_can_only_fall(pending_repo):
    write(
        pending_repo,
        "docs/ops.md",
        PENDING_PAGE.replace("aws s3 ls", "# more\naws s3 ls"),
    )
    found = problems_of(
        enrol(pending_repo, WITH_PENDING.replace("comments = 1", "comments = 2"))
    )
    assert found == [
        "docs/ops.md: 2 shell comment lines, more than the 1 this page had when pending "
        "was frozen; the residual can only fall."
    ]
    write(
        pending_repo, "docs/ops.md", PENDING_PAGE.replace("  # lists the buckets", "")
    )
    dx.check(enrol(pending_repo, WITH_PENDING.replace("comments = 1", "comments = 0")))


def test_a_pending_page_with_nothing_pending_must_leave(pending_repo):
    write(pending_repo, "docs/ops.md", "# Ops\n\n```text\nout\n```\n")
    found = problems_of(
        enrol(
            pending_repo,
            WITH_PENDING.replace(
                "comments = 1, unlabelled = 1", "comments = 0, unlabelled = 0"
            ),
        )
    )
    assert found == [
        "docs/ops.md is pending but has nothing pending (no shell blocks, and every fence "
        "names a language); remove its [pending] entry."
    ]


def test_an_exec_tag_on_a_pending_page_is_refused(pending_repo):
    write(
        pending_repo, "docs/ops.md", PENDING_PAGE + "\n```{.bash exec}\necho hi\n```\n"
    )
    assert any(
        "docs/ops.md:11: an exec block on a pending page never runs" in p
        for p in problems_of(enrol(pending_repo, WITH_PENDING))
    )


def test_the_frozen_pending_list_is_the_enrolment_s_pending_list_or_larger():
    """The TOML may only drop pages the frozen list holds, never add one."""
    pending = dx.load().pending
    assert set(pending) <= set(dx.PENDING_FROZEN)


# ---------------------------------------------------------------------------
# Skip reasons, package managers, AWS, bash -n on skip blocks
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "reason, ok",
    [
        ("x", False),
        ("because it needs AWS", False),
        ("aws needs an account", False),
        ("aws: needs an account", True),
        ("AWS: needs an account", False),
        ("cloud: needs an account", False),
        ("aws:", False),
        ("aws: ", False),
        ("bug #123: the endpoint returns 500", True),
        ("bug: the endpoint returns 500", False),
        ("bug #abc: x", False),
        ("bug#1: x", False),
        ("dev #1: x", False),
        ("fragment: fill in your values", True),
    ],
)
def test_skip_reason_names_a_category(reason, ok):
    """R-E7: `reason="x"` said nothing about why a block could not run."""
    text = page(f'{FENCE}{{.bash skip reason="{reason}"}}\necho hi\n{FENCE}')
    if ok:
        (block,) = blocks(text)
        assert dx.category_of(block.reason) == reason.split(":")[0].split(" ")[0]
    else:
        assert (
            "skip reason must start with one of: checkout, dev, server, aws"
            in refused(text)
        )


@pytest.mark.parametrize(
    "body, tool",
    [
        ("pip install openfeature-sdk experimently experimently-openfeature", "pip"),
        ("gem install experimently", "gem"),
        ("npx @getexperimently/cli init", "npx"),
        ("uv pip install experimently", "uv"),
        ("cd sdk/js && npm ci", "npm"),
        ("sudo pip3 install experimently", "pip3"),
        ("python -m pip install experimently", "python -m pip"),
        ("dotnet add package Experimently.SDK", "dotnet add"),
        ("composer require experimently/sdk", "composer"),
        ("go get github.com/getexperimently/go-sdk", "go get"),
        ("FOO=1 yarn add @getexperimently/js-sdk", "yarn"),
        ("VERSION=$(npm view x version)", "npm"),
        ("if true; then pnpm i; fi", "pnpm"),
        ("pipx run experimently", "pipx"),
        ("poetry add experimently", "poetry"),
    ],
)
def test_a_block_that_runs_may_not_install_or_run_a_package(body, tool):
    """M6 (T29): until the names are published, a run would fetch a squatter's."""
    text = page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}")
    assert f"may not run '{tool}'" in refused(text)


@pytest.mark.parametrize(
    "body",
    [
        "aws sts get-caller-identity",
        "cdk deploy --all",
        "sam build",
        "cd infrastructure && cdk synth",
        "ARN=$(aws sts get-caller-identity --query Arn)",
    ],
)
def test_a_block_that_runs_may_not_reach_aws(body):
    """PE C10: an exec block never reaches an AWS account."""
    text = page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}")
    assert "may not call '" in refused(text)


@pytest.mark.parametrize(
    "body",
    [
        "echo npm pip aws",
        "curl -s https://registry.npmjs.org/react | jq .name",
        'echo "run npm ci"',
        "ls node_modules",
        "echo sam-and-cdk",
    ],
)
def test_the_words_alone_are_not_a_package_manager_or_aws(body):
    (block,) = blocks(page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}"))
    assert dx.block_problems(block, "p.md") == []


def test_a_registry_skip_must_run_a_package_manager():
    good = page(
        f'{FENCE}{{.bash skip reason="registry: not published"}}\npip install experimently\n{FENCE}'
    )
    bad = page(
        f'{FENCE}{{.bash skip reason="registry: not published"}}\ncurl localhost\n{FENCE}'
    )
    (block,) = blocks(good)
    assert dx.block_problems(block, "p.md") == []
    assert (
        "the skip reason says 'registry' but the block runs no package manager"
        in refused(bad)
    )


def test_bash_n_runs_on_skip_blocks_too_except_fragments():
    broken = "aws s3 cp 'x"
    skip = page(
        f'{FENCE}{{.bash skip reason="aws: needs an account"}}\n{broken}\n{FENCE}'
    )
    fragment = page(
        f'{FENCE}{{.bash skip reason="fragment: fill it in"}}\n{broken}\n{FENCE}'
    )
    assert "syntax (bash -n)" in refused(skip)
    (block,) = blocks(fragment)
    assert dx.block_problems(block, "p.md") == []


def test_bash_n_is_refused_with_a_bash_older_than_4_4(tmp_path, monkeypatch):
    """PE C16: macOS's /bin/bash 3.2 would give different answers than CI."""
    fake = tmp_path / "bash"
    fake.write_text("#!/bin/sh\necho 3.2\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{__import__('os').pathsep}/usr/bin:/bin")
    monkeypatch.setattr(dx, "_SYNTAX_BASH", [])
    with pytest.raises(dx.Refused, match="is bash 3.2; the examples need bash >= 4.4"):
        dx.syntax_problem("echo hi")


def test_the_aws_cli_cannot_read_the_callers_credentials():
    env = dx.scrubbed_env("docex-unit", {})
    assert (
        env["AWS_CONFIG_FILE"]
        == env["AWS_SHARED_CREDENTIALS_FILE"]
        == __import__("os").devnull
    )
    problems = _run_page(
        'echo "$AWS_SHARED_CREDENTIALS_FILE $AWS_CONFIG_FILE"',
        expects={0: [f"{__import__('os').devnull} {__import__('os').devnull}"]},
    )
    assert problems == [], problems


# ---------------------------------------------------------------------------
# Messages: every problem in one run, one prefix, annotations in CI
# ---------------------------------------------------------------------------


def test_every_problem_is_reported_in_one_run(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    write(
        repo,
        "docs/p.md",
        page(
            f"{FENCE}{{.bash exec}}\necho a  # one\necho b  # two\n{FENCE}\n<!-- expect: a -->",
            f'{FENCE}{{.bash skip reason="x"}}\necho no  # three\n{FENCE}',
        ),
    )
    enrol(repo, GOOD)
    assert dx.main(["--check"]) == 2
    err = capsys.readouterr().err.strip().split("\n")
    assert err[-1] == "4 problems"
    refusals = err[:-1]
    assert len(refusals) == 4, err
    assert all(
        line.count("refused:") == 1 and line.startswith("refused: ")
        for line in refusals
    )
    assert sum('shell comment "#' in line for line in refusals) == 2
    assert sum("skip reason must start" in line for line in refusals) == 1


def test_problems_are_annotated_in_github_actions(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    write(
        repo,
        "docs/p.md",
        (repo / "docs" / "p.md").read_text().replace("echo no", "echo no  # a, b: c"),
    )
    enrol(repo, GOOD)
    assert dx.main(["--check"]) == 2
    err = capsys.readouterr().err
    assert (
        '::error file=docs/p.md,line=9::docs/p.md:9: shell comment "# a, b: c" breaks '
        "when pasted into zsh." in err
    ), err


def test_the_authoring_pages_sample_is_what_the_check_prints(repo, monkeypatch, capsys):
    """The 'When the check fails' sample is real output, not a paraphrase."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    authoring = (REPO / "docs" / "development" / "doc-examples.md").read_text()
    section = authoring.split("## When the check fails", 1)[1]
    sample = section.split("```text\n", 1)[1].split("\n```", 1)[0]
    (repo / "docs" / "p.md").unlink()
    write(
        repo,
        "docs/guides/new-page.md",
        "# New page\n\nStart it:\n\n```bash\necho start\n```\n\n```zsh\necho z\n```\n",
    )
    write(
        repo,
        "docs/guides/tour.md",
        "# Tour\n\nCreate a flag and read back its id. The block below prints it.\n\n"
        + "\n" * 8
        + "```{.bash exec}\n"
        + "curl -s localhost:8000/api/v1/feature-flags/ | jq -r '.[0].id'  # prints the flag's id\n"
        + "```\n<!-- expect: - -->\n",
    )
    enrol(
        repo,
        """
        [meta]
        documents = 1
        exec = 1
        universe = ["docs/guides/tour.md"]

        [[document]]
        path = "docs/guides/tour.md"
        environment = "bare"
        exec = 1
        skip = 0
        expects = 1
        """,
    )
    assert dx.main(["--check"]) == 2
    assert capsys.readouterr().err.strip() == sample.strip()


# ---------------------------------------------------------------------------
# Output a CI log can use: measured counts, line by line
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_the_run_counts_the_blocks_it_executed():
    """R-E4: `passed (N exec)` printed the enrolment's number, not what ran."""
    text = page(
        f"{FENCE}{{.bash exec}}\necho a\n{FENCE}\n<!-- expect: a -->",
        f"{FENCE}{{.bash exec}}\necho b\n{FENCE}\n<!-- expect: b -->",
    )
    problems, reached = dx.execute_counted(
        blocks(text), "p.md", dx.scrubbed_env("docex-unit", {})
    )
    assert (problems, reached) == ([], 2)
    stops = page(
        f"{FENCE}{{.bash exec}}\necho a\n{FENCE}\n<!-- expect: a -->",
        f"{FENCE}{{.bash exec}}\nexit 0\n{FENCE}",
        f"{FENCE}{{.bash exec}}\necho c\n{FENCE}\n<!-- expect: c -->",
    )
    _, stopped = dx.execute_counted(
        blocks(stops), "p.md", dx.scrubbed_env("docex-unit", {})
    )
    assert stopped == 1
    doc = {"path": "p.md", "exec": 3}
    line, found = dx.run_verdict(doc, problems, reached)
    assert line == "p.md: FAILED (2/3 exec blocks ran)"
    assert found == ["p.md: 2 exec blocks reached their end; the enrolment says 3"]
    assert dx.run_verdict({"path": "p.md", "exec": 2}, [], 2) == (
        "p.md: passed (2/2 exec blocks ran)",
        [],
    )


@pytest.mark.regression
def test_the_runner_writes_its_output_line_by_line():
    """R-E5 (the runner's half): a pipe is block-buffered, so a job killed mid-run
    lost the name of the page it was on.  The deadline half is E0b's."""
    import subprocess

    probe = textwrap.dedent(
        f"""
        import importlib.util, sys
        spec = importlib.util.spec_from_file_location("dx", {str(REPO / "scripts" / "doc_examples.py")!r})
        dx = importlib.util.module_from_spec(spec)
        sys.modules["dx"] = dx
        spec.loader.exec_module(dx)
        try:
            dx.main([])
        except SystemExit:
            pass
        print(sys.stdout.line_buffering, sys.stderr.line_buffering)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert result.stdout.strip() == "True True", result.stderr


# ---------------------------------------------------------------------------
# Rendering, through the site's own Markdown extensions
# ---------------------------------------------------------------------------


def _render(text: str) -> str:
    import markdown

    config = yaml.safe_load((REPO / "mkdocs.yml").read_text())
    names, options = [], {}
    for entry in config["markdown_extensions"]:
        if isinstance(entry, dict):
            ((name, opts),) = entry.items()
            names.append(name)
            if opts:
                options[name] = opts
        else:
            names.append(entry)
    options.pop("pymdownx.snippets", None)
    names = [n for n in names if n != "pymdownx.snippets"]
    return markdown.markdown(text, extensions=names, extension_configs=options)


def _problems(text: str) -> list[str]:
    return dx.render_problems(text, _render(text), "p.md")


def test_good_tags_render_as_code():
    text = page(
        f"{FENCE}{{.bash exec timeout=30}}\necho hi\n{FENCE}\n<!-- expect: hi -->",
        f'{FENCE}{{.bash skip reason="dev: x"}}\necho no\n{FENCE}',
    )
    assert _problems(text) == []
    assert "expect" not in _render(text).replace("<!-- expect: hi -->", "")


@pytest.mark.parametrize(
    "text",
    [
        page(
            f"Intro.\n\n{FENCE}bash exec\necho destroyed\n{FENCE}"
        ),  # last on the page
        page(
            f"{FENCE}bash exec\necho destroyed\n{FENCE}",
            f"{FENCE}bash\necho next\n{FENCE}",
        ),  # swallows the next fence
        page(f'{FENCE}{{.bash skip reason="dev: a"}} trailing\necho x\n{FENCE}'),
    ],
    ids=["destroyed-last", "destroyed-then-fence", "trailing-text"],
)
def test_a_destroyed_fence_is_caught_by_the_render_check(text):
    assert _problems(text)


def test_no_dot_renders_as_code_so_only_the_source_check_sees_it():
    text = page(f"{FENCE}{{bash exec}}\necho hi\n{FENCE}")
    assert _problems(text) == []
    assert "without '.'" in refused(text)


def test_inline_code_that_mentions_a_fence_is_not_a_leak():
    text = page(
        "Write `` ```{.bash exec} `` for a block that runs, or\n"
        '`` ```{.bash skip reason="..."} `` for one that does not.',
        "Pass `extra={...}` to the logger.",
        "`docker compose\nup -d` starts it.",
    )
    assert _problems(text) == []


# ---------------------------------------------------------------------------
# The real repository
# ---------------------------------------------------------------------------


def test_the_repository_enrolment_holds():
    dx.check()


def test_the_site_toolchain_is_installed_from_one_place():
    """The page the render check inspects is built by exactly what ships."""
    for workflow in ("docs.yml", "doc-examples.yml"):
        text = (REPO / ".github" / "workflows" / workflow).read_text()
        assert "bash scripts/docs_toolchain.sh" in text, workflow
        assert "grep -E '^mkdocs" not in text, f"{workflow} spells the install itself"


# ---------------------------------------------------------------------------
# Execution (no Docker: a page's blocks, one bash, sentinels between them)
# ---------------------------------------------------------------------------


def _run_page(*bodies: str, expects=None, extra_env=None) -> list[str]:
    """Run fixture blocks through execute(); return the problems it reports."""
    expects = expects or {}
    parts = []
    for i, body in enumerate(bodies):
        lines = "".join(f"\n<!-- expect: {e} -->" for e in expects.get(i, []))
        parts.append(f"{FENCE}{{.bash exec timeout=10}}\n{body}\n{FENCE}{lines}")
    page_blocks = blocks(page(*parts))
    env = dx.scrubbed_env("docex-unit", {})
    env.update(extra_env or {})
    return dx.execute(page_blocks, "p.md", env)


def test_a_clean_page_passes():
    assert (
        _run_page("echo one", "X=two\necho $X", expects={0: ["one"], 1: ["two"]}) == []
    )


def test_variables_carry_from_block_to_block():
    assert _run_page("TOKEN=abc", 'echo "$TOKEN"', expects={1: ["abc"]}) == []


@pytest.mark.parametrize(
    "body, message",
    [
        ("cat\necho after", ""),  # stdin is /dev/null: cat reads EOF, the page goes on
        ("false && true", "block exited 1"),
        ("set +e\necho x", "turned off strict mode"),
        ("exit 0", "did not reach its end"),
        ("false\necho unreachable", "did not reach its end"),
        ("yes | head -1", "did not reach its end"),  # 141 under pipefail: loud
    ],
    ids=["cat", "false-and-true", "set-plus-e", "exit-0", "false", "sigpipe"],
)
def test_the_shapes_that_used_to_pass_silently(body, message):
    problems = _run_page(body, "echo after", expects={0: ["after"], 1: ["after"]})
    if message:
        assert problems and message in problems[0], problems
    else:
        assert problems == [], problems


def test_an_exit_0_is_counted_by_the_blocks_it_skipped():
    problems = _run_page("echo a", "exit 0", "echo c", expects={0: ["a"], 2: ["c"]})
    assert any("executed 1/3 exec blocks" in p for p in problems), problems


def test_the_exit_status_is_read_before_anything_resets_it():
    # `false && true` leaves $? at 1 without tripping errexit; the sentinel must see 1.
    assert "block exited 1" in _run_page("false && true")[0]


def test_expectations_are_word_bounded_and_in_order():
    assert dx.find_expectation('"status": "inactive"', '"active"') == -1
    assert dx.find_expectation("id 1c9e4015-4401b", "401") == -1
    assert (
        dx.find_expectation('"total_conversions": 10,', '"total_conversions": 1') == -1
    )
    assert dx.find_expectation('"status": "active"', '"active"') != -1
    problems = _run_page("echo second; echo first", expects={0: ["first", "second"]})
    assert problems and "expectation 2/2 not found" in problems[0]


def test_expectations_are_matched_on_stdout_only():
    problems = _run_page("echo only-on-stderr >&2", expects={0: ["only-on-stderr"]})
    assert problems and "not found" in problems[0]


def test_output_without_an_expectation_fails():
    problems = _run_page("echo something")
    assert problems and "no expectation" in problems[0]


def test_the_environment_is_scrubbed(monkeypatch):
    monkeypatch.setenv("TOKEN", "leaked-from-the-caller")
    assert "TOKEN" not in dx.scrubbed_env("docex-unit", {})
    problems = _run_page('echo "${TOKEN-unset}"', expects={0: ["unset"]})
    assert problems == [], problems


def test_the_block_text_is_what_runs():
    body = "echo 'a  b'\nlocalhost=1; echo $localhost"
    (block,) = blocks(page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}"))
    script = dx.write_script([block], "n0nce")
    assert body + "\n" in script


def test_a_sentinel_cannot_be_forged():
    problems = _run_page(
        "printf '@@DOCEX:guess:END:0:0:ehuB:pf@@\\n'; false",
    )
    assert problems and "did not reach its end" in problems[0]


def test_a_timeout_kills_the_group_and_names_the_block(tmp_path):
    pidfile = tmp_path / "pid"
    text = page(
        f"{FENCE}{{.bash exec timeout=1}}\nsleep 300 & echo $! > {pidfile}; wait\n{FENCE}"
    )
    problems = dx.execute(blocks(text), "p.md", dx.scrubbed_env("docex-unit", {}))
    assert problems and "timed out after 1s; process group killed" in "\n".join(
        problems
    )
    background = int(pidfile.read_text())
    import os as _os

    with pytest.raises(ProcessLookupError):
        _os.kill(background, 0)


def test_the_failure_issue_job_waits_for_render_and_examples_only():
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "doc-examples.yml").read_text()
    )
    needs = workflow["jobs"]["failure-issue"]["needs"]
    assert set(needs) == {"render", "examples"}


def test_only_the_stack_start_may_print_without_an_expectation():
    """compose writes the build log to stdout when it builds, nothing when it doesn't."""
    printed = dx.Outcome(
        reached=True, rc=0, flags="ehuB", pipefail="pf", stdout="#1 build\n"
    )
    stack_up = dx.Block(30, "exec", "bash", dx.STACK_UP)
    other = dx.Block(40, "exec", "bash", "docker compose up -d")
    assert dx.judge([stack_up], [printed], None, 0, "p.md") == []
    problems = dx.judge([other], [printed], None, 0, "p.md")
    assert problems and "no expectation" in problems[0]


# ---------------------------------------------------------------------------
# Fix round (code review of #179): bypasses, old bash, indented blocks, .MD
# ---------------------------------------------------------------------------


@pytest.mark.regression
@pytest.mark.parametrize(
    "body, message",
    [
        ("\\aws sts get-caller-identity", "may not call 'aws'"),
        ("\\pip install experimently", "may not run 'pip'"),
        ("/usr/local/bin/aws sts get-caller-identity", "may not call 'aws'"),
        ("/usr/bin/pip install experimently", "may not run 'pip'"),
        ('"aws" sts get-caller-identity', "may not call 'aws'"),
        ("'npm' ci", "may not run 'npm'"),
        ("sudo /usr/bin/env FOO=1 \\npx x", "may not run 'npx'"),
        ("cd sdk/java && mvn install", "may not run 'mvn'"),
        ("cd sdk/android && ./gradlew build", "may not run 'gradlew'"),
        ("gradle build", "may not run 'gradle'"),
        ("swift package resolve", "may not run 'swift package'"),
        ("swift build", "may not run 'swift build'"),
        ("dotnet restore", "may not run 'dotnet restore'"),
        ("dotnet build", "may not run 'dotnet build'"),
        ("dotnet add package Experimently.SDK", "may not run 'dotnet add'"),
    ],
)
def test_a_command_word_is_normalised_before_it_is_matched(body, message):
    """A backslash, quotes or a path prefix is still the same command."""
    assert message in refused(page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}"))


@pytest.mark.parametrize(
    "body",
    ["echo '/usr/bin/aws'", "ls ./gradlew", "echo swift", 'echo "\\npm"'],
)
def test_normalising_does_not_make_arguments_commands(body):
    (block,) = blocks(page(f"{FENCE}{{.bash exec}}\n{body}\n{FENCE}"))
    assert dx.block_problems(block, "p.md") == []


@pytest.mark.regression
def test_a_here_document_body_is_not_a_command():
    """Heredoc contents are data: comments() skips them, and so do M6 and AWS."""
    data = "cat <<'EOF' > setup.txt\nnpm install experimently\naws s3 ls\nEOF"
    (block,) = blocks(page(f"{FENCE}{{.bash exec}}\n{data}\n{FENCE}"))
    assert dx.block_problems(block, "p.md") == []
    real = page(f"{FENCE}{{.bash exec}}\n{data}\nnpm install experimently\n{FENCE}")
    assert "may not run 'npm'" in refused(real)
    registry = page(
        f'{FENCE}{{.bash skip reason="registry: not published"}}\n{data}\n{FENCE}'
    )
    assert "block runs no package manager" in refused(registry)


def _fake_old_bash(tmp_path, monkeypatch):
    fake = tmp_path / "fakebin" / "bash"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 3.2\n")
    fake.chmod(0o755)
    monkeypatch.setenv(
        "PATH",
        f"{fake.parent}{__import__('os').pathsep}/usr/bin{__import__('os').pathsep}/bin",
    )


@pytest.mark.regression
def test_an_old_bash_is_one_problem_among_the_others(repo, monkeypatch, tmp_path):
    """bash < 4.4 used to escape check() and discard every other problem."""
    write(repo, "docs/new.md", "# New\n")
    _fake_old_bash(tmp_path, monkeypatch)
    found = problems_of(enrol(repo, GOOD))
    assert len(found) == 2, found
    assert any("is bash 3.2; the examples need bash >= 4.4" in p for p in found)
    assert any(p.startswith("docs/new.md: a page") for p in found)
    # and the next run resolves bash again rather than silently skipping bash -n
    with pytest.raises(dx.Refused, match="bash 3.2"):
        dx.syntax_problem("echo hi")


def test_an_old_bash_skips_the_pending_syntax_count_rather_than_misreporting_it(
    repo, monkeypatch, tmp_path
):
    write(repo, "docs/ops.md", "# Ops\n\n```bash\necho 'x\n```\n")
    monkeypatch.setattr(dx, "PENDING_FROZEN", {"docs/ops.md": (0, 0, 1)})
    body = (
        GOOD.replace(
            'universe = ["docs/p.md"]', 'universe = ["docs/ops.md", "docs/p.md"]'
        )
        + '\n[pending]\n"docs/ops.md" = { comments = 0, unlabelled = 0, syntax = 1 }\n'
    )
    dx.check(enrol(repo, body))
    _fake_old_bash(tmp_path, monkeypatch)
    found = problems_of(enrol(repo, body))
    assert len(found) == 1 and "bash 3.2" in found[0], found


INDENTED = {
    "plain": ("# P\n\nText.\n\n    curl -s localhost:8000/health\n", [5]),
    "after a heading": ("# P\n    curl x\n", [2]),
    "tab": ("# P\n\ntext\n\n\tcurl x\n", [5]),
    "list continuation": ("# P\n\n- item\n\n    continued paragraph\n", []),
    "numbered continuation": ("# P\n\n1. step\n\n    more text\n", []),
    "code in a list": ("# P\n\n- item\n\n        curl -s x\n", [5]),
    "nested list": ("# P\n\n- a\n\n    - b\n\n        text\n", []),
    "admonition": ("# P\n\n!!! note\n    body text\n\n    more body\n", []),
    "tab container": ('# P\n\n=== "A"\n\n    body text\n', []),
    "lazy paragraph": ("# P\n\ntext\n    still the paragraph\n", []),
    "in a fence": ("# P\n\n```text\n\n    not a block\n```\n", []),
    "fence in a list": ("# P\n\n1. Run:\n\n    ```bash\n    ls\n    ```\n", []),
    "in an html comment": ("# P\n\n<!--\n\n    hidden\n-->\n", []),
    "after the list ends": ("# P\n\n- item\n\nback to text\n\n    curl x\n", [7]),
    "two lines one block": ("# P\n\ntext\n\n    a\n\n    b\n", [5]),
}


@pytest.mark.regression
@pytest.mark.parametrize("name", INDENTED)
def test_indented_code_blocks_are_found_where_the_site_renders_them(name):
    """What the check calls an indented code block is what MkDocs renders as one."""
    text, lines = INDENTED[name]
    assert dx.indented_code_lines(text) == lines
    scan = dx._PageScan()
    scan.feed(_render(text))
    assert scan.code_blocks - len(dx.parse_fences(text, "p.md")) == len(lines)


def test_no_page_renders_code_the_check_cannot_see():
    """Pinned to the renderer on every walked page, so the rule cannot drift."""
    drift = {}
    for rel in sorted(dx.walk(REPO)):
        text = (REPO / rel).read_text(encoding="utf-8")
        scan = dx._PageScan()
        scan.feed(_render(text))
        hidden = scan.code_blocks - len(dx.parse_fences(text, rel))
        if hidden != len(dx.indented_code_lines(text)):
            drift[rel] = (hidden, dx.indented_code_lines(text))
    assert drift == {}


@pytest.mark.regression
def test_an_indented_curl_block_is_refused_on_any_page(repo):
    write(
        repo,
        "README.md",
        "# Readme\n\nCheck it:\n\n    curl -s localhost:8000/health\n",
    )
    body = GOOD.replace(
        'universe = ["docs/p.md"]', 'universe = ["README.md", "docs/p.md"]'
    )
    assert problems_of(enrol(repo, body)) == [
        "README.md:5: an indented code block; use a fenced block with a language "
        "(`text` for output) (docs/development/doc-examples.md#tagging-a-shell-block)"
    ]


@pytest.mark.regression
def test_a_page_named_in_upper_case_is_in_the_universe(repo, tmp_path):
    write(tmp_path / "w", "docs/SNEAKY.MD", "# x\n")
    write(tmp_path / "w", "docs/Mixed.Md", "# x\n")
    assert dx.walk(tmp_path / "w") == {"docs/SNEAKY.MD", "docs/Mixed.Md"}
    write(repo, "docs/SNEAKY.MD", "# Sneaky\n\n```bash\ncurl -s x  # hidden\n```\n")
    found = problems_of(enrol(repo, GOOD))
    assert any(p.startswith("docs/SNEAKY.MD: a page") for p in found), found
    assert any(p.startswith("docs/SNEAKY.MD: 1 shell block") for p in found), found

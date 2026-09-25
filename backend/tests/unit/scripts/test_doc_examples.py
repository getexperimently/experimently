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
        {FENCE}{{.bash skip reason="needs a browser"}}
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
    assert (skip.kind, skip.reason) == ("skip", "needs a browser")


@pytest.mark.parametrize(
    "info, message",
    [
        ("bash", "untagged shell fence"),
        ("sh", "untagged shell fence"),
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
        ("{.sh exec}", "only .bash blocks run"),
        ("{.python exec}", "not shell"),
        ("{.bash .python exec}", "exactly one language class"),
    ],
)
def test_malformed_tags_are_refused(info, message):
    text = page(f"{FENCE}{info}\necho hi\n{FENCE}")
    assert message in refused(text)


def test_an_expectation_after_a_skip_or_a_json_block_is_refused():
    skip = page(f'{FENCE}{{.bash skip reason="x"}}\necho\n{FENCE}\n<!-- expect: y -->')
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
    """A scratch repository root with one enrolled page."""
    monkeypatch.setattr(dx, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "p.md").write_text(
        page(
            f"{FENCE}{{.bash exec}}\necho hi\n{FENCE}\n<!-- expect: hi -->",
            f'{FENCE}{{.bash skip reason="x"}}\necho no\n{FENCE}',
        )
    )
    return tmp_path


def enrol(root, body: str) -> pathlib.Path:
    path = root / "doc_examples.toml"
    path.write_text(textwrap.dedent(body))
    return path


GOOD = """
    [meta]
    documents = 1

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


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("expects = 1", "expects = 2", "expects 1 != 2 enrolled"),
        ("exec = 1", "exec = 0", "exec 1 != 0 enrolled"),
        (
            "documents = 1",
            "documents = 2",
            "enrolled 1 document(s); [meta] documents = 2",
        ),
        ('environment = "bare"', 'environment = "local"', "'local' is not implemented"),
        ('environment = "bare"', 'environment = "cloud"', "is not one of"),
        ('path = "docs/p.md"', 'path = "docs/missing.md"', "is not a markdown file"),
        ('path = "docs/p.md"', 'path = "../p.md"', "is not a markdown file"),
    ],
)
def test_enrolment_mismatches_are_refused(repo, old, new, message):
    with pytest.raises(dx.Refused, match=__import__("re").escape(message)):
        dx.check(enrol(repo, GOOD.replace(old, new)))


def test_working_instructions_cannot_be_enrolled(repo):
    (repo / "CLAUDE.md").write_text("# x\n")
    with pytest.raises(dx.Refused, match="working instructions"):
        dx.check(enrol(repo, GOOD.replace("docs/p.md", "CLAUDE.md")))


def test_a_stack_page_needs_exactly_one_stack_start(repo):
    qs = repo / "docs" / "getting-started"
    qs.mkdir()
    one = f"{FENCE}{{.bash exec}}\ndocker compose up -d --wait\n{FENCE}"
    two = one + "\n\n" + one
    body = GOOD.replace("documents = 1", "documents = 2").replace(
        'environment = "bare"', 'environment = "stack"'
    ) + textwrap.dedent(
        """
        [[document]]
        path = "docs/getting-started/quick-start.md"
        environment = "bare"
        exec = {n}
        skip = 0
        expects = 0
        """
    )
    (qs / "quick-start.md").write_text(page(one))
    dx.check(enrol(repo, body.format(n=1)))
    (qs / "quick-start.md").write_text(page(two))
    with pytest.raises(dx.Refused, match="2 exec blocks equal"):
        dx.check(enrol(repo, body.format(n=2)))


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
        f'{FENCE}{{.bash skip reason="x"}}\necho no\n{FENCE}',
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
        page(f'{FENCE}{{.bash skip reason="a"}} trailing\necho x\n{FENCE}'),
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

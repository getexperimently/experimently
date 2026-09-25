#!/usr/bin/env python3
"""The documentation's shell examples: tagged, counted, and rendered as code.

A document is *enrolled* in ``scripts/doc_examples.toml``.  In an enrolled
document every shell fence says whether it runs::

    ```{.bash exec}                      runs (timeout 120 s)
    ```{.bash exec timeout=1200}         runs, with its own timeout
    ```{.bash skip reason="..."}         does not run, and says why

and a block that runs may be followed, with no blank line, by the output the
page promises::

    <!-- expect: "healthy" -->

This file is the contract (docs/development/doc-examples.md explains it to
authors).  It checks, without running anything:

``--check``
    every enrolled document parses; every shell fence is tagged in the one form
    superfences renders as code and GitHub shows cleanly; nothing a reader could
    not paste is in a block (a ``#`` comment breaks zsh, a masked ``$(...)``
    hides a failure); every block that runs passes ``bash -n``; and the numbers
    of documents, run blocks, skipped blocks and expectations are exactly what
    the enrolment file says.  Prints the counts.

``--render SITE_DIR``
    after ``mkdocs build``: every enrolled page under ``docs/`` renders each of
    its fences as a code block, and no fence leaked into a paragraph.

Running the examples is ``--run`` (not yet implemented; it arrives with the
execution environments).  Standard library only.
"""

from __future__ import annotations

import argparse
import dataclasses
import html.parser
import pathlib
import re
import subprocess
import sys
import tomllib
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENROLMENT = ROOT / "scripts" / "doc_examples.toml"

SHELL = ("bash", "sh", "shell", "console")
ENVIRONMENTS = ("bare", "stack", "local")
DEFAULT_TIMEOUT = 120

# The document a ``stack`` document's stack is started from, and the one command
# in it that starts the stack.  Coupled by assertion (``_check_stack``), not by
# a copy: a quick-start edit that changes the command fails here.
STACK_DOC = "docs/getting-started/quick-start.md"
STACK_UP = "docker compose up -d --wait"


class Refused(Exception):
    """A document or the enrolment breaks the contract; nothing is run."""


@dataclasses.dataclass
class Fence:
    line: int  # 1-based line of the opening fence
    marker: str  # the backticks or tildes that open it
    info: str  # everything after the marker, stripped
    body: list[str]  # content lines, de-indented by the opener's indentation
    trailing: list[str] = dataclasses.field(
        default_factory=list
    )  # lines after the close


@dataclasses.dataclass
class Block:
    """A shell fence in an enrolled document."""

    line: int
    kind: str  # "exec" or "skip"
    lang: str
    body: str
    timeout: int = DEFAULT_TIMEOUT
    reason: str = ""
    expects: list[str] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Fences (CommonMark-shaped: an opener, content, a closer at least as long)
# ---------------------------------------------------------------------------

# Any indentation: superfences renders a fence nested in a list item (four or more
# spaces) as code too, so such a fence is a block like any other.
_OPENER = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>`{3,}|~{3,})(?P<info>.*)$")


def parse_fences(text: str, name: str) -> list[Fence]:
    """Every top-level fence in *text*.  An unclosed fence is refused."""
    lines = text.split("\n")
    fences: list[Fence] = []
    i = 0
    while i < len(lines):
        match = _OPENER.match(lines[i])
        if not match or (
            match.group("marker")[0] == "`" and "`" in match.group("info")
        ):
            i += 1
            continue
        indent, marker = len(match.group("indent")), match.group("marker")
        start = i
        body: list[str] = []
        i += 1
        while i < len(lines):
            closer = lines[i].strip()
            if closer and set(closer) == {marker[0]} and len(closer) >= len(marker):
                break
            body.append(
                lines[i][indent:] if lines[i][:indent].strip() == "" else lines[i]
            )
            i += 1
        else:
            raise Refused(f"{name}:{start + 1}: unclosed fence ({marker})")
        fence = Fence(start + 1, marker, match.group("info").strip(), body)
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith("<!-- expect"):
            fence.trailing.append(lines[j])
            j += 1
        fences.append(fence)
        i += 1
    return fences


# ---------------------------------------------------------------------------
# The tag grammar
# ---------------------------------------------------------------------------

_BRACE = re.compile(r"^\{(?P<inner>[^{}]*)\}(?P<rest>.*)$")
_ATTR = re.compile(
    r'\s*(?:(?P<key>[a-z_]+)=(?:"(?P<quoted>[^"]*)"|(?P<bare>\S+))|(?P<word>\S+))'
)
_EXPECT = re.compile(r"^\s*<!-- expect: (?P<text>.+?) -->\s*$")


def _names_shell(info: str) -> bool:
    first = info.split()[0] if info.split() else ""
    return first.lstrip("{.").rstrip("}") in SHELL


def classify(fence: Fence, name: str) -> Optional[Block]:
    """The Block for a shell fence, None for any other fence; Refused if malformed."""
    where = f"{name}:{fence.line}"
    info = fence.info
    if not info.startswith("{"):
        if info.split()[:1] and info.split()[0] in SHELL:
            if len(info.split()) > 1:
                raise Refused(
                    f"{where}: refused: '{info}' is not brace form "
                    f"(superfences renders it as a paragraph); write {{.{info.split()[0]} ...}}"
                )
            raise Refused(
                f"{where}: untagged shell fence '```{info}'; tag it "
                f'{{.bash exec}} or {{.{info} skip reason="..."}}'
            )
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return None
    brace = _BRACE.match(info)
    if not brace:
        raise Refused(f"{where}: refused: malformed brace info string '{info}'")
    if brace.group("rest").strip():
        raise Refused(f"{where}: refused: text after '}}' (it breaks the fence)")
    tokens = [m for m in _ATTR.finditer(brace.group("inner")) if m.group(0).strip()]
    words = [t.group("word") for t in tokens if t.group("word")]
    classes = [w[1:] for w in words if w.startswith(".")]
    words = [w for w in words if not w.startswith(".")]
    if not classes:
        if any(w in SHELL for w in words):
            raise Refused(
                f"{where}: refused: brace fence names a shell language without '.'"
            )
        lang = ""
    elif len(classes) > 1 or not (tokens[0].group("word") or "").startswith("."):
        if any(c in SHELL for c in classes):
            raise Refused(f"{where}: refused: exactly one language class, and first")
        lang = ""
    else:
        lang = classes[0]
    if lang not in SHELL:  # not a shell fence: not ours to judge, but it never runs
        if "exec" in words or "skip" in words:
            raise Refused(f"{where}: refused: exec/skip on a fence that is not shell")
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return None
    attrs: dict[str, str] = {}
    for t in tokens:
        if t.group("key"):
            key = t.group("key")
            if key in attrs:
                raise Refused(f"{where}: refused: duplicate attribute '{key}'")
            attrs[key] = (
                t.group("quoted") if t.group("quoted") is not None else t.group("bare")
            )
    kinds = [w for w in words if w in ("exec", "skip")]
    unknown = [w for w in words if w not in ("exec", "skip")] + [
        k for k in attrs if k not in ("timeout", "reason")
    ]
    if unknown:
        raise Refused(f"{where}: refused: unknown attribute(s) {unknown}")
    if len(kinds) != 1:
        raise Refused(
            f"{where}: refused: a shell fence carries exactly one of exec or skip"
        )
    kind = kinds[0]
    body = "\n".join(fence.body)
    if kind == "skip":
        reason = attrs.get("reason", "")
        if not reason.strip() or len(reason) > 200:
            raise Refused(
                f'{where}: refused: skip needs reason="..." (1-200 characters)'
            )
        if "timeout" in attrs:
            raise Refused(f"{where}: refused: timeout on a block that does not run")
        if fence.trailing:
            raise Refused(f"{where}: an expectation follows a block that does not run")
        return Block(fence.line, "skip", lang, body, reason=reason)
    if lang != "bash":
        raise Refused(f"{where}: refused: only .bash blocks run (the runner is bash)")
    if "reason" in attrs:
        raise Refused(f"{where}: refused: reason on a block that runs")
    timeout = DEFAULT_TIMEOUT
    if "timeout" in attrs:
        if (
            not re.fullmatch(r"[0-9]{1,4}", attrs["timeout"])
            or not 1 <= int(attrs["timeout"]) <= 3600
        ):
            raise Refused(f"{where}: refused: timeout must be 1-3600 seconds")
        timeout = int(attrs["timeout"])
    expects = []
    for line in fence.trailing:
        match = _EXPECT.match(line)
        text = match.group("text").strip() if match else ""
        if not match or not text or len(text) > 200 or "-->" in text:
            raise Refused(f"{where}: refused: malformed expectation {line.strip()!r}")
        expects.append(text)
    return Block(fence.line, "exec", lang, body, timeout=timeout, expects=expects)


# ---------------------------------------------------------------------------
# What may be in a block
# ---------------------------------------------------------------------------

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(?P<word>[A-Za-z_][A-Za-z0-9_]*)\1")
_MASKED = re.compile(r"^\s*(export|declare|local|readonly)\s+[A-Za-z_]\w*=\$\(")
# Ways a block could reach past the runner's compose project (PR-2b isolates each
# document with COMPOSE_PROJECT_NAME).  The quick-start's own plain
# `docker compose down -v` is allowed: under that isolation it removes only the
# runner's project.
_ESCAPES = (
    (re.compile(r"COMPOSE_PROJECT_NAME"), "sets or clears COMPOSE_PROJECT_NAME"),
    (
        re.compile(r"docker\s+compose\b[^\n]*\s(-p\b|--project-name\b)"),
        "names a compose project",
    ),
    (
        re.compile(r"\benv\s+(-u\b|-i\b|--unset\b|--ignore-environment\b)"),
        "rewrites the environment",
    ),
    (re.compile(r"\bunset\s+COMPOSE"), "clears a compose setting"),
    (
        re.compile(
            r"\bdocker\s+(volume|container|network|system|image)\s+(rm|prune)\b"
        ),
        "removes Docker resources directly",
    ),
    (re.compile(r"\bdocker\s+rm\b"), "removes containers directly"),
)


def comment_lines(body: str) -> list[int]:
    """0-based lines of *body* that carry a shell comment.

    A ``#`` starts a comment only outside quotes and at the start of a word, so
    ``$#``, ``${#x}``, ``a#b`` and a URL's ``#anchor`` are not comments.  Lines
    inside a here-document are data, not shell, and are skipped.
    """
    found, terminator = [], None
    for number, line in enumerate(body.split("\n")):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        quote = None
        for column, char in enumerate(line):
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char == "#" and (column == 0 or line[column - 1] in " \t;&|("):
                found.append(number)
                break
        heredoc = _HEREDOC.search(line)
        if heredoc:
            terminator = heredoc.group("word")
    return found


def lint_block(block: Block, name: str) -> None:
    where = f"{name}:{block.line}"
    for offset in comment_lines(block.body):
        raise Refused(
            f"{name}:{block.line + 1 + offset}: refused: shell comment in an example "
            "(breaks when pasted into zsh; say it in the prose)"
        )
    if block.kind != "exec":
        return
    if not block.body.strip():
        raise Refused(f"{where}: refused: empty block")
    last = [line for line in block.body.split("\n") if line.strip()][-1]
    if last.rstrip().endswith("\\"):
        raise Refused(
            f"{where}: refused: last line ends in '\\' (it would swallow what follows)"
        )
    for line in block.body.split("\n"):
        if _MASKED.search(line):
            raise Refused(
                f"{where}: refused: 'export X=$(...)' masks the substitution's exit "
                "status; assign, then export"
            )
    for pattern, what in _ESCAPES:
        if pattern.search(block.body):
            raise Refused(f"{where}: refused: the block {what}")
    check = subprocess.run(
        ["bash", "--noprofile", "--norc", "-n"],
        input=block.body,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0 or check.stderr.strip():
        raise Refused(f"{where}: syntax (bash -n): {check.stderr.strip() or 'failed'}")


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

_DOC_KEYS = {"path", "environment", "exec", "skip", "expects"}


def load_enrolment(path: pathlib.Path = ENROLMENT) -> list[dict]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    unknown = set(data) - {"meta", "document"}
    if unknown:
        raise Refused(f"{path.name}: unknown table(s) {sorted(unknown)}")
    meta = data.get("meta", {})
    if set(meta) != {"documents"} or not isinstance(meta["documents"], int):
        raise Refused(f"{path.name}: [meta] must be exactly 'documents = <n>'")
    documents = data.get("document", [])
    if len(documents) != meta["documents"]:
        raise Refused(
            f"enrolled {len(documents)} document(s); [meta] documents = {meta['documents']}"
        )
    seen = set()
    for doc in documents:
        if set(doc) != _DOC_KEYS:
            raise Refused(
                f"{path.name}: a document has keys {sorted(doc)}; want {sorted(_DOC_KEYS)}"
            )
        rel = doc["path"]
        if rel in seen:
            raise Refused(f"{path.name}: {rel} enrolled twice")
        seen.add(rel)
        target = ROOT / rel
        if (
            rel.startswith("/")
            or ".." in pathlib.PurePosixPath(rel).parts
            or not rel.endswith(".md")
            or not target.is_file()
        ):
            raise Refused(
                f"{path.name}: {rel} is not a markdown file in the repository"
            )
        if pathlib.PurePosixPath(rel).name == "CLAUDE.md" or rel.startswith(".claude/"):
            raise Refused(
                f"{path.name}: {rel} is working instructions, not documentation (T1)"
            )
        if doc["environment"] not in ENVIRONMENTS:
            raise Refused(
                f"{rel}: environment {doc['environment']!r} is not one of {ENVIRONMENTS}"
            )
        if doc["environment"] == "local":
            raise Refused(
                f"{rel}: environment 'local' is not implemented yet (the demo applications)"
            )
        for key in ("exec", "skip", "expects"):
            if not isinstance(doc[key], int) or doc[key] < 0:
                raise Refused(f"{rel}: {key} must be a non-negative integer")
    return documents


def blocks_of(rel: str) -> list[Block]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    blocks = [b for f in parse_fences(text, rel) if (b := classify(f, rel)) is not None]
    for block in blocks:
        lint_block(block, rel)
    return blocks


def _check_stack(documents: list[dict], parsed: dict[str, list[Block]]) -> None:
    if not any(d["environment"] == "stack" for d in documents):
        return
    stack_doc = next((d for d in documents if d["path"] == STACK_DOC), None)
    if stack_doc is None or stack_doc["environment"] != "bare":
        raise Refused(f"a 'stack' document needs {STACK_DOC} enrolled as 'bare'")
    ups = [
        b for b in parsed[STACK_DOC] if b.kind == "exec" and b.body.strip() == STACK_UP
    ]
    if len(ups) != 1:
        raise Refused(
            f"{STACK_DOC}: {len(ups)} exec blocks equal {STACK_UP!r} (expected exactly 1)"
        )


def check(path: pathlib.Path = ENROLMENT, out=sys.stdout) -> dict[str, dict[str, int]]:
    documents = load_enrolment(path)
    parsed = {d["path"]: blocks_of(d["path"]) for d in documents}
    _check_stack(documents, parsed)
    counts, mismatches = {}, []
    for doc in documents:
        blocks = parsed[doc["path"]]
        got = {
            "exec": sum(b.kind == "exec" for b in blocks),
            "skip": sum(b.kind == "skip" for b in blocks),
            "expects": sum(len(b.expects) for b in blocks),
        }
        counts[doc["path"]] = got
        print(
            f"{doc['path']}: {got['exec']} exec, {got['skip']} skip, "
            f"{got['expects']} expects ({doc['environment']})",
            file=out,
        )
        for key, value in got.items():
            if value != doc[key]:
                mismatches.append(
                    f"{doc['path']}: {key} {value} != {doc[key]} enrolled"
                )
    if mismatches:
        raise Refused("; ".join(mismatches))
    print(f"{len(documents)} document(s): contract holds", file=out)
    return counts


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class _PageScan(html.parser.HTMLParser):
    """Count code blocks, and collect what each <p> says outside and inside <code>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.code_blocks = 0
        self.paragraphs: list[dict] = []
        self._stack: list[str] = []
        self._p: Optional[dict] = None

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and "highlight" in classes:
            self.code_blocks += 1
        self._stack.append(tag)
        if tag == "p":
            self._p = {"outside": "", "codes": [], "children": 0, "in_code": False}
        elif self._p is not None:
            self._p["children"] += 1
            if tag == "code":
                self._p["in_code"] = True
                self._p["codes"].append("")

    def handle_endtag(self, tag):
        while self._stack and self._stack.pop() != tag:
            pass
        if tag == "code" and self._p is not None:
            self._p["in_code"] = False
        if tag == "p" and self._p is not None:
            self.paragraphs.append(self._p)
            self._p = None

    def handle_data(self, data):
        if self._p is None:
            return
        if self._p["in_code"]:
            self._p["codes"][-1] += data
        else:
            self._p["outside"] += data


def render_problems(source: str, page_html: str, name: str) -> list[str]:
    """What is wrong with how *page_html* rendered *source*'s fences."""
    problems = []
    fences = len(parse_fences(source, name))
    scan = _PageScan()
    scan.feed(page_html)
    if scan.code_blocks != fences:
        problems.append(
            f"{name}: {scan.code_blocks} rendered code blocks, {fences} fences in source"
        )
    for p in scan.paragraphs:
        leaked = any(
            line.lstrip().startswith(("```", "~~~"))
            for line in p["outside"].split("\n")
        )
        only_code = (
            p["children"] == 1 and len(p["codes"]) == 1 and not p["outside"].strip()
        )
        if leaked or (only_code and "\n" in p["codes"][0]):
            problems.append(
                f"{name}: a fence rendered as a paragraph: {p['outside'][:80]!r}"
            )
    return problems


def render(site: pathlib.Path, path: pathlib.Path = ENROLMENT, out=sys.stdout) -> None:
    problems = []
    for doc in load_enrolment(path):
        rel = pathlib.PurePosixPath(doc["path"])
        if rel.parts[0] != "docs":
            continue  # outside docs/, MkDocs builds no page (T1's stated asymmetry)
        page_rel = rel.relative_to("docs").with_suffix("")
        if page_rel.name in ("README", "index"):
            page = site / page_rel.parent / "index.html"
        else:
            page = site / page_rel / "index.html"
        if not page.is_file():
            problems.append(f"{rel}: no page at {page} (excluded from the site?)")
            continue
        problems += render_problems(
            (ROOT / rel).read_text(encoding="utf-8"),
            page.read_text(encoding="utf-8"),
            str(rel),
        )
        print(f"{rel}: rendered", file=out)
    if problems:
        raise Refused("\n".join(problems))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate tags and counts")
    mode.add_argument(
        "--render", metavar="SITE_DIR", type=pathlib.Path, help="check a built site"
    )
    mode.add_argument(
        "--run", action="store_true", help="run the examples (not yet implemented)"
    )
    args = parser.parse_args(argv)
    try:
        if args.check:
            check()
        elif args.render:
            render(args.render)
        else:
            print("--run is not implemented yet", file=sys.stderr)
            return 2
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

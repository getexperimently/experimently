"""What the deploy documentation promises an operator (UX section B, CHECK 6).

`mkdocs build --strict` checks links between documents; it cannot see a link
printed by a workflow's `::error::`. These do: every
`docs/<path>.md#<anchor>` a refusal sends an operator to must be a heading
that exists. And the runbook must be usable for either environment, without
the step that deleted a published release tag mid-incident.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DOCS = REPO_ROOT / "docs"
RUNBOOK = DOCS / "deployment" / "rollback-runbook.md"
GUIDE = DOCS / "deployment" / "deployment-guide.md"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="this tree has no docs")


def _slug(heading: str) -> str:
    """The anchor mkdocs' default `toc` extension gives a heading."""
    text = re.sub(r"[`*]", "", heading.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s]+", "-", text).strip("-")


def _anchors(path: Path) -> set[str]:
    return {
        _slug(m.group(1))
        for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", path.read_text(), re.M)
    }


@pytest.mark.regression
def test_every_doc_anchor_a_workflow_prints_exists():
    links = set()
    for name in ("deploy.yml", "rollback.yml", "db-migrate.yml"):
        text = (WORKFLOWS / name).read_text()
        links |= set(re.findall(r"(docs/[\w/.-]+\.md)#([\w-]+)", text))
    assert len(links) >= 2, f"found only {links}: the scan is not reading"
    for doc, anchor in sorted(links):
        path = REPO_ROOT / doc
        assert path.is_file(), f"a workflow links {doc}, which does not exist"
        assert anchor in _anchors(path), (
            f"a workflow sends operators to {doc}#{anchor}; that heading does "
            f"not exist (it has {sorted(_anchors(path))})"
        )


@pytest.mark.regression
def test_the_runbook_works_for_either_environment():
    text = RUNBOOK.read_text()
    assert "export ENV=prod   # or staging" in text
    fences = re.findall(r"```bash\n(.*?)```", text, re.S)
    code = "\n".join(fences)
    for literal in ("experimentation-prod", "backend-prod", "platform-prod", "-prod-"):
        assert literal not in code, f"a runbook command names {literal!r}"


@pytest.mark.regression
def test_the_runbook_does_not_delete_a_release_tag():
    text = RUNBOOK.read_text()
    assert ":refs/tags/" not in text
    assert "git tag -d" not in text


def test_the_guide_has_the_ordered_checklist():
    headings = [
        m.group(1) for m in re.finditer(r"^### (1\.\d) ", GUIDE.read_text(), re.M)
    ]
    assert headings == ["1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6"], headings
    text = GUIDE.read_text()
    # Protection before any variable or secret (EM C12).
    assert text.index("required reviewer") < text.index("Variables `AWS_ACCOUNT_ID`")
    # The OIDC subject is decoded before the trust policy is written (PE C5).
    assert "Decode a\n  real token" in text or "decode a real token" in text.lower()

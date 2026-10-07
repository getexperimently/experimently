"""Every page in the docs navigation is classified for end-to-end verification (#939).

``tests/acceptance/docs/inventory.toml`` gives each page that the ``nav`` of
``mkdocs.yml`` lists exactly one class saying how the page is verified, with a
one-line reason, and maps each flow in the "Flows, at least" list of #939 to
what verifies it. The file's header is the contract; this test holds it:

* every nav page has an entry, and every entry is a nav page (keys are the
  paths exactly as the nav writes them, so a page the nav lists twice is one
  key, and a second entry for it is a TOML parse error);
* the class is one of ``CLASSES`` or ``external:<service>`` with a slug for the
  service, and only the fields that class allows are present;
* a ``journey`` names its id, a slug no other page uses, and either its
  expectations file ``tests/acceptance/docs/journeys/<id>.yaml`` exists or the
  entry says ``pending = true`` (refused once the file exists, so a pending
  flag cannot outlive the journey it stands for) and ``planned``, the pull
  request that writes it (one of ``PLANNED``; only on a pending journey, so
  the run summary can say where each journey not yet written comes from);
* an ``exec`` page is enrolled in ``scripts/doc_examples.toml`` with at least
  one exec block;
* a ``workflow`` page names a workflow whose ``on.<event>.paths`` lists the
  page's own path, ``docs/<page>``, as a literal entry. The workflow file is
  parsed, not searched: a comment or a step name that mentions the page does
  not count, and neither does a glob such as ``docs/**`` (#1075);
* an ``aws`` page says which step exercises it in ``exercised_by``: a list of
  values from ``EXERCISED_BY`` -- the ten steps of #295 word for word, ``605``
  or ``production-deploy`` -- or ``["none"]`` when no step does (#1075). It
  records which step exercises the page, never whether that step has run;
* every flow of #939 (``FLOWS_939``, copied from the issue) is mapped, to
  declared journeys, to classified pages or to a class some page has.

The planted-defect tests below run the same check on small inventories with
one defect each, so each refusal is seen to fire.

``mkdocs.yml`` is read with a YAML loader that accepts any tag (a MkDocs config
may carry ``!ENV`` or ``!!python/name:``), building the tagged node as plain
YAML. Reads only files; no git, so it runs the same in
``scripts/core_build.sh``'s copy. It is in the docs-only gate's "Docs content
tests" through its directory, ``backend/tests/unit/docs/``.
"""

from __future__ import annotations

import posixpath
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

import pytest
import yaml

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[4]
MKDOCS = REPO_ROOT / "mkdocs.yml"
INVENTORY = REPO_ROOT / "tests" / "acceptance" / "docs" / "inventory.toml"
JOURNEYS = REPO_ROOT / "tests" / "acceptance" / "docs" / "journeys"
DOC_EXAMPLES = REPO_ROOT / "scripts" / "doc_examples.toml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The classes a page can have, besides ``external:<service>``. Pinned: a new
#: class is a change to the plan, not to this file alone.
CLASSES: Tuple[str, ...] = ("journey", "exec", "workflow", "reference", "aws", "device")
EXTERNAL = re.compile(r"external:(?P<service>.*)", re.DOTALL)
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

#: The fields each class may carry; ``class`` and ``reason`` are required on all.
FIELDS: Dict[str, Set[str]] = {
    "journey": {"class", "reason", "journey", "pending", "planned"},
    "workflow": {"class", "reason", "workflow"},
    "aws": {"class", "reason", "exercised_by"},
}
PLAIN_FIELDS = {"class", "reason"}
#: The pull requests of the QA plan (#897, #939) a pending journey may name.
PLANNED: Tuple[str, ...] = ("D2", "D3a", "D3b", "unassigned")
FLOW_FIELDS = {"text", "note", "journeys", "pages", "classes"}

#: The steps of #295 (the first deploy to a real staging account, and a
#: rollback rehearsal), verbatim but for each line's closing punctuation. When
#: the issue's list changes, change this and the mapping.
STEPS_295: Tuple[str, ...] = (
    "bootstrap the account",
    "create the image repositories and a bootstrap image",
    "set up GitHub OIDC access for the deploy workflow",
    "run the first stack deploy",
    "migrate",
    "smoke through the load balancer on a non-probe path",
    "deploy a second release and roll back",
    "force a circuit breaker and an alarm rollback",
    "replace the invented test fixtures with captured output",
    "tear down, with the residue measured",
)
#: Everything an aws page's ``exercised_by`` may name, and nothing else: the
#: steps of #295, ``605`` (#605, which removes two DynamoDB tables after an
#: on-demand backup of each), ``production-deploy`` (the first deploy to
#: production) and ``none``, which stands alone.
NONE = "none"
EXERCISED_BY: Tuple[str, ...] = STEPS_295 + ("605", "production-deploy", NONE)

#: The "Flows, at least" list of #939, verbatim but for each line's closing
#: punctuation. When the issue's list changes, change this and the mapping.
FLOWS_939: Tuple[str, ...] = (
    "the docs site: every page in the nav reachable, links resolve, search works,"
    " the power analysis and sample size pages render and calculate",
    "Quick Start, end to end",
    "the Docker Compose guide: start the stack as written, open the dashboard, sign in",
    "feature flags: create, targeting, gradual rollout, safety monitoring",
    "experiments: the guided builder, assign, track, results (including the"
    " statistics the guide promises)",
    "the dashboard-and-API guide and the API examples (the `{.bash exec}` blocks"
    " that `doc-examples.yml` already runs)",
    "the SDK quick starts",
    "self-hosting guides where they can be rehearsed without AWS",
    "any other first-run flow the plan identifies",
)

HOW_TO_FIX = (
    "Each nav page needs one entry in tests/acceptance/docs/inventory.toml: "
    '[pages."<path as the nav writes it>"] with class = one of '
    + ", ".join(CLASSES)
    + ', external:<service>, and a one-line reason = "...". '
    "The file's header says what each class means."
)


# ---------------------------------------------------------------------------
# Reading the inputs
# ---------------------------------------------------------------------------
class _AnyTagLoader(yaml.SafeLoader):
    """A safe loader that builds a node with an unknown tag as plain YAML."""


def _untagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


# The empty prefix matches every tag the safe loader has no constructor for.
_AnyTagLoader.add_multi_constructor("", _untagged)


def load_mkdocs(text: str) -> Dict[str, Any]:
    return yaml.load(text, Loader=_AnyTagLoader)


def nav_pages(config: Mapping[str, Any]) -> Tuple[Set[str], List[str]]:
    """The set of Markdown pages the nav lists, and the problems found walking it.

    A leaf that is an http(s) URL is a link, not a page. Any other leaf that is
    not a ``.md`` path is refused rather than ignored.
    """
    pages: Set[str] = set()
    problems: List[str] = []

    def walk(node: Any, where: str) -> None:
        if isinstance(node, str):
            if node.startswith(("http://", "https://")):
                return
            if node.endswith(".md"):
                pages.add(posixpath.normpath(node))
            else:
                problems.append(f"nav entry {where!r} is not a .md page: {node!r}")
        elif isinstance(node, list):
            for item in node:
                walk(item, where)
        elif isinstance(node, dict):
            for title, value in node.items():
                walk(value, str(title))
        else:
            problems.append(f"nav entry {where!r} is not a page or a section: {node!r}")

    nav = config.get("nav")
    if not nav:
        problems.append("mkdocs.yml has no nav")
    else:
        walk(nav, "nav")
    return pages, problems


def parse_inventory(text: str) -> Tuple[Dict[str, Any], List[str]]:
    """The inventory, or an empty one and the parse error (a duplicate key is one)."""
    try:
        return tomllib.loads(text), []
    except tomllib.TOMLDecodeError as error:
        return {}, [
            f"inventory.toml does not parse (a duplicate key does not): {error}"
        ]


def enrolled_exec_counts(text: str) -> Dict[str, int]:
    """Each page doc_examples.toml enrols, relative to docs/, with its exec count."""
    counts: Dict[str, int] = {}
    for document in tomllib.loads(text).get("document", []):
        path = document["path"]
        if path.startswith("docs/"):
            counts[path[len("docs/") :]] = int(document.get("exec", 0))
    return counts


def workflow_paths(text: str) -> Set[str]:
    """Every literal entry of the workflow's ``on.<event>.paths`` lists.

    Read from the parsed YAML, so a comment, a step name or a script line that
    names a page is not an entry. A YAML 1.1 loader reads the bare key ``on``
    as the boolean ``True``; both spellings are looked up. ``paths-ignore`` is
    not ``paths``.
    """
    config = yaml.safe_load(text)
    if not isinstance(config, dict):
        return set()
    triggers = config["on"] if "on" in config else config.get(True)
    if not isinstance(triggers, dict):
        return set()
    entries: Set[str] = set()
    for event in triggers.values():
        if isinstance(event, dict) and isinstance(event.get("paths"), list):
            entries.update(p for p in event["paths"] if isinstance(p, str))
    return entries


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
def _one_line(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and "\n" not in value


def _class_problems(key: str, entry: Mapping[str, Any]) -> Tuple[str, List[str]]:
    """The entry's class family (``external`` for every service) and its problems."""
    cls = entry.get("class")
    if not isinstance(cls, str):
        return "", [f"{key}: no class"]
    match = EXTERNAL.fullmatch(cls)
    if match:
        service = match.group("service")
        if service == "":
            return "external", [f"{key}: class external: names no service"]
        if not SLUG.fullmatch(service):
            return "external", [
                f"{key}: external service {service!r} is not a lower-case slug"
            ]
        return "external", []
    if cls not in CLASSES:
        return "", [f"{key}: unknown class {cls!r}"]
    return cls, []


def problems(
    inventory: Mapping[str, Any],
    nav: Set[str],
    *,
    enrolled: Mapping[str, int],
    workflows: Mapping[str, Set[str]],
    written: Set[str],
) -> List[str]:
    """Every way the inventory breaks its contract; empty when it holds.

    ``enrolled`` is doc_examples.toml's exec count per page, ``workflows``
    each workflow file's stem with its literal ``on.<event>.paths`` entries
    (``workflow_paths``), ``written`` the journey ids with an expectations
    file.
    """
    found: List[str] = []
    unknown_top = set(inventory) - {"pages", "flow"}
    if unknown_top:
        found.append(f"unknown top-level keys: {sorted(unknown_top)}")

    pages = inventory.get("pages", {})
    if not isinstance(pages, dict):
        return found + ["[pages] is not a table"]

    for page in sorted(nav - set(pages)):
        found.append(f"unclassified nav page: {page}")
    for page in sorted(set(pages) - nav):
        found.append(f"classified page not in the nav: {page}")

    classes_seen: Set[str] = set()
    journey_pages: Dict[str, str] = {}
    for key in sorted(pages):
        entry = pages[key]
        if not isinstance(entry, dict):
            found.append(f"{key}: not a table")
            continue
        family, class_problems = _class_problems(key, entry)
        found.extend(class_problems)
        if family:
            classes_seen.add(entry["class"])
            classes_seen.add(family)
        allowed = FIELDS.get(family, PLAIN_FIELDS)
        extra = set(entry) - allowed
        if extra:
            found.append(
                f"{key}: fields not allowed on class {family!r}: {sorted(extra)}"
            )
        if not _one_line(entry.get("reason")):
            found.append(f"{key}: reason must be one non-empty line")

        if family == "journey":
            journey = entry.get("journey")
            if not isinstance(journey, str) or journey == "":
                found.append(f"{key}: journey without an id")
                continue
            if not SLUG.fullmatch(journey):
                found.append(f"{key}: journey id {journey!r} is not a lower-case slug")
            if journey in journey_pages:
                found.append(
                    f"{key}: journey id {journey!r} is also {journey_pages[journey]}'s"
                    " (one expectations file per page)"
                )
            journey_pages[journey] = key
            if "pending" in entry and entry["pending"] is not True:
                found.append(f"{key}: pending must be true, or absent")
            elif entry.get("pending") is True and journey in written:
                found.append(
                    f"{key}: journey {journey!r} has its expectations file;"
                    " remove pending = true"
                )
            elif "pending" not in entry and journey not in written:
                found.append(
                    f"{key}: journey {journey!r} has no expectations file"
                    f" journeys/{journey}.yaml and is not pending = true"
                )
            if entry.get("pending") is True and entry.get("planned") not in PLANNED:
                found.append(
                    f"{key}: a pending journey names the pull request that writes it:"
                    f" planned = one of {', '.join(PLANNED)}"
                )
            elif entry.get("pending") is not True and "planned" in entry:
                found.append(f"{key}: planned is only for a pending journey")
        elif family == "exec":
            if enrolled.get(key, 0) < 1:
                found.append(
                    f"{key}: class exec, but scripts/doc_examples.toml enrols no exec"
                    " block of it"
                )
        elif family == "workflow":
            workflow = entry.get("workflow")
            if not isinstance(workflow, str) or workflow not in workflows:
                found.append(
                    f"{key}: workflow {workflow!r} is not a file in .github/workflows/"
                )
            elif f"docs/{key}" not in workflows[workflow]:
                found.append(
                    f"{key}: workflow {workflow!r} does not run this page:"
                    f" 'docs/{key}' is not a literal on.<event>.paths entry of"
                    f" .github/workflows/{workflow}.yml"
                )
        elif family == "aws":
            found.extend(_exercised_by_problems(key, entry))

    found.extend(
        _flow_problems(
            inventory.get("flow", []), set(pages), set(journey_pages), classes_seen
        )
    )
    return found


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _exercised_by_problems(key: str, entry: Mapping[str, Any]) -> List[str]:
    """An aws page's ``exercised_by``: values of ``EXERCISED_BY``, none twice."""
    if "exercised_by" not in entry:
        return [
            f"{key}: class aws needs exercised_by, the steps that exercise the"
            f' page (["{NONE}"] when no step does)'
        ]
    steps = entry["exercised_by"]
    if not _strings(steps) or not steps:
        return [f"{key}: exercised_by must be a non-empty list of strings"]
    found = [
        f"{key}: exercised_by {step!r} is not a step of #295 word for word,"
        " '605', 'production-deploy' or 'none'"
        for step in steps
        if step not in EXERCISED_BY
    ]
    for step in sorted({s for s in steps if steps.count(s) > 1}):
        found.append(f"{key}: exercised_by names {step!r} twice")
    if NONE in steps and len(steps) > 1:
        found.append(f"{key}: exercised_by {NONE!r} stands alone")
    return found


def _flow_problems(
    flows: Any, pages: Set[str], journeys: Set[str], classes: Set[str]
) -> List[str]:
    if not isinstance(flows, list):
        return ["[[flow]] is not an array of tables"]
    found: List[str] = []
    texts: List[str] = []
    for index, flow in enumerate(flows):
        if not isinstance(flow, dict):
            found.append(f"flow {index}: not a table")
            continue
        text = flow.get("text")
        label = repr(text) if isinstance(text, str) else f"flow {index}"
        if not isinstance(text, str):
            found.append(f"{label}: no text")
        else:
            texts.append(text)
        extra = set(flow) - FLOW_FIELDS
        if extra:
            found.append(f"{label}: fields not allowed: {sorted(extra)}")
        if not _one_line(flow.get("note")):
            found.append(f"{label}: note must be one non-empty line")
        lists = {name: flow.get(name, []) for name in ("journeys", "pages", "classes")}
        for name, value in lists.items():
            if not _strings(value):
                found.append(f"{label}: {name} must be a list of strings")
                lists[name] = []
        if not any(lists.values()):
            found.append(f"{label}: maps to no journey, page or class")
        for journey in lists["journeys"]:
            if journey not in journeys:
                found.append(f"{label}: journey {journey!r} is no page's journey")
        for page in lists["pages"]:
            if page not in pages:
                found.append(f"{label}: page {page!r} is not in [pages]")
        for cls in lists["classes"]:
            if cls not in classes:
                found.append(f"{label}: no page has class {cls!r}")

    for text in sorted({t for t in texts if texts.count(t) > 1}):
        found.append(f"flow mapped twice: {text!r}")
    for text in FLOWS_939:
        if text not in texts:
            found.append(f"#939 flow not mapped: {text!r}")
    for text in texts:
        if text not in FLOWS_939:
            found.append(f"flow not in #939's list: {text!r}")
    return found


# ---------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------
def _real_nav() -> Tuple[Set[str], List[str]]:
    return nav_pages(load_mkdocs(MKDOCS.read_text(encoding="utf-8")))


def _real_context() -> Dict[str, Any]:
    return {
        "enrolled": enrolled_exec_counts(DOC_EXAMPLES.read_text(encoding="utf-8")),
        "workflows": {
            p.stem: workflow_paths(p.read_text(encoding="utf-8"))
            for p in WORKFLOWS.glob("*.yml")
        },
        "written": {p.stem for p in JOURNEYS.glob("*.yaml")},
    }


def test_every_nav_page_is_classified_and_every_flow_mapped():
    nav, found = _real_nav()
    inventory, parse_found = parse_inventory(INVENTORY.read_text(encoding="utf-8"))
    found += parse_found or problems(inventory, nav, **_real_context())
    assert not found, "\n".join(found) + "\n\n" + HOW_TO_FIX


#: The workflow page of the real tree, and two workflows that exist but do not
#: run it: `docs` lists `docs/**` in its paths (a glob, not the page), and
#: `leak-guard` has no paths at all. Either one passed before #1075.
WORKFLOW_PAGE = "self-hosting/kubernetes.md"


@pytest.mark.regression
@pytest.mark.parametrize("workflow", ["docs", "leak-guard"])
def test_a_workflow_page_naming_a_workflow_that_does_not_list_it_is_refused(
    workflow,
):
    nav, _found = _real_nav()
    inventory, _parse = parse_inventory(INVENTORY.read_text(encoding="utf-8"))
    context = _real_context()
    entry = inventory["pages"][WORKFLOW_PAGE]
    assert (entry["class"], entry["workflow"]) == ("workflow", "chart-kind")
    assert f"docs/{WORKFLOW_PAGE}" in context["workflows"]["chart-kind"]
    assert workflow in context["workflows"]

    entry["workflow"] = workflow
    found = problems(inventory, nav, **context)
    assert found == [
        f"{WORKFLOW_PAGE}: workflow {workflow!r} does not run this page:"
        f" 'docs/{WORKFLOW_PAGE}' is not a literal on.<event>.paths entry of"
        f" .github/workflows/{workflow}.yml"
    ]


def test_workflow_paths_reads_only_the_literal_on_paths_entries():
    text = (
        "# docs/a.md is run below, by name (a comment, not an entry)\n"
        "name: A\n"
        "on:\n"
        "  pull_request:\n"
        "    paths:\n"
        "      - 'docs/a.md'\n"
        "      - 'docs/**'\n"
        "  push:\n"
        "    branches: [main]\n"
        "    paths-ignore: ['docs/b.md']\n"
        "  schedule:\n"
        "    - cron: '0 0 * * *'\n"
        "jobs:\n"
        "  run:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: docs/c.md\n"
        "        run: scripts/x.sh docs/c.md\n"
    )
    assert workflow_paths(text) == {"docs/a.md", "docs/**"}
    assert workflow_paths("on: [push, pull_request]\n") == set()
    assert workflow_paths("on: push\n") == set()
    assert workflow_paths("'on':\n  push:\n    paths: [docs/a.md]\n") == {"docs/a.md"}


def test_the_nav_parsed_to_real_pages():
    """A nav that came back empty would leave nothing for the check above."""
    nav, _found = _real_nav()
    assert len(nav) > 100, f"the nav parsed to {len(nav)} pages"
    assert "getting-started/quick-start.md" in nav


# ---------------------------------------------------------------------------
# Planted defects: each refusal fires
# ---------------------------------------------------------------------------
GOOD = """
[pages."a.md"]
class = "journey"
journey = "a-journey"
pending = true
planned = "D3a"
reason = "walked"

[pages."b.md"]
class = "exec"
reason = "run by doc examples"

[pages."c.md"]
class = "workflow"
workflow = "chart-kind"
reason = "run by a workflow"

[pages."d.md"]
class = "external:salesforce"
reason = "needs a third party"

[pages."e.md"]
class = "reference"
reason = "nothing to walk"

[pages."f.md"]
class = "aws"
exercised_by = ["none"]
reason = "needs AWS"

[pages."j.md"]
class = "aws"
exercised_by = ["run the first stack deploy", "605", "production-deploy"]
reason = "needs AWS"

[pages."g.md"]
class = "device"
reason = "needs a simulator"
"""

NAV = {"a.md", "b.md", "c.md", "d.md", "e.md", "f.md", "g.md", "j.md"}
CONTEXT: Dict[str, Any] = {
    "enrolled": {"b.md": 3},
    "workflows": {"chart-kind": {"docs/c.md", "charts/**"}},
    "written": set(),
}
#: j.md's mapping, which the exercised_by plants edit.
J_STEPS = 'exercised_by = ["run the first stack deploy", "605", "production-deploy"]'


def _flows(skip: Iterable[str] = ()) -> str:
    blocks = [
        f'[[flow]]\ntext = "{text}"\njourneys = ["a-journey"]\nnote = "mapped"\n'
        for text in FLOWS_939
        if text not in skip
    ]
    return "\n" + "\n".join(blocks)


def _check(text: str, nav: Set[str] = NAV, **context: Any) -> List[str]:
    inventory, found = parse_inventory(text)
    if found:
        return found
    return problems(inventory, nav, **{**CONTEXT, **context})


#: The mapping line every flow of the fixture carries; the plants edit the first.
MAPPED = 'journeys = ["a-journey"]'


def test_the_good_fixture_passes():
    assert _check(GOOD + _flows()) == []


PLANTS = [
    pytest.param(
        GOOD + _flows(),
        NAV | {"new.md"},
        {},
        "unclassified nav page: new.md",
        id="unclassified-nav-page",
    ),
    pytest.param(
        GOOD + '\n[pages."gone.md"]\nclass = "reference"\nreason = "x"\n' + _flows(),
        NAV,
        {},
        "classified page not in the nav: gone.md",
        id="classified-page-not-in-nav",
    ),
    pytest.param(
        GOOD + '\n[pages."e.md"]\nclass = "reference"\nreason = "again"\n' + _flows(),
        NAV,
        {},
        "does not parse",
        id="duplicate-key",
    ),
    pytest.param(
        GOOD.replace('class = "aws"', 'class = "manual"') + _flows(),
        NAV,
        {},
        "f.md: unknown class 'manual'",
        id="unknown-class",
    ),
    pytest.param(
        GOOD.replace('"external:salesforce"', '"external:"') + _flows(),
        NAV,
        {},
        "d.md: class external: names no service",
        id="external-without-service",
    ),
    pytest.param(
        GOOD.replace('"external:salesforce"', '"external"') + _flows(),
        NAV,
        {},
        "d.md: unknown class 'external'",
        id="external-without-colon",
    ),
    pytest.param(
        GOOD.replace('"external:salesforce"', '"external:Sales Force"') + _flows(),
        NAV,
        {},
        "is not a lower-case slug",
        id="external-service-not-a-slug",
    ),
    pytest.param(
        GOOD.replace('journey = "a-journey"\n', "") + _flows(),
        NAV,
        {},
        "a.md: journey without an id",
        id="journey-without-id",
    ),
    pytest.param(
        GOOD.replace('pending = true\nplanned = "D3a"\n', "") + _flows(),
        NAV,
        {},
        "has no expectations file",
        id="journey-neither-written-nor-pending",
    ),
    pytest.param(
        GOOD + _flows(),
        NAV,
        {"written": {"a-journey"}},
        "remove pending = true",
        id="pending-after-the-file-exists",
    ),
    pytest.param(
        GOOD.replace('planned = "D3a"\n', "") + _flows(),
        NAV,
        {},
        "a.md: a pending journey names the pull request that writes it",
        id="pending-without-planned",
    ),
    pytest.param(
        GOOD.replace('planned = "D3a"', 'planned = "D9"') + _flows(),
        NAV,
        {},
        "a.md: a pending journey names the pull request that writes it",
        id="planned-unknown",
    ),
    pytest.param(
        GOOD.replace("pending = true\n", "") + _flows(),
        NAV,
        {"written": {"a-journey"}},
        "a.md: planned is only for a pending journey",
        id="planned-on-a-written-journey",
    ),
    pytest.param(
        GOOD.replace("pending = true", "pending = false") + _flows(),
        NAV,
        {},
        "pending must be true",
        id="pending-false",
    ),
    pytest.param(
        GOOD.replace(
            'class = "reference"\nreason = "nothing to walk"',
            'class = "journey"\njourney = "a-journey"\n'
            'pending = true\nplanned = "D3b"\nreason = "nothing to walk"',
        )
        + _flows(),
        NAV,
        {},
        "is also a.md's",
        id="journey-id-shared",
    ),
    pytest.param(
        GOOD + _flows(),
        NAV,
        {"enrolled": {}},
        "b.md: class exec, but",
        id="exec-not-enrolled",
    ),
    pytest.param(
        GOOD + _flows(),
        NAV,
        {"workflows": {}},
        "c.md: workflow 'chart-kind' is not a file",
        id="workflow-missing",
    ),
    pytest.param(
        GOOD + _flows(),
        NAV,
        {"workflows": {"chart-kind": set()}},
        "c.md: workflow 'chart-kind' does not run this page",
        id="workflow-without-paths",
    ),
    pytest.param(
        GOOD + _flows(),
        NAV,
        {"workflows": {"chart-kind": {"docs/**", "docs/*.md", "c.md"}}},
        "c.md: workflow 'chart-kind' does not run this page",
        id="workflow-paths-glob-only",
    ),
    pytest.param(
        GOOD.replace('exercised_by = ["none"]\n', "") + _flows(),
        NAV,
        {},
        "f.md: class aws needs exercised_by",
        id="aws-without-exercised-by",
    ),
    pytest.param(
        GOOD.replace('exercised_by = ["none"]', "exercised_by = []") + _flows(),
        NAV,
        {},
        "f.md: exercised_by must be a non-empty list of strings",
        id="aws-exercised-by-empty",
    ),
    pytest.param(
        GOOD.replace('exercised_by = ["none"]', 'exercised_by = "none"') + _flows(),
        NAV,
        {},
        "f.md: exercised_by must be a non-empty list of strings",
        id="aws-exercised-by-not-a-list",
    ),
    pytest.param(
        GOOD.replace(J_STEPS, 'exercised_by = ["bootstrap the account;"]') + _flows(),
        NAV,
        {},
        "j.md: exercised_by 'bootstrap the account;' is not a step of #295",
        id="aws-step-not-verbatim",
    ),
    pytest.param(
        GOOD.replace(J_STEPS, 'exercised_by = ["Run the first stack deploy"]')
        + _flows(),
        NAV,
        {},
        "j.md: exercised_by 'Run the first stack deploy' is not a step of #295",
        id="aws-step-case-differs",
    ),
    pytest.param(
        GOOD.replace(J_STEPS, 'exercised_by = ["a step of our own"]') + _flows(),
        NAV,
        {},
        "j.md: exercised_by 'a step of our own' is not a step of #295",
        id="aws-step-invented",
    ),
    pytest.param(
        GOOD.replace(J_STEPS, 'exercised_by = ["605", "605"]') + _flows(),
        NAV,
        {},
        "j.md: exercised_by names '605' twice",
        id="aws-step-twice",
    ),
    pytest.param(
        GOOD.replace(J_STEPS, 'exercised_by = ["605", "none"]') + _flows(),
        NAV,
        {},
        "j.md: exercised_by 'none' stands alone",
        id="aws-none-with-a-step",
    ),
    pytest.param(
        GOOD.replace(
            'class = "reference"', 'class = "reference"\nexercised_by = ["none"]'
        )
        + _flows(),
        NAV,
        {},
        "e.md: fields not allowed on class 'reference': ['exercised_by']",
        id="exercised-by-off-aws",
    ),
    pytest.param(
        GOOD.replace('reason = "needs AWS"', 'reason = ""') + _flows(),
        NAV,
        {},
        "f.md: reason must be one non-empty line",
        id="empty-reason",
    ),
    pytest.param(
        GOOD.replace('reason = "needs AWS"', 'reason = """two\nlines"""') + _flows(),
        NAV,
        {},
        "f.md: reason must be one non-empty line",
        id="two-line-reason",
    ),
    pytest.param(
        GOOD.replace('class = "aws"', 'class = "aws"\nworkflow = "chart-kind"')
        + _flows(),
        NAV,
        {},
        "f.md: fields not allowed",
        id="field-not-allowed",
    ),
    pytest.param(
        GOOD + _flows(skip=[FLOWS_939[6]]),
        NAV,
        {},
        "#939 flow not mapped: 'the SDK quick starts'",
        id="flow-unmapped",
    ),
    pytest.param(
        GOOD + _flows() + '\n[[flow]]\ntext = "a flow of our own"\n'
        'journeys = ["a-journey"]\nnote = "x"\n',
        NAV,
        {},
        "flow not in #939's list",
        id="flow-invented",
    ),
    pytest.param(
        GOOD + _flows().replace('journeys = ["a-journey"]', "journeys = []", 1),
        NAV,
        {},
        "maps to no journey, page or class",
        id="flow-maps-to-nothing",
    ),
    pytest.param(
        GOOD + _flows().replace('"a-journey"', '"no-such-journey"', 1),
        NAV,
        {},
        "journey 'no-such-journey' is no page's journey",
        id="flow-names-undeclared-journey",
    ),
    pytest.param(
        GOOD + _flows().replace(MAPPED, MAPPED + '\npages = ["nowhere.md"]', 1),
        NAV,
        {},
        "page 'nowhere.md' is not in [pages]",
        id="flow-names-unknown-page",
    ),
    pytest.param(
        GOOD + _flows().replace(MAPPED, MAPPED + '\nclasses = ["external:github"]', 1),
        NAV,
        {},
        "no page has class 'external:github'",
        id="flow-names-class-no-page-has",
    ),
    pytest.param(
        GOOD + _flows() + _flows(skip=FLOWS_939[1:]),
        NAV,
        {},
        "flow mapped twice",
        id="flow-mapped-twice",
    ),
    pytest.param(
        GOOD + _flows() + "\n[extra]\nkey = 1\n",
        NAV,
        {},
        "unknown top-level keys: ['extra']",
        id="unknown-top-level-key",
    ),
    pytest.param(
        GOOD.replace('journey = "a-journey"', 'journey = "A Journey"') + _flows(),
        NAV,
        {},
        "journey id 'A Journey' is not a lower-case slug",
        id="journey-id-not-a-slug",
    ),
    pytest.param(
        GOOD + _flows().replace('note = "mapped"', 'note = ""', 1),
        NAV,
        {},
        "note must be one non-empty line",
        id="flow-note-empty",
    ),
    pytest.param(
        GOOD + _flows().replace('note = "mapped"', 'note = "mapped"\nowner = "x"', 1),
        NAV,
        {},
        "fields not allowed: ['owner']",
        id="flow-field-not-allowed",
    ),
    pytest.param(
        GOOD.replace('class = "device"\n', "") + _flows(),
        NAV,
        {},
        "g.md: no class",
        id="entry-without-class",
    ),
    pytest.param(
        "pages = 3\n" + _flows(),
        NAV,
        {},
        "[pages] is not a table",
        id="pages-not-a-table",
    ),
    pytest.param(
        '[pages]\n"h.md" = "reference"\n' + GOOD + _flows(),
        NAV | {"h.md"},
        {},
        "h.md: not a table",
        id="entry-not-a-table",
    ),
    pytest.param(
        "flow = 3\n" + GOOD,
        NAV,
        {},
        "[[flow]] is not an array of tables",
        id="flows-not-an-array",
    ),
    pytest.param(
        "flow = [1]\n" + GOOD,
        NAV,
        {},
        "flow 0: not a table",
        id="flow-not-a-table",
    ),
    pytest.param(
        GOOD + _flows().replace(f'text = "{FLOWS_939[0]}"\n', "", 1),
        NAV,
        {},
        "flow 0: no text",
        id="flow-without-text",
    ),
    pytest.param(
        GOOD + _flows().replace(MAPPED, 'journeys = "a-journey"', 1),
        NAV,
        {},
        "journeys must be a list of strings",
        id="flow-list-not-strings",
    ),
]


@pytest.mark.parametrize("text, nav, context, expected", PLANTS)
def test_planted_defect_is_refused(text, nav, context, expected):
    found = _check(text, nav, **context)
    assert any(expected in line for line in found), found


# ---------------------------------------------------------------------------
# Reading mkdocs.yml
# ---------------------------------------------------------------------------
def test_the_loader_accepts_mkdocs_tags():
    config = load_mkdocs(
        "site_name: !ENV [SITE_NAME, x]\n"
        "markdown_extensions:\n"
        "  - pymdownx.emoji:\n"
        "      emoji_index: !!python/name:material.extensions.emoji.twemoji\n"
        "nav:\n"
        "  - Home: index.md\n"
    )
    assert config["site_name"] == ["SITE_NAME", "x"]
    assert nav_pages(config) == ({"index.md"}, [])


def test_the_nav_walk_reads_every_shape_and_refuses_the_unknown():
    config = load_mkdocs(
        "nav:\n"
        "  - index.md\n"
        "  - Section:\n"
        "    - Page: a/b.md\n"
        "    - Deeper:\n"
        "      - c.md\n"
        "    - Twice: a/b.md\n"
        "  - Link: https://example.com/\n"
        "  - Odd: notes.txt\n"
        "  - Number: 3\n"
    )
    pages, found = nav_pages(config)
    assert pages == {"index.md", "a/b.md", "c.md"}
    assert found == [
        "nav entry 'Odd' is not a .md page: 'notes.txt'",
        "nav entry 'Number' is not a page or a section: 3",
    ]
    assert nav_pages({}) == (set(), ["mkdocs.yml has no nav"])

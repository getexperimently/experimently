"""The documentation site as its source describes it, for ``crawl`` and ``search``.

What a crawl expects comes from the site's source, the ``mkdocs.yml`` and
``docs/`` it was built from (the stack names that directory: ``stacks.py``):

* the nav pages, in nav order, each once (a page the nav lists twice is one);
* the URL MkDocs gives each (``use_directory_urls``, MkDocs' default:
  ``a/b.md`` is ``a/b/``, and ``a/README.md`` or ``a/index.md`` is ``a/``);
* each page's first ``# `` heading as the reader sees it rendered
  (``guide.parse``: its inline Markdown removed), or "" when it has none;
* the site's ``site_url``, and every absolute link to it written in the nav
  pages' Markdown, which MkDocs' strict build does not check (it checks only
  relative links).

And what a crawl or a search does with what it sees, without a browser: which
links are the site's, how a link is resolved (redirects are followed only
within the site), and where a page is in the search results.

A page or a link that answers 5xx, or nothing, is asked once more,
``RETRY_SECONDS`` later, and the second answer is the one judged: GitHub Pages
answers 503 now and then (one of 121 pages in one run, measured on
2026-10-06), and one such answer would make a whole night red for nothing. A
second 5xx is a finding, and a 4xx is never asked again. The crawl's file says
which were asked twice. ``execute`` drives
the browser; this module imports neither Playwright nor ``backend``, so the
unit job tests it.
"""

from __future__ import annotations

import posixpath
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

import yaml

from docs_runner import guide as guides

#: Redirects followed for one link, at most.
MAX_REDIRECTS = 5
#: How long before a page or link that answered 5xx or nothing is asked again.
RETRY_SECONDS = 2.0
REDIRECTS = (301, 302, 303, 307, 308)
#: An absolute link in Markdown text ends at whitespace or at what closes it.
_LINK_END = r"[^\s<>\"'`)\]]*"
_TRAILING = ".,;:!?"


class SiteError(ValueError):
    """The source cannot say what the site should be."""


class _AnyTagLoader(yaml.SafeLoader):
    """A safe loader that builds a node with an unknown tag as plain YAML."""


def _untagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_AnyTagLoader.add_multi_constructor("", _untagged)


@dataclass(frozen=True)
class Source:
    """The directory a site was built from: its ``mkdocs.yml`` and docs."""

    root: Path

    @property
    def config(self) -> Dict[str, Any]:
        path = self.root / "mkdocs.yml"
        try:
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=_AnyTagLoader)
        except (OSError, yaml.YAMLError) as error:
            raise SiteError(f"cannot read {path.name} of the source: {error}") from None
        if not isinstance(data, dict):
            raise SiteError("the source's mkdocs.yml is not a mapping")
        return data

    @property
    def docs_root(self) -> Path:
        return self.root / str(self.config.get("docs_dir", "docs"))


@dataclass(frozen=True)
class NavPage:
    """A nav page as the source says the site must show it."""

    path: str  # relative to docs/, as the nav writes it
    url: str  # relative to the site's base: "" for the home page, else "a/b/"
    heading: str  # the source's first "# " heading, rendered; "" when none


def nav_paths(config: Dict[str, Any]) -> List[str]:
    """The Markdown pages of the nav, in nav order, each once."""
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            if node.endswith(".md") and not node.startswith(("http://", "https://")):
                page = posixpath.normpath(node)
                if page not in found:
                    found.append(page)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(config.get("nav") or [])
    if not found:
        raise SiteError("the source's mkdocs.yml has no nav pages")
    return found


def page_url(path: str) -> str:
    """The URL MkDocs gives a page, relative to the site's base."""
    stem = path[: -len(".md")]
    directory, name = posixpath.split(stem)
    if name in ("index", "README"):
        return f"{directory}/" if directory else ""
    return f"{stem}/"


def first_heading(docs_root: Path, path: str) -> str:
    """The page's first ``# `` heading as rendered, or "" when it has none."""
    parsed = guides.load(docs_root, path)
    return next((h.text for h in parsed.headings if h.level == 1), "")


def nav_pages(source: Source) -> List[NavPage]:
    docs_root = source.docs_root
    pages = []
    for path in nav_paths(source.config):
        heading = first_heading(docs_root, path) if (docs_root / path).is_file() else ""
        pages.append(NavPage(path, page_url(path), heading))
    return pages


def site_url(source: Source) -> str:
    """The source's ``site_url``, ending in ``/``, or "" when it gives none."""
    value = str(source.config.get("site_url") or "")
    if value and not value.endswith("/"):
        value += "/"
    return value


def absolute_links(source: Source, paths: Sequence[str]) -> List[Tuple[str, str]]:
    """(page, link) for each absolute link to the site in the pages' Markdown.

    The link is as written, its fragment and any closing punctuation removed;
    each (page, link) once, in page order.
    """
    base = site_url(source)
    if not base:
        return []
    pattern = re.compile(re.escape(base) + _LINK_END)
    found: List[Tuple[str, str]] = []
    for path in paths:
        file = source.docs_root / path
        if not file.is_file():
            continue
        for match in pattern.finditer(file.read_text(encoding="utf-8")):
            link = urldefrag(match.group(0).rstrip(_TRAILING))[0]
            if (path, link) not in found:
                found.append((path, link))
    return found


# ---------------------------------------------------------------------------
# What the crawl sees
# ---------------------------------------------------------------------------
def normalise(text: str) -> str:
    return " ".join(text.split())


def within(url: str, base: str) -> bool:
    """True when *url* is a page of the site at *base* (same scheme, host, path)."""
    return url.startswith(base) or url == base.rstrip("/")


def strip(url: str) -> str:
    """*url* without its fragment and query (a search adds ``?h=``)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def on_site(base: str, url: str) -> str:
    """*url*, a page of the site, relative to its base ("" for the home page)."""
    return url[len(base) :] if url.startswith(base) else url


def to_stack(link: str, written_base: str, stack_base: str) -> str:
    """An absolute link to the site as written, on the stack being crawled."""
    return stack_base + link[len(written_base) :]


def site_links(hrefs: Sequence[str], base: str) -> List[str]:
    """The distinct links to the site among *hrefs*, fragments removed."""
    found: List[str] = []
    for href in hrefs:
        if not href.startswith(("http://", "https://")):
            continue
        link = urldefrag(href)[0]
        if within(link, base) and link not in found:
            found.append(link)
    return found


#: ``fetch(url) -> (status, Location header or "")``, never following redirects.
Fetch = Callable[[str], Tuple[int, str]]


@dataclass(frozen=True)
class Resolved:
    link: str
    status: Optional[int]  # the last answer's status; None when none came
    final: str  # the last URL asked for
    problem: str  # "" when the link resolves
    retried: bool = (
        False  # a URL on the way answered 5xx or nothing, and was asked again
    )


def transient(status: Optional[int]) -> bool:
    """True for an answer worth asking again: a 5xx, or none at all."""
    return status is None or status >= 500


def resolve(
    link: str, base: str, fetch: Fetch, pause: Callable[[float], None] = time.sleep
) -> Resolved:
    """Follow *link*'s redirects within the site to a 2xx, or say why not.

    Each URL that answers 5xx or nothing is asked once more after
    ``RETRY_SECONDS``; ``retried`` says it was.
    """
    url = link
    retried = False
    for _ in range(MAX_REDIRECTS + 1):
        for attempt in (1, 2):
            try:
                status, location = fetch(url)
                error = ""
            # Any failure to answer is a finding about the link, not a crash.
            except Exception as failure:
                status, location, error = None, "", type(failure).__name__
            if attempt == 1 and transient(status):
                retried = True
                pause(RETRY_SECONDS)
                continue
            break
        if status is None:
            return Resolved(link, None, url, f"no answer ({error})", retried)
        if status in REDIRECTS:
            if not location:
                return Resolved(
                    link, status, url, f"{status} with no Location", retried
                )
            target = urljoin(url, location)
            if not within(target, base):
                return Resolved(
                    link,
                    status,
                    url,
                    f"{status} to {target}, outside the site",
                    retried,
                )
            url = target
            continue
        if 200 <= status < 300:
            return Resolved(link, status, url, "", retried)
        return Resolved(link, status, url, f"answered {status}", retried)
    return Resolved(link, None, url, f"more than {MAX_REDIRECTS} redirects", retried)


def compare_headings(
    pages: Sequence[NavPage], seen: Dict[str, Dict[str, Any]]
) -> List[str]:
    """One line per nav page the site does not show as its source says.

    *seen* maps a page's path to what the browser saw there: ``status`` (the
    answer, after redirects; None when none came), ``url`` (where the browser
    ended) and ``heading`` (the first first-level heading of the main content,
    or None when there is none).
    """
    problems: List[str] = []
    for page in pages:
        visit = seen.get(page.path)
        where = f"{page.path} (/{page.url})"
        if visit is None:
            problems.append(f"{where}: not visited")
            continue
        status = visit.get("status")
        if status is None or not 200 <= status < 300:
            problems.append(
                f"{where}: answered {status if status is not None else 'nothing'}"
            )
            continue
        if not visit.get("on_site", True):
            problems.append(f"{where}: left the site, to {visit.get('url')}")
            continue
        if not page.heading:
            problems.append(f"{where}: the source page has no # heading")
            continue
        heading = visit.get("heading")
        if heading is None:
            problems.append(f"{where}: no first-level heading on the page")
        elif normalise(heading) != normalise(page.heading):
            problems.append(
                f"{where}: the page's heading is {normalise(heading)!r}, the source's"
                f" first heading is {page.heading!r}"
            )
    return problems


def rank(results: Sequence[str], base: str, wanted: str) -> Optional[int]:
    """The 1-based place of page *wanted* (``/a/b/``) among search *results*."""
    target = wanted.lstrip("/")
    for place, url in enumerate(results, 1):
        if on_site(base, strip(url)) == target:
            return place
    return None

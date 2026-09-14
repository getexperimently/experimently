/**
 * The documentation site.
 *
 * The docs are markdown under `docs/` at the repository root, built into a
 * static site by MkDocs (`mkdocs.yml`) and published to GitHub Pages on each
 * release. The dashboard used to render that markdown itself, from a slug map
 * with no test, inside the authenticated bundle, and needed `docs/` copied
 * into its image — every page read "coming soon" when it was not. Now the
 * dashboard links out: `/docs` is a hub of links into the site, and every
 * in-app "read the guide" link goes through `docsUrl()`.
 *
 * `NEXT_PUBLIC_DOCS_URL` overrides the site's origin for a deployment that
 * hosts its own copy (`mkdocs build` and serve `site/`). It is read at build
 * time, like every `NEXT_PUBLIC_*` variable.
 */

/** Where the published site lives when nothing overrides it (mkdocs.yml `site_url`). */
export const DEFAULT_DOCS_URL = 'https://getexperimently.github.io/experimently';

export const DOCS_URL = (process.env.NEXT_PUBLIC_DOCS_URL || DEFAULT_DOCS_URL).replace(/\/+$/, '');

/**
 * The URL of a page, given its path under `docs/` without the `.md`
 * (`'getting-started/quick-start'`). MkDocs builds each page as a directory
 * (`use_directory_urls`), and a `README` is its directory's index.
 */
export function docsUrl(page: string, anchor?: string): string {
  const path = page.replace(/^\/+|\/+$/g, '').replace(/(^|\/)README$/, '').replace(/\/+$/, '');
  const base = path ? `${DOCS_URL}/${path}/` : `${DOCS_URL}/`;
  return anchor ? `${base}#${anchor}` : base;
}

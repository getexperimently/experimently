/**
 * Where a "read the guide" link goes.
 *
 * The docs are markdown under `docs/` at the repository root. The dashboard
 * used to render that markdown itself, from a slug map with no test, inside
 * the authenticated bundle — every page read "coming soon" when it was not.
 * Now the dashboard links out, and `docsUrl()` is the single place that
 * decides where "out" is.
 *
 * DEFAULT: THE REPOSITORY, NOT THE MKDOCS SITE. `mkdocs.yml` declares
 * `site_url: https://getexperimently.github.io/experimently/`, and that site
 * does not exist. `.github/workflows/docs.yml` builds the docs on every pull
 * request but its `deploy` job is gated on
 *
 *     startsWith(github.ref, 'refs/tags/v') && github.repository == 'getexperimently/experimently'
 *
 * — a release tag, from the public repository. The public repository has no
 * tags and is not yet public, so the site has never been built once, and every
 * link that pointed at it answered 404. It was the homepage's primary button.
 *
 * So the default is a GitHub blob URL. GitHub renders markdown, so the links
 * work the moment the repository is public, with no Pages site, no release
 * tag and no dependency on the release pipeline. They are still 404 while the
 * repository is private — there is no destination that is not, and pretending
 * otherwise is what caused this.
 *
 * `NEXT_PUBLIC_DOCS_URL` overrides that with the origin of a *built* site, for
 * anyone self-hosting `mkdocs build` output, and then the URLs take MkDocs's
 * `use_directory_urls` shape instead. Set it to `MKDOCS_SITE_URL` once the
 * published site exists. Read at build time, like every `NEXT_PUBLIC_*`.
 *
 * `url-literals.test.ts` does this for `/api/v1/` paths; `docs-links.test.ts`
 * does it here — every `docsUrl('...')` literal in the dashboard must resolve
 * to a file that exists under `docs/`.
 */

/** The repository the markdown lives in, and the branch links point at. */
export const DOCS_REPO = 'https://github.com/getexperimently/experimently';
export const DOCS_BRANCH = 'main';

/** Where the MkDocs site will live once a release tag builds it (mkdocs.yml `site_url`). */
export const MKDOCS_SITE_URL = 'https://getexperimently.github.io/experimently';

/** A self-hosted built site, if one is configured. Empty means "use the repository". */
export const DOCS_SITE = (process.env.NEXT_PUBLIC_DOCS_URL || '').replace(/\/+$/, '');

/** The base every docs link is built on, whichever mode is in force. */
export const DOCS_URL = DOCS_SITE || `${DOCS_REPO}/tree/${DOCS_BRANCH}/docs`;

/**
 * The URL of a page, given its path under `docs/` without the `.md`
 * (`'getting-started/quick-start'`).
 *
 * A `README` addresses its directory in both modes: MkDocs publishes it as the
 * directory index, and GitHub renders it under the directory listing.
 */
export function docsUrl(page: string, anchor?: string): string {
  const path = page.replace(/^\/+|\/+$/g, '');
  const isIndex = path === '' || path === 'README' || path.endsWith('/README');
  const dir = path.replace(/(^|\/)README$/, '').replace(/\/+$/, '');

  let base: string;
  if (DOCS_SITE) {
    // A built MkDocs site: `use_directory_urls`, so every page is a directory.
    base = dir ? `${DOCS_SITE}/${dir}/` : `${DOCS_SITE}/`;
  } else if (isIndex) {
    // A directory on GitHub renders its README.
    base = `${DOCS_REPO}/tree/${DOCS_BRANCH}/docs${dir ? `/${dir}` : ''}`;
  } else {
    base = `${DOCS_REPO}/blob/${DOCS_BRANCH}/docs/${path}.md`;
  }

  return anchor ? `${base}#${anchor}` : base;
}

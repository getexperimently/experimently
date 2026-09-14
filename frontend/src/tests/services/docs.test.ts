/**
 * The documentation site is external now: every in-app "read the guide"
 * link resolves through `docsUrl()` to a page of the MkDocs site, never to
 * an in-app route. These pin the URL shape so the hub, the modules guide
 * links and the site's own `use_directory_urls` layout stay in step.
 */
import { DEFAULT_DOCS_URL, DOCS_URL, docsUrl } from '@/services/docs';

describe('docsUrl', () => {
  it('builds a directory URL for a page path, as MkDocs publishes it', () => {
    expect(docsUrl('getting-started/quick-start')).toBe(`${DOCS_URL}/getting-started/quick-start/`);
  });

  it('treats a README as its directory index', () => {
    expect(docsUrl('rbac/README')).toBe(`${DOCS_URL}/rbac/`);
    expect(docsUrl('README')).toBe(`${DOCS_URL}/`);
  });

  it('appends an anchor after the trailing slash', () => {
    expect(docsUrl('self-hosting/migrations', 'switching-profile')).toBe(
      `${DOCS_URL}/self-hosting/migrations/#switching-profile`,
    );
  });

  it('tolerates stray slashes on the page path', () => {
    expect(docsUrl('/sdk/javascript/')).toBe(`${DOCS_URL}/sdk/javascript/`);
  });

  it('defaults to the published site and never ends in a slash', () => {
    expect(DEFAULT_DOCS_URL).toBe('https://getexperimently.github.io/experimently');
    expect(DOCS_URL.endsWith('/')).toBe(false);
  });
});

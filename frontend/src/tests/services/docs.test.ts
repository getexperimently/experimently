/**
 * Every in-app "read the guide" link resolves through `docsUrl()`, never to an
 * in-app route. These pin the URL shape in both modes.
 *
 * The default mode is the repository, not the MkDocs site: that site has never
 * been built (docs.yml deploys only on a release tag from the public repo, and
 * there are no tags), so every link that pointed at it answered 404 — the
 * homepage's primary button among them. See the header of `services/docs.ts`.
 */
import {
  DOCS_BRANCH,
  DOCS_REPO,
  DOCS_URL,
  MKDOCS_SITE_URL,
  docsUrl,
} from '@/services/docs';

const BLOB = `${DOCS_REPO}/blob/${DOCS_BRANCH}/docs`;
const TREE = `${DOCS_REPO}/tree/${DOCS_BRANCH}/docs`;

describe('docsUrl (default: the repository)', () => {
  it('addresses a page as the markdown file GitHub renders', () => {
    expect(docsUrl('getting-started/quick-start')).toBe(`${BLOB}/getting-started/quick-start.md`);
  });

  it('addresses a README as its directory, which GitHub renders from the README', () => {
    expect(docsUrl('rbac/README')).toBe(`${TREE}/rbac`);
    expect(docsUrl('README')).toBe(TREE);
  });

  it('appends an anchor', () => {
    expect(docsUrl('self-hosting/migrations', 'switching-profile')).toBe(
      `${BLOB}/self-hosting/migrations.md#switching-profile`,
    );
  });

  it('tolerates stray slashes on the page path', () => {
    expect(docsUrl('/sdk/javascript/')).toBe(`${BLOB}/sdk/javascript.md`);
  });

  it('never points at the MkDocs site, which has never been built', () => {
    // The specific regression: the default used to be MKDOCS_SITE_URL and
    // every link 404'd. A `.md` suffix is not enough to assert — a link to
    // `<site>/x.md` would also carry one.
    expect(DOCS_URL.startsWith(DOCS_REPO)).toBe(true);
    expect(docsUrl('getting-started/quick-start')).not.toContain(MKDOCS_SITE_URL);
  });
});

/**
 * The self-hosted mode. `DOCS_SITE` is read from the environment at module
 * load, so this needs a fresh module registry rather than a reassignment.
 */
describe('docsUrl (NEXT_PUBLIC_DOCS_URL: a built MkDocs site)', () => {
  const load = (site: string) => {
    let mod: typeof import('@/services/docs');
    jest.isolateModules(() => {
      process.env.NEXT_PUBLIC_DOCS_URL = site;
      mod = require('@/services/docs');
    });
    return mod!;
  };

  afterEach(() => {
    delete process.env.NEXT_PUBLIC_DOCS_URL;
  });

  it('builds the directory URLs MkDocs publishes, and drops a trailing slash on the base', () => {
    const d = load('https://docs.example.com/');
    expect(d.DOCS_URL).toBe('https://docs.example.com');
    expect(d.docsUrl('getting-started/quick-start')).toBe(
      'https://docs.example.com/getting-started/quick-start/',
    );
    expect(d.docsUrl('rbac/README')).toBe('https://docs.example.com/rbac/');
    expect(d.docsUrl('README')).toBe('https://docs.example.com/');
    expect(d.docsUrl('self-hosting/migrations', 'switching-profile')).toBe(
      'https://docs.example.com/self-hosting/migrations/#switching-profile',
    );
  });
});

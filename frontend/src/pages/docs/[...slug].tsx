import fs from 'fs';
import path from 'path';
import Link from 'next/link';
import Head from 'next/head';
import { GetStaticPaths, GetStaticProps } from 'next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Map URL slug (joined with '/') → relative path from repo root docs/ folder
const SLUG_TO_FILE: Record<string, string | null> = {
  // Getting Started
  'quick-start':                   'getting-started/quick-start.md',
  'concepts':                      null,
  'architecture':                  null,
  'faq':                           null,

  // Feature Flags
  'feature-flags/create':          null,
  'feature-flags/targeting':       'Enhanced_Rules_Engine_Reference.md',
  'feature-flags/rollouts':        null,
  'feature-flags/safety':          null,

  // Experiments
  'experiments/run':               'guides/user-guide.md',
  'experiments/statistics':        'api/sequential-testing.md',
  'experiments/cuped':             'api/cuped.md',
  'experiments/mab':               'api/multi-armed-bandit.md',
  'experiments/split-url':         'api/split-url.md',
  'experiments/exclusion':         'api/mutual-exclusion-groups.md',

  // SDKs
  'sdks/javascript':               'sdk-guide.md',
  'sdks/python':                   'sdk-guide.md',
  'sdks/java':                     'sdk-guide.md',
  'sdks/react':                    'sdk-guide.md',
  'sdks/mcp':                      'mcp-server.md',

  // API Reference
  'api-reference/auth':            null,
  'api-reference/experiments':     'api/endpoints.md',
  'api-reference/feature-flags':   'api/endpoints.md',
  'api-reference/compliance':      'api/compliance.md',
  'api-reference/integrations':    'api/integrations.md',
  'api-reference/endpoints':       'api/endpoints.md',

  // Integrations
  'integrations/aws':              null,
  'integrations/warehouses':       'api/warehouse-analytics.md',
  'integrations/jira':             'api/integrations.md',
  'integrations/salesforce':       'api/integrations.md',
  'integrations/github':           'api/integrations.md',
  'integrations/notifications':    'api/alerting.md',

  // Security & Compliance
  'security/soc2':                 'api/compliance.md',
  'security/iso27001':             'api/compliance.md',
  'security/audit-logging':        'api/audit-logging.md',
  'security/rbac':                 'api/rbac.md',
  'security/api-keys':             null,

  // Self-Hosting
  'self-hosting/cdk':              null,
  'self-hosting/docker':           'getting-started/docker-guide.md',
  'self-hosting/env':              'getting-started/environment-setup.md',
  'self-hosting/migrations':       null,
  'self-hosting/monitoring':       null,

  // Guides
  'guides/first-ab-test':          'guides/user-guide.md',
  'guides/bayesian':               'api/bayesian.md',
  'guides/warehouse-analytics':    'api/warehouse-analytics.md',
  'guides/no-code-builder':        'guides/experiment-wizard.md',
  'guides/interaction-detection':  'api/interaction-detection.md',

  // Changelog
  'changelog':                     null,
  'changelog#all':                 null,
  'roadmap':                       null,
};

// Human-readable titles for each slug
const SLUG_TITLES: Record<string, string> = {
  'quick-start': 'Quick Start',
  'concepts': 'Core Concepts',
  'architecture': 'Architecture Overview',
  'faq': 'FAQ',
  'feature-flags/create': 'Creating Feature Flags',
  'feature-flags/targeting': 'Targeting & Rules',
  'feature-flags/rollouts': 'Gradual Rollouts',
  'feature-flags/safety': 'Safety Monitoring',
  'experiments/run': 'Running Experiments',
  'experiments/statistics': 'Statistical Methods',
  'experiments/cuped': 'CUPED Variance Reduction',
  'experiments/mab': 'Multi-Armed Bandits',
  'experiments/split-url': 'Split URL Testing',
  'experiments/exclusion': 'Mutual Exclusion Groups',
  'sdks/javascript': 'JavaScript SDK',
  'sdks/python': 'Python SDK',
  'sdks/java': 'Java SDK',
  'sdks/react': 'React SDK',
  'sdks/mcp': 'MCP Server',
  'api-reference/auth': 'Authentication',
  'api-reference/experiments': 'Experiments API',
  'api-reference/feature-flags': 'Feature Flags API',
  'api-reference/compliance': 'Compliance API',
  'api-reference/integrations': 'Integrations API',
  'api-reference/endpoints': 'All Endpoints',
  'integrations/aws': 'AWS Integration',
  'integrations/warehouses': 'Warehouse-Native Analytics',
  'integrations/jira': 'Jira Integration',
  'integrations/salesforce': 'Salesforce Integration',
  'integrations/github': 'GitHub Integration',
  'integrations/notifications': 'Slack & Email Notifications',
  'security/soc2': 'SOC 2 Compliance',
  'security/iso27001': 'ISO 27001 Compliance',
  'security/audit-logging': 'Audit Logging',
  'security/rbac': 'Role-Based Access Control',
  'security/api-keys': 'API Key Management',
  'self-hosting/cdk': 'AWS CDK Deployment',
  'self-hosting/docker': 'Docker Setup',
  'self-hosting/env': 'Environment Variables',
  'self-hosting/migrations': 'Database Migrations',
  'self-hosting/monitoring': 'Monitoring',
  'guides/first-ab-test': 'Your First A/B Test',
  'guides/bayesian': 'Bayesian Experimentation',
  'guides/warehouse-analytics': 'Warehouse-Native Analytics',
  'guides/no-code-builder': 'No-Code Experiment Builder',
  'guides/interaction-detection': 'Interaction Detection',
  'changelog': 'Changelog',
  'roadmap': 'Roadmap',
};

interface Props {
  slug: string;
  title: string;
  content: string | null;
}

export const getStaticPaths: GetStaticPaths = () => {
  const paths = Object.keys(SLUG_TO_FILE).map((slug) => ({
    params: { slug: slug.split('/') },
  }));
  return { paths, fallback: false };
};

export const getStaticProps: GetStaticProps<Props> = ({ params }) => {
  const slugParts = (params?.slug as string[]) ?? [];
  const slug = slugParts.join('/');
  const title = SLUG_TITLES[slug] ?? slug;
  const relFile = SLUG_TO_FILE[slug];

  let content: string | null = null;
  if (relFile) {
    const docsRoot = path.join(process.cwd(), '..', 'docs');
    const filePath = path.join(docsRoot, relFile);
    if (fs.existsSync(filePath)) {
      content = fs.readFileSync(filePath, 'utf-8');
    }
  }

  return { props: { slug, title, content } };
};

export default function DocPage({ slug, title, content }: Props) {
  const breadcrumbs = slug.split('/');

  return (
    <>
      <Head>
        <title>{title} — Experimently Docs</title>
        <meta name="description" content={`Experimently documentation: ${title}`} />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="min-h-screen bg-white">
        {/* Nav */}
        <nav className="border-b border-gray-100 bg-white sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-6 lg:px-8">
            <div className="flex justify-between items-center h-16">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Link href="/" className="text-gray-900 font-semibold text-base hover:text-blue-600 transition">
                  Experimently
                </Link>
                <span>/</span>
                <Link href="/docs" className="hover:text-gray-900 transition">Docs</Link>
                {breadcrumbs.map((crumb, i) => (
                  <span key={i} className="flex items-center gap-2">
                    <span>/</span>
                    <span className={i === breadcrumbs.length - 1 ? 'text-gray-900 font-medium' : ''}>
                      {crumb.replace(/-/g, ' ')}
                    </span>
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-4">
                <a href="https://app.getexperimently.com/login" className="text-gray-600 hover:text-gray-900 text-sm font-medium">Sign in</a>
                <a href="https://app.getexperimently.com/signup" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition">
                  Get started free
                </a>
              </div>
            </div>
          </div>
        </nav>

        <div className="max-w-4xl mx-auto px-6 lg:px-8 py-12">
          {content ? (
            <article className="prose prose-gray prose-headings:font-semibold prose-a:text-blue-600 max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {content}
              </ReactMarkdown>
            </article>
          ) : (
            <ComingSoon title={title} slug={slug} />
          )}

          <div className="mt-16 pt-8 border-t border-gray-100">
            <Link href="/docs" className="text-blue-600 hover:text-blue-700 text-sm font-medium">
              ← Back to documentation
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}

function ComingSoon({ title, slug }: { title: string; slug: string }) {
  // Related links to suggest based on section
  const section = slug.split('/')[0];
  const suggestions: Record<string, { label: string; href: string }[]> = {
    'feature-flags': [
      { label: 'Targeting & Rules', href: '/docs/feature-flags/targeting' },
      { label: 'All Endpoints', href: '/docs/api-reference/endpoints' },
    ],
    'api-reference': [
      { label: 'All Endpoints', href: '/docs/api-reference/endpoints' },
      { label: 'Compliance API', href: '/docs/api-reference/compliance' },
    ],
    'integrations': [
      { label: 'Integrations API Reference', href: '/docs/api-reference/integrations' },
      { label: 'Warehouse Analytics', href: '/docs/integrations/warehouses' },
    ],
    'security': [
      { label: 'Audit Logging', href: '/docs/security/audit-logging' },
      { label: 'Compliance API', href: '/docs/api-reference/compliance' },
    ],
    'self-hosting': [
      { label: 'Docker Setup', href: '/docs/self-hosting/docker' },
      { label: 'Environment Variables', href: '/docs/self-hosting/env' },
    ],
  };

  const related = suggestions[section] ?? [
    { label: 'Quick Start', href: '/docs/quick-start' },
    { label: 'All Endpoints', href: '/docs/api-reference/endpoints' },
  ];

  return (
    <div className="text-center py-20">
      <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-50 mb-6">
        <svg className="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <h1 className="text-3xl font-bold text-gray-900 mb-3">{title}</h1>
      <p className="text-gray-500 mb-8 max-w-md mx-auto">
        This page is being written. Check back soon, or reach out if you need help now.
      </p>
      <div className="flex flex-wrap gap-3 justify-center mb-10">
        <a
          href="mailto:hello@getexperimently.com"
          className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition"
        >
          Contact us
        </a>
        <Link
          href="/docs"
          className="bg-gray-100 text-gray-900 px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-200 transition"
        >
          Browse all docs
        </Link>
      </div>
      {related.length > 0 && (
        <div className="text-left max-w-sm mx-auto">
          <p className="text-sm font-medium text-gray-700 mb-3">Related pages you can read now:</p>
          <ul className="space-y-2">
            {related.map((r) => (
              <li key={r.href}>
                <Link href={r.href} className="text-sm text-blue-600 hover:text-blue-700 transition">
                  → {r.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

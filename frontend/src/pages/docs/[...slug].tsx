import fs from 'fs';
import path from 'path';
import Link from 'next/link';
import { PageTitle } from '@/components/PageTitle';
import { GetStaticPaths, GetStaticProps } from 'next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ComponentPropsWithoutRef } from 'react';

const SLUG_TO_FILE: Record<string, string> = {
  // Getting Started
  'quick-start':                   'getting-started/quick-start.md',
  'concepts':                      'getting-started/concepts.md',
  'architecture':                  'getting-started/architecture.md',
  'faq':                           'getting-started/faq.md',

  // Feature Flags
  'feature-flags/create':          'feature-flags/create.md',
  'feature-flags/targeting':       'Enhanced_Rules_Engine_Reference.md',
  'feature-flags/rollouts':        'feature-flags/rollouts.md',
  'feature-flags/safety':          'feature-flags/safety.md',

  // Experiments
  'experiments/run':               'guides/user-guide.md',
  'experiments/statistics':        'api/sequential-testing.md',
  'experiments/cuped':             'api/cuped.md',
  'experiments/mab':               'api/multi-armed-bandit.md',
  'experiments/split-url':         'api/split-url.md',
  'experiments/exclusion':         'api/mutual-exclusion-groups.md',

  // SDKs
  'sdks/javascript':               'sdk/javascript.md',
  'sdks/python':                   'sdk-guide.md',
  'sdks/java':                     'sdk/java.md',
  'sdks/react':                    'sdk/react.md',
  'sdks/go':                       'sdk/go.md',
  'sdks/ios':                      'sdk/ios.md',
  'sdks/android':                  'sdk/android.md',
  'sdks/flutter':                  'sdk/flutter.md',
  'sdks/react-native':             'sdk/react-native.md',
  'sdks/mcp':                      'mcp-server.md',
  'sdks/openfeature':              'sdk/openfeature.md',
  'sdks/edge':                     'sdk/edge.md',
  'sdks/ruby':                     'sdk/ruby.md',
  'sdks/php':                      'sdk/php.md',
  'sdks/dotnet':                   'sdk/dotnet.md',
  'sdks/elixir':                   'sdk/elixir.md',

  // API Reference
  'api-reference/auth':            'api/auth.md',
  'api-reference/experiments':     'api/endpoints.md',
  'api-reference/feature-flags':   'api/endpoints.md',
  'api-reference/compliance':      'api/compliance.md',
  'api-reference/integrations':    'api/integrations.md',
  'api-reference/endpoints':       'api/endpoints.md',

  // LLM / AI Model Evaluation
  'llm-evaluation/overview':       'llm-evaluation/overview.md',
  'llm-evaluation/quickstart':     'llm-evaluation/quickstart.md',

  // Integrations
  'integrations/aws':              'integrations/aws.md',
  'integrations/warehouses':       'api/warehouse-analytics.md',
  'integrations/databricks':       'warehouse/databricks.md',
  'integrations/clickhouse':       'warehouse/clickhouse.md',
  'integrations/mysql':            'warehouse/mysql.md',
  'integrations/jira':             'api/integrations.md',
  'integrations/salesforce':       'integrations/salesforce.md',
  'integrations/github':           'integrations/github.md',
  'integrations/notifications':    'api/alerting.md',

  // Auth
  'auth/sso':                      'auth/sso.md',

  // Security & Compliance
  'security/soc2':                 'api/compliance.md',
  'security/iso27001':             'api/compliance.md',
  'security/audit-logging':        'api/audit-logging.md',
  'security/rbac':                 'api/rbac.md',
  'security/api-keys':             'security/api-keys.md',

  // Self-Hosting
  'self-hosting/cdk':              'self-hosting/cdk.md',
  'self-hosting/docker':           'getting-started/docker-guide.md',
  'self-hosting/env':              'getting-started/environment-setup.md',
  'self-hosting/migrations':       'self-hosting/migrations.md',
  'self-hosting/monitoring':       'self-hosting/monitoring.md',

  // Guides & Tutorials
  'guides/first-ab-test':          'guides/user-guide.md',
  'guides/bayesian':               'api/bayesian.md',
  'guides/warehouse-analytics':    'api/warehouse-analytics.md',
  'guides/no-code-builder':        'guides/experiment-wizard.md',
  'guides/interaction-detection':  'api/interaction-detection.md',

  // EP-043: Post-Stratification & BH FDR Correction
  'statistics/post-stratification': 'statistics/post-stratification.md',
  'statistics/fdr-correction':      'statistics/fdr-correction.md',

  // EP-056: Pre-Experiment Power Analysis
  'statistics/power-analysis':      'statistics/power-analysis.md',

  // EP-057: Multi-Tenant Team Workspaces
  'workspaces/overview':            'workspaces/overview.md',
  'workspaces/quickstart':          'workspaces/quickstart.md',

  // EP-050: HIPAA Compliance
  'hipaa/overview':                 'hipaa/overview.md',

  // EP-058: WebSocket Streaming
  'websocket-streaming':            'websocket-streaming.md',
  'experiments/live-streaming':     'websocket-streaming.md',
};

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
  'statistics/post-stratification': 'Post-Stratification Variance Reduction',
  'statistics/fdr-correction': 'Benjamini-Hochberg FDR Correction',
  'statistics/power-analysis': 'Statistical Power Analysis',
  'workspaces/overview': 'Team Workspaces — Overview',
  'workspaces/quickstart': 'Team Workspaces — Quickstart',
  'sdks/javascript': 'JavaScript SDK',
  'sdks/python': 'Python SDK',
  'sdks/java': 'Java SDK',
  'sdks/react': 'React SDK',
  'sdks/go': 'Go SDK',
  'sdks/ios': 'iOS Swift SDK',
  'sdks/android': 'Android Kotlin SDK',
  'sdks/flutter': 'Flutter SDK',
  'sdks/react-native': 'React Native SDK',
  'sdks/mcp': 'MCP Server',
  'sdks/openfeature': 'OpenFeature Provider',
  'sdks/edge': 'Edge SDK (Cloudflare / Vercel / Deno)',
  'sdks/ruby': 'Ruby SDK',
  'sdks/php': 'PHP SDK',
  'sdks/dotnet': '.NET SDK',
  'sdks/elixir': 'Elixir SDK',
  'hipaa/overview': 'HIPAA Compliance',
  'websocket-streaming': 'Live Results Streaming (WebSocket)',
  'experiments/live-streaming': 'Live Results Streaming (WebSocket)',
  'auth/sso': 'Enterprise SSO / SAML',
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
  'self-hosting/monitoring': 'Monitoring & Observability',
  'guides/first-ab-test': 'Your First A/B Test',
  'guides/bayesian': 'Bayesian Experimentation',
  'guides/warehouse-analytics': 'Warehouse-Native Analytics',
  'guides/no-code-builder': 'Guided Experiment Builder',
  'guides/interaction-detection': 'Interaction Detection',
};

// Reverse map: doc file path → canonical /docs/<slug>
const FILE_TO_SLUG: Record<string, string> = {
  'getting-started/quick-start.md':        'quick-start',
  'getting-started/concepts.md':           'concepts',
  'getting-started/architecture.md':       'architecture',
  'getting-started/faq.md':               'faq',
  'feature-flags/create.md':              'feature-flags/create',
  'Enhanced_Rules_Engine_Reference.md':    'feature-flags/targeting',
  'feature-flags/rollouts.md':            'feature-flags/rollouts',
  'feature-flags/safety.md':              'feature-flags/safety',
  'guides/user-guide.md':                 'experiments/run',
  'api/sequential-testing.md':            'experiments/statistics',
  'api/cuped.md':                         'experiments/cuped',
  'api/multi-armed-bandit.md':            'experiments/mab',
  'api/split-url.md':                     'experiments/split-url',
  'api/mutual-exclusion-groups.md':       'experiments/exclusion',
  'sdk/javascript.md':                    'sdks/javascript',
  'sdk-guide.md':                         'sdks/python',
  'sdk/java.md':                          'sdks/java',
  'sdk/react.md':                         'sdks/react',
  'sdk/go.md':                            'sdks/go',
  'sdk/ios.md':                           'sdks/ios',
  'sdk/android.md':                       'sdks/android',
  'sdk/flutter.md':                       'sdks/flutter',
  'sdk/react-native.md':                  'sdks/react-native',
  'mcp-server.md':                        'sdks/mcp',
  'sdk/openfeature.md':                   'sdks/openfeature',
  'sdk/edge.md':                          'sdks/edge',
  'sdk/ruby.md':                          'sdks/ruby',
  'sdk/php.md':                           'sdks/php',
  'sdk/dotnet.md':                        'sdks/dotnet',
  'sdk/elixir.md':                        'sdks/elixir',
  'hipaa/overview.md':                    'hipaa/overview',
  'websocket-streaming.md':               'websocket-streaming',
  'auth/sso.md':                          'auth/sso',
  'api/auth.md':                          'api-reference/auth',
  'api/endpoints.md':                     'api-reference/endpoints',
  'api/compliance.md':                    'api-reference/compliance',
  'api/integrations.md':                  'api-reference/integrations',
  'integrations/aws.md':                  'integrations/aws',
  'api/warehouse-analytics.md':           'integrations/warehouses',
  'integrations/salesforce.md':           'integrations/salesforce',
  'integrations/github.md':               'integrations/github',
  'api/alerting.md':                      'integrations/notifications',
  'api/audit-logging.md':                 'security/audit-logging',
  'api/rbac.md':                          'security/rbac',
  'security/api-keys.md':                 'security/api-keys',
  'self-hosting/cdk.md':                  'self-hosting/cdk',
  'getting-started/docker-guide.md':      'self-hosting/docker',
  'getting-started/environment-setup.md': 'self-hosting/env',
  'self-hosting/migrations.md':           'self-hosting/migrations',
  'self-hosting/monitoring.md':           'self-hosting/monitoring',
  'api/bayesian.md':                      'guides/bayesian',
  'guides/experiment-wizard.md':          'guides/no-code-builder',
  'api/interaction-detection.md':         'guides/interaction-detection',
  'workspaces/overview.md':              'workspaces/overview',
  'workspaces/quickstart.md':            'workspaces/quickstart',
};

function resolveHref(href: string, currentFile: string): string {
  if (!href || href.startsWith('http') || href.startsWith('mailto:') || href.startsWith('#')) {
    return href;
  }
  if (!href.endsWith('.md')) {
    return href;
  }
  // Resolve relative path from currentFile's directory
  const dir = currentFile.includes('/') ? currentFile.substring(0, currentFile.lastIndexOf('/') + 1) : '';
  const parts = (dir + href).split('/');
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === '..') resolved.pop();
    else if (part !== '.') resolved.push(part);
  }
  const resolvedPath = resolved.join('/');
  const slug = FILE_TO_SLUG[resolvedPath];
  return slug ? `/docs/${slug}` : `/docs/${resolvedPath.replace(/\.md$/, '')}`;
}

interface Props {
  slug: string;
  title: string;
  content: string;
  currentFile: string;
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

  // The markdown lives in the repository's docs/ directory, next to frontend/.
  // DOCS_ROOT overrides the location (e.g. an unusual container layout).
  const docsRoot = process.env.DOCS_ROOT || path.join(process.cwd(), '..', 'docs');
  const filePath = path.join(docsRoot, relFile);

  if (!fs.existsSync(filePath)) {
    // Fail the build rather than ship a placeholder page: every slug in
    // SLUG_TO_FILE must point at a real file.
    throw new Error(
      `Docs page "${slug}" maps to ${relFile}, but ${filePath} does not exist. ` +
        'Is docs/ available to the build (docker context = repository root)?',
    );
  }
  const content = fs.readFileSync(filePath, 'utf-8');

  return { props: { slug, title, content, currentFile: relFile } };
};

export default function DocPage({ slug, title, content, currentFile }: Props) {
  const breadcrumbs = slug.split('/');

  return (
    <>
      <PageTitle title={`${title} · Docs`} description={`Experimently documentation: ${title}`} />

      <div className="flex-1 bg-white">
        {/* Breadcrumbs */}
        <div className="border-b border-gray-100 bg-white">
          <div className="max-w-7xl mx-auto px-6 lg:px-8">
            <nav aria-label="Breadcrumb" className="flex items-center gap-2 h-12 text-sm text-gray-500">
              <Link href="/docs" className="hover:text-gray-900 transition">Docs</Link>
              {breadcrumbs.map((crumb, i) => (
                <span key={i} className="flex items-center gap-2">
                  <span>/</span>
                  <span className={i === breadcrumbs.length - 1 ? 'text-gray-900 font-medium' : ''}>
                    {crumb.replace(/-/g, ' ')}
                  </span>
                </span>
              ))}
            </nav>
          </div>
        </div>

        <div className="max-w-4xl mx-auto px-6 lg:px-8 py-12">
          <article className="prose prose-gray prose-headings:font-semibold prose-a:text-blue-600 max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children, ...props }: ComponentPropsWithoutRef<'a'>) => {
                  const resolved = resolveHref(href ?? '', currentFile);
                  if (resolved.startsWith('/')) {
                    return <Link href={resolved} className="text-blue-600 hover:text-blue-700">{children}</Link>;
                  }
                  return <a href={resolved} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </article>

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

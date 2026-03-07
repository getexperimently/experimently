import Head from 'next/head';
import Link from 'next/link';

const sections = [
  {
    category: 'Getting Started',
    icon: '🚀',
    description: 'Get up and running in under 10 minutes.',
    links: [
      { label: 'Quick Start', href: '/docs/quick-start', desc: 'Create your first experiment in minutes' },
      { label: 'Core Concepts', href: '/docs/concepts', desc: 'Feature flags, experiments, variants, and metrics' },
      { label: 'Architecture Overview', href: '/docs/architecture', desc: 'How Experimently works under the hood' },
      { label: 'FAQ', href: '/docs/faq', desc: 'Common questions answered' },
    ],
  },
  {
    category: 'Feature Flags',
    icon: '🚩',
    description: 'Control feature rollouts safely with targeting rules.',
    links: [
      { label: 'Creating Feature Flags', href: '/docs/feature-flags/create', desc: 'Set up your first flag' },
      { label: 'Targeting & Rules', href: '/docs/feature-flags/targeting', desc: '20+ operators, segment targeting' },
      { label: 'Gradual Rollouts', href: '/docs/feature-flags/rollouts', desc: 'Staged rollout schedules' },
      { label: 'Safety Monitoring', href: '/docs/feature-flags/safety', desc: 'Auto-rollback on error spikes' },
    ],
  },
  {
    category: 'A/B Testing & Experiments',
    icon: '⚗️',
    description: 'Design, run, and analyze experiments with statistical rigour.',
    links: [
      { label: 'Running Experiments', href: '/docs/experiments/run', desc: 'End-to-end experiment lifecycle' },
      { label: 'Statistical Methods', href: '/docs/experiments/statistics', desc: 'Frequentist, Bayesian, sequential testing' },
      { label: 'CUPED Variance Reduction', href: '/docs/experiments/cuped', desc: 'Reduce variance with pre-experiment covariates' },
      { label: 'Multi-Armed Bandits', href: '/docs/experiments/mab', desc: 'Thompson Sampling, UCB1, Epsilon-Greedy' },
      { label: 'Split URL Testing', href: '/docs/experiments/split-url', desc: 'Server-side URL splitting via Lambda@Edge' },
      { label: 'Mutual Exclusion Groups', href: '/docs/experiments/exclusion', desc: 'Prevent cross-experiment contamination' },
    ],
  },
  {
    category: 'LLM / AI Model Evaluation',
    icon: '🤖',
    description: 'Compare prompt versions, model variants, and agent configs against real business metrics.',
    links: [
      { label: 'Overview', href: '/docs/llm-evaluation/overview', desc: 'What LLM evaluation is and why it matters' },
      { label: 'Quick Start', href: '/docs/llm-evaluation/quickstart', desc: 'Compare GPT-4o vs Claude Sonnet in 5 minutes' },
    ],
  },
  {
    category: 'SDKs',
    icon: '📦',
    description: 'Client libraries for every major language and framework.',
    links: [
      { label: 'JavaScript SDK', href: '/docs/sdks/javascript', desc: 'Browser and Node.js' },
      { label: 'Python SDK', href: '/docs/sdks/python', desc: 'Server-side Python integration' },
      { label: 'Java SDK', href: '/docs/sdks/java', desc: 'Spring Boot auto-configuration, consistent hash bucketing' },
      { label: 'React SDK', href: '/docs/sdks/react', desc: 'Hooks, HOC, SSR support via ServerClient' },
      { label: 'Go SDK', href: '/docs/sdks/go', desc: 'Native Go client for microservices and CLIs. Zero dependencies, context-aware, goroutine-safe.' },
      { label: 'iOS Swift SDK', href: '/docs/sdks/ios', desc: 'Native Swift SDK for iOS 14+ and macOS 11+. Async/await API, offline fallback.' },
      { label: 'Android Kotlin SDK', href: '/docs/sdks/android', desc: 'Native Kotlin SDK for Android (minSdk 21). Coroutines, OkHttp, Compose examples.' },
      { label: 'Flutter SDK', href: '/docs/sdks/flutter', desc: 'Dart SDK for Flutter (iOS, Android, Web, Desktop). Offline fallback, consistent hashing.' },
      { label: 'React Native SDK', href: '/docs/sdks/react-native', desc: 'useFlag and useExperiment hooks, Provider, AsyncStorage offline support.' },
      { label: 'MCP Server', href: '/docs/sdks/mcp', desc: 'AI-powered experiment design via Model Context Protocol' },
      { label: 'OpenFeature Provider', href: '/docs/sdks/openfeature', desc: 'CNCF-standard OpenFeature provider for TypeScript and Python — swap vendors without changing app code' },
      { label: 'Edge SDK', href: '/docs/sdks/edge', desc: 'Sub-millisecond evaluation for Cloudflare Workers, Vercel Edge, and Deno Deploy — zero Node.js dependencies, pure-JS MD5 consistent hash' },
    ],
  },
  {
    category: 'API Reference',
    icon: '📡',
    description: 'Full REST API documentation with request/response schemas.',
    links: [
      { label: 'Authentication', href: '/docs/api-reference/auth', desc: 'API keys and JWT tokens' },
      { label: 'Experiments', href: '/docs/api-reference/experiments', desc: 'CRUD, scheduling, results' },
      { label: 'Feature Flags', href: '/docs/api-reference/feature-flags', desc: 'Flags, rollouts, evaluation' },
      { label: 'Compliance & Audit', href: '/docs/api-reference/compliance', desc: 'Audit events, SOC 2 / ISO 27001 reports, export' },
      { label: 'Integrations', href: '/docs/api-reference/integrations', desc: 'Jira, Salesforce, GitHub webhooks' },
      { label: 'All Endpoints', href: '/docs/api-reference/endpoints', desc: 'Complete endpoint reference' },
    ],
  },
  {
    category: 'Integrations',
    icon: '🔌',
    description: 'Connect Experimently to your existing data stack.',
    links: [
      { label: 'AWS', href: '/docs/integrations/aws', desc: 'ECS, Lambda, CloudFront, DynamoDB' },
      { label: 'Data Warehouses', href: '/docs/integrations/warehouses', desc: 'Snowflake, BigQuery, Redshift — warehouse-native analytics' },
      { label: 'Databricks', href: '/docs/integrations/databricks', desc: 'Databricks SQL warehouse connector — read-only analytics via Unity Catalog' },
      { label: 'ClickHouse', href: '/docs/integrations/clickhouse', desc: 'ClickHouse columnar analytics connector — blazing fast OLAP queries' },
      { label: 'MySQL', href: '/docs/integrations/mysql', desc: 'MySQL / MariaDB connector — parameterised read-only analytics queries' },
      { label: 'Jira', href: '/docs/integrations/jira', desc: 'Sync experiment status, auto-create issues' },
      { label: 'Salesforce', href: '/docs/integrations/salesforce', desc: 'OAuth2 integration, webhook sync' },
      { label: 'GitHub', href: '/docs/integrations/github', desc: 'HMAC-signed webhooks, PR linking' },
      { label: 'Slack & Email', href: '/docs/integrations/notifications', desc: 'Alerting and experiment notifications' },
    ],
  },
  {
    category: 'Security & Compliance',
    icon: '🔒',
    description: 'Enterprise-grade security, audit logging, and compliance reports.',
    links: [
      { label: 'SOC 2 Compliance', href: '/docs/security/soc2', desc: 'SOC 2 Type II audit report export' },
      { label: 'ISO 27001', href: '/docs/security/iso27001', desc: 'ISO 27001 compliance report export' },
      { label: 'Audit Logging', href: '/docs/security/audit-logging', desc: 'HMAC-SHA256 tamper-proof audit trail' },
      { label: 'RBAC', href: '/docs/security/rbac', desc: 'Role-based access control: Admin, Developer, Analyst, Viewer' },
      { label: 'API Key Management', href: '/docs/security/api-keys', desc: 'Scoped keys, rotation, revocation' },
      { label: 'Enterprise SSO', href: '/docs/auth/sso', desc: 'SAML 2.0, OIDC/OAuth2 for Okta, Azure AD, Google Workspace, GitHub, and OneLogin.' },
    ],
  },
  {
    category: 'Self-Hosting',
    icon: '🏗️',
    description: 'Deploy Experimently to your own AWS account.',
    links: [
      { label: 'AWS CDK Deployment', href: '/docs/self-hosting/cdk', desc: 'One-command CDK deploy to ECS Fargate' },
      { label: 'Docker Compose', href: '/docs/self-hosting/docker', desc: 'Local development setup' },
      { label: 'Environment Variables', href: '/docs/self-hosting/env', desc: 'Configuration reference' },
      { label: 'Database Migrations', href: '/docs/self-hosting/migrations', desc: 'Alembic migration guide' },
      { label: 'Monitoring', href: '/docs/self-hosting/monitoring', desc: 'CloudWatch dashboards, Prometheus metrics' },
    ],
  },
  {
    category: 'Guides & Tutorials',
    icon: '📖',
    description: 'Step-by-step walkthroughs for common use cases.',
    links: [
      { label: 'Your First A/B Test', href: '/docs/guides/first-ab-test', desc: 'End-to-end experiment walkthrough' },
      { label: 'Bayesian Experimentation', href: '/docs/guides/bayesian', desc: 'Beta-Binomial posteriors and stopping rules' },
      { label: 'Warehouse-Native Analytics', href: '/docs/guides/warehouse-analytics', desc: 'Query Snowflake/BigQuery directly' },
      { label: 'No-Code Experiment Builder', href: '/docs/guides/no-code-builder', desc: '5-step visual wizard' },
      { label: 'Interaction Detection', href: '/docs/guides/interaction-detection', desc: 'Detect and handle experiment interactions' },
    ],
  },
  {
    category: 'Statistics Reference',
    icon: 'S',
    description: 'Deep dives into the statistical methods used by the platform.',
    links: [
      { label: 'Power Analysis & Sample Size', href: '/docs/statistics/power-analysis', desc: 'Pre-experiment planning: MDE, alpha, power, runtime estimation' },
      { label: 'Post-Stratification', href: '/docs/statistics/post-stratification', desc: 'Variance reduction using post-experiment stratification' },
      { label: 'FDR Correction', href: '/docs/statistics/fdr-correction', desc: 'Benjamini-Hochberg false discovery rate correction for multiple metrics' },
    ],
  },
  {
    category: 'Team Workspaces',
    icon: 'W',
    description: 'Isolate experiments and feature flags per team, project, or product area with role-based access control.',
    links: [
      { label: 'Workspace Overview', href: '/docs/workspaces/overview', desc: 'Role hierarchy (OWNER → VIEWER), plan limits, scoped API keys' },
      { label: 'Quickstart', href: '/docs/workspaces/quickstart', desc: 'Create a workspace, invite your team, and generate a scoped API key' },
    ],
  },
];

const quickLinks = [
  { label: '5-minute Quick Start', href: '/docs/quick-start', color: 'bg-blue-600 hover:bg-blue-700 text-white' },
  { label: 'API Reference', href: '/docs/api-reference/endpoints', color: 'bg-gray-900 hover:bg-gray-800 text-white' },
  { label: 'SDK Guides', href: '/docs/sdks/javascript', color: 'bg-white hover:bg-gray-50 text-gray-900 border border-gray-200' },
];

export default function DocsIndex() {
  return (
    <>
      <Head>
        <title>Documentation — Experimently</title>
        <meta name="description" content="Experimently documentation: quick start, SDK guides, API reference, integrations, security and self-hosting." />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="min-h-screen bg-white">
        {/* Navigation */}
        <nav className="border-b border-gray-100 bg-white sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-6 lg:px-8">
            <div className="flex justify-between items-center h-16">
              <div className="flex items-center gap-8">
                <Link href="/" className="text-xl font-semibold text-gray-900">
                  Experimently
                </Link>
                <span className="text-gray-300">/</span>
                <span className="text-sm font-medium text-gray-600">Documentation</span>
              </div>
              <div className="flex items-center gap-4">
                <a href="/experiments" className="text-gray-600 hover:text-gray-900 text-sm font-medium">
                  Sign in
                </a>
                <a href="/docs/quick-start" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition">
                  Get started free
                </a>
              </div>
            </div>
          </div>
        </nav>

        {/* Hero */}
        <div className="bg-gray-50 border-b border-gray-100 py-16 px-6">
          <div className="max-w-4xl mx-auto text-center">
            <h1 className="text-4xl font-bold text-gray-900 mb-4">
              Experimently Documentation
            </h1>
            <p className="text-xl text-gray-600 mb-8">
              Everything you need to build, ship, and measure with confidence.
            </p>
            <div className="flex flex-wrap gap-3 justify-center">
              {quickLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`px-6 py-3 rounded-lg font-medium text-sm transition shadow-sm ${link.color}`}
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* Search hint */}
        <div className="max-w-7xl mx-auto px-6 lg:px-8 py-6">
          <div className="flex items-center gap-2 bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 max-w-lg">
            <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="text-sm text-gray-400">Search the docs… (coming soon)</span>
          </div>
        </div>

        {/* Docs grid */}
        <div className="max-w-7xl mx-auto px-6 lg:px-8 pb-24">
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {sections.map((section) => (
              <div key={section.category} className="border border-gray-200 rounded-xl p-6 hover:border-blue-200 hover:shadow-sm transition">
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-2xl">{section.icon}</span>
                  <h2 className="text-lg font-semibold text-gray-900">{section.category}</h2>
                </div>
                <p className="text-sm text-gray-500 mb-5">{section.description}</p>
                <ul className="space-y-3">
                  {section.links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className="group flex items-start gap-2 text-sm"
                      >
                        <span className="text-blue-600 group-hover:text-blue-700 font-medium transition flex-shrink-0">
                          {link.label}
                        </span>
                        <span className="text-gray-400">—</span>
                        <span className="text-gray-500 group-hover:text-gray-700 transition">
                          {link.desc}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <footer className="bg-gray-900 text-white py-12 px-6">
          <div className="max-w-7xl mx-auto">
            <div className="flex flex-col md:flex-row justify-between items-center gap-6">
              <div>
                <Link href="/" className="text-xl font-semibold text-white">
                  Experimently
                </Link>
                <p className="text-gray-400 text-sm mt-1">Modern experimentation platform</p>
              </div>
              <div className="flex flex-wrap gap-6 text-sm text-gray-400">
                <Link href="/" className="hover:text-white transition">Home</Link>
                <Link href="/docs" className="hover:text-white transition">Docs</Link>
                <Link href="/docs/api-reference/endpoints" className="hover:text-white transition">API Reference</Link>
                <Link href="/docs/sdks/javascript" className="hover:text-white transition">SDKs</Link>
                <a href="mailto:hello@getexperimently.com" className="hover:text-white transition">Contact</a>
              </div>
            </div>
            <div className="border-t border-gray-800 mt-8 pt-8">
              <p className="text-gray-500 text-sm text-center">
                © 2026 Experimently. All rights reserved.
              </p>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}

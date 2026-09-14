import { PageTitle } from '@/components/PageTitle';
import Link from 'next/link';
import { docsUrl } from '@/services/docs';

const sections = [
  {
    category: 'Getting Started',
    icon: '🚀',
    description: 'Get up and running in under 10 minutes.',
    links: [
      { label: 'Quick Start', href: docsUrl('getting-started/quick-start'), desc: 'Create your first experiment in minutes' },
      { label: 'Core Concepts', href: docsUrl('getting-started/concepts'), desc: 'Feature flags, experiments, variants, and metrics' },
      { label: 'Architecture Overview', href: docsUrl('getting-started/architecture'), desc: 'How Experimently works under the hood' },
      { label: 'FAQ', href: docsUrl('getting-started/faq'), desc: 'Common questions answered' },
      { label: 'Modules & Profiles', href: docsUrl('getting-started/modules'), desc: 'What the core profile includes, what each module adds, and how to run the full profile' },
    ],
  },
  {
    category: 'Feature Flags',
    icon: '🚩',
    description: 'Control feature rollouts safely with targeting rules.',
    links: [
      { label: 'Creating Feature Flags', href: docsUrl('feature-flags/create'), desc: 'Set up your first flag' },
      { label: 'Targeting & Rules', href: docsUrl('Enhanced_Rules_Engine_Reference'), desc: '20+ operators, segment targeting' },
      { label: 'Gradual Rollouts', href: docsUrl('feature-flags/rollouts'), desc: 'Staged rollout schedules' },
      { label: 'Safety Monitoring', href: docsUrl('feature-flags/safety'), desc: 'Auto-rollback on error spikes' },
    ],
  },
  {
    category: 'A/B Testing & Experiments',
    icon: '⚗️',
    description: 'Design, run, and analyze experiments with statistical rigour.',
    links: [
      { label: 'Running Experiments', href: docsUrl('guides/user-guide'), desc: 'End-to-end experiment lifecycle' },
      { label: 'Statistical Methods', href: docsUrl('api/sequential-testing'), desc: 'Frequentist, Bayesian, sequential testing' },
      { label: 'CUPED Variance Reduction', href: docsUrl('api/cuped'), desc: 'Reduce variance with pre-experiment covariates' },
      { label: 'Multi-Armed Bandits', href: docsUrl('api/multi-armed-bandit'), desc: 'Thompson Sampling, UCB1, Epsilon-Greedy' },
      { label: 'Split URL Testing', href: docsUrl('api/split-url'), desc: 'Server-side URL splitting via Lambda@Edge' },
      { label: 'Mutual Exclusion Groups', href: docsUrl('api/mutual-exclusion-groups'), desc: 'Prevent cross-experiment contamination' },
      { label: 'Live Results Streaming', href: docsUrl('websocket-streaming'), desc: 'Real-time experiment results via WebSocket — p-values, lift, and significance updated live.' },
    ],
  },
  {
    category: 'LLM / AI Model Evaluation',
    icon: '🤖',
    description: 'Compare prompt versions, model variants, and agent configs against real business metrics.',
    links: [
      { label: 'Overview', href: docsUrl('llm-evaluation/overview'), desc: 'What LLM evaluation is and why it matters' },
      { label: 'Quick Start', href: docsUrl('llm-evaluation/quickstart'), desc: 'Compare GPT-4o vs Claude Sonnet in 5 minutes' },
    ],
  },
  {
    category: 'SDKs',
    icon: '📦',
    description: 'Client libraries for 14 languages and frameworks — from web to mobile to server.',
    links: [
      { label: 'JavaScript SDK', href: docsUrl('sdk/javascript'), desc: 'Browser and Node.js' },
      { label: 'Python SDK', href: docsUrl('sdk-guide'), desc: 'Server-side Python integration' },
      { label: 'Java SDK', href: docsUrl('sdk/java'), desc: 'Spring Boot auto-configuration, consistent hash bucketing' },
      { label: 'React SDK', href: docsUrl('sdk/react'), desc: 'Hooks, HOC, SSR support via ServerClient' },
      { label: 'Go SDK', href: docsUrl('sdk/go'), desc: 'Native Go client for microservices and CLIs. Zero dependencies, context-aware, goroutine-safe.' },
      { label: 'iOS Swift SDK', href: docsUrl('sdk/ios'), desc: 'Native Swift SDK for iOS 14+ and macOS 11+. Async/await API, offline fallback.' },
      { label: 'Android Kotlin SDK', href: docsUrl('sdk/android'), desc: 'Native Kotlin SDK for Android (minSdk 21). Coroutines, OkHttp, Compose examples.' },
      { label: 'Flutter SDK', href: docsUrl('sdk/flutter'), desc: 'Dart SDK for Flutter (iOS, Android, Web, Desktop). Offline fallback, consistent hashing.' },
      { label: 'React Native SDK', href: docsUrl('sdk/react-native'), desc: 'useFlag and useExperiment hooks, Provider, AsyncStorage offline support.' },
      { label: 'MCP Server', href: docsUrl('mcp-server'), desc: 'AI-powered experiment design via Model Context Protocol' },
      { label: 'OpenFeature Provider', href: docsUrl('sdk/openfeature'), desc: 'CNCF-standard OpenFeature provider for TypeScript and Python — swap vendors without changing app code' },
      { label: 'Edge SDK', href: docsUrl('sdk/edge'), desc: 'Sub-millisecond evaluation for Cloudflare Workers, Vercel Edge, and Deno Deploy — zero Node.js dependencies, pure-JS MD5 consistent hash' },
      { label: 'Ruby SDK', href: docsUrl('sdk/ruby'), desc: 'Native Ruby gem, zero runtime dependencies, thread-safe Mutex TTL cache, Net::HTTP, consistent MD5 hash.' },
      { label: 'PHP SDK', href: docsUrl('sdk/php'), desc: 'Composer package (ext-json + ext-curl only), PSR-compatible, consistent MD5 hash bucketing.' },
      { label: '.NET SDK', href: docsUrl('sdk/dotnet'), desc: 'netstandard2.1 + net6.0, System.Text.Json, HttpClient, LRU cache with TTL, xUnit-tested.' },
      { label: 'Elixir SDK', href: docsUrl('sdk/elixir'), desc: 'Hex package with :httpc + Jason, GenServer-backed ETS cache, OTP-compatible, 93 ExUnit tests.' },
    ],
  },
  {
    category: 'API Reference',
    icon: '📡',
    description: 'Full REST API documentation with request/response schemas.',
    links: [
      { label: 'Authentication', href: docsUrl('api/auth'), desc: 'API keys and JWT tokens' },
      { label: 'Experiments', href: docsUrl('api/endpoints'), desc: 'CRUD, scheduling, results' },
      { label: 'Feature Flags', href: docsUrl('api/endpoints'), desc: 'Flags, rollouts, evaluation' },
      { label: 'Compliance & Audit', href: docsUrl('api/compliance'), desc: 'Audit events, SOC 2 / ISO 27001 reports, export' },
      { label: 'Integrations', href: docsUrl('api/integrations'), desc: 'Jira, Salesforce, GitHub webhooks' },
      { label: 'All Endpoints', href: docsUrl('api/endpoints'), desc: 'Complete endpoint reference' },
    ],
  },
  {
    category: 'Integrations',
    icon: '🔌',
    description: 'Connect Experimently to your existing data stack.',
    links: [
      { label: 'AWS', href: docsUrl('integrations/aws'), desc: 'ECS, Lambda, CloudFront, DynamoDB' },
      { label: 'Data Warehouses', href: docsUrl('api/warehouse-analytics'), desc: 'Snowflake, BigQuery, Redshift — warehouse-native analytics' },
      { label: 'Databricks', href: docsUrl('warehouse/databricks'), desc: 'Databricks SQL warehouse connector — read-only analytics via Unity Catalog' },
      { label: 'ClickHouse', href: docsUrl('warehouse/clickhouse'), desc: 'ClickHouse columnar analytics connector — blazing fast OLAP queries' },
      { label: 'MySQL', href: docsUrl('warehouse/mysql'), desc: 'MySQL / MariaDB connector — parameterised read-only analytics queries' },
      { label: 'Jira', href: docsUrl('api/integrations'), desc: 'Sync experiment status, auto-create issues' },
      { label: 'Salesforce', href: docsUrl('integrations/salesforce'), desc: 'OAuth2 integration, webhook sync' },
      { label: 'GitHub', href: docsUrl('integrations/github'), desc: 'HMAC-signed webhooks, PR linking' },
      { label: 'Slack & Email', href: docsUrl('api/alerting'), desc: 'Alerting and experiment notifications' },
    ],
  },
  {
    category: 'Security & Compliance',
    icon: '🔒',
    description: 'Security, audit logging, and compliance reports.',
    links: [
      { label: 'Compliance audit logging', href: docsUrl('api/compliance'), desc: 'Signed audit events and report export' },
      { label: 'ISO 27001', href: docsUrl('api/compliance'), desc: 'ISO 27001 compliance report export' },
      { label: 'Audit Logging', href: docsUrl('api/audit-logging'), desc: 'HMAC-SHA256 tamper-proof audit trail' },
      { label: 'RBAC', href: docsUrl('api/rbac'), desc: 'Role-based access control: Admin, Developer, Analyst, Viewer' },
      { label: 'API Key Management', href: docsUrl('security/api-keys'), desc: 'Scoped keys, rotation, revocation' },
      { label: 'SSO / SAML / OIDC', href: docsUrl('auth/sso'), desc: 'SAML 2.0, OIDC/OAuth2 for Okta, Azure AD, Google Workspace, GitHub, and OneLogin.' },
      { label: 'HIPAA Compliance', href: docsUrl('hipaa/overview'), desc: 'PHI encryption (Fernet AES-128-CBC), 6-year audit retention, BAA management, data residency.' },
    ],
  },
  {
    category: 'Self-Hosting',
    icon: '🏗️',
    description: 'Deploy Experimently to your own AWS account.',
    links: [
      { label: 'AWS CDK Deployment', href: docsUrl('self-hosting/cdk'), desc: 'One-command CDK deploy to ECS Fargate' },
      { label: 'Docker Compose', href: docsUrl('getting-started/docker-guide'), desc: 'Local development setup' },
      { label: 'Environment Variables', href: docsUrl('getting-started/environment-setup'), desc: 'Configuration reference' },
      { label: 'Database Migrations', href: docsUrl('self-hosting/migrations'), desc: 'Alembic migration guide' },
      { label: 'Monitoring', href: docsUrl('self-hosting/monitoring'), desc: 'CloudWatch dashboards, Prometheus metrics' },
    ],
  },
  {
    category: 'Guides & Tutorials',
    icon: '📖',
    description: 'Step-by-step walkthroughs for common use cases.',
    links: [
      { label: 'Your First A/B Test', href: docsUrl('guides/user-guide'), desc: 'End-to-end experiment walkthrough' },
      { label: 'Bayesian Experimentation', href: docsUrl('api/bayesian'), desc: 'Beta-Binomial posteriors and stopping rules' },
      { label: 'Warehouse-Native Analytics', href: docsUrl('api/warehouse-analytics'), desc: 'Query Snowflake/BigQuery directly' },
      { label: 'Guided Experiment Builder', href: docsUrl('guides/experiment-wizard'), desc: '5-step draft-and-submit API' },
      { label: 'Interaction Detection', href: docsUrl('api/interaction-detection'), desc: 'Detect and handle experiment interactions' },
    ],
  },
  {
    category: 'Statistics Reference',
    icon: 'S',
    description: 'Deep dives into the statistical methods used by the platform.',
    links: [
      { label: 'Power Analysis & Sample Size', href: docsUrl('statistics/power-analysis'), desc: 'Pre-experiment planning: MDE, alpha, power, runtime estimation' },
      { label: 'Post-Stratification', href: docsUrl('statistics/post-stratification'), desc: 'Variance reduction using post-experiment stratification' },
      { label: 'FDR Correction', href: docsUrl('statistics/fdr-correction'), desc: 'Benjamini-Hochberg false discovery rate correction for multiple metrics' },
    ],
  },
  {
    category: 'Team Workspaces',
    icon: 'W',
    description: 'Isolate experiments and feature flags per team, project, or product area with role-based access control.',
    links: [
      { label: 'Workspace Overview', href: docsUrl('workspaces/overview'), desc: 'Role hierarchy (OWNER → VIEWER), plan limits, scoped API keys' },
      { label: 'Quickstart', href: docsUrl('workspaces/quickstart'), desc: 'Create a workspace, invite your team, and generate a scoped API key' },
    ],
  },
];

const quickLinks = [
  { label: '5-minute Quick Start', href: docsUrl('getting-started/quick-start'), color: 'bg-blue-600 hover:bg-blue-700 text-white' },
  { label: 'API Reference', href: docsUrl('api/endpoints'), color: 'bg-gray-900 hover:bg-gray-800 text-white' },
  { label: 'SDK Guides', href: docsUrl('sdk/javascript'), color: 'bg-white hover:bg-gray-50 text-gray-900 border border-gray-200' },
];

export default function DocsIndex() {
  return (
    <>
      <PageTitle
        title="Documentation"
        description="Experimently documentation: quick start, 14 SDK guides, API reference, integrations, HIPAA compliance, and self-hosting."
      />

      <div className="flex-1 bg-white">

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
                <a
                  key={link.href}
                  href={link.href}
                  target="_blank"
                  rel="noreferrer"
                  className={`px-6 py-3 rounded-lg font-medium text-sm transition shadow-sm ${link.color}`}
                >
                  {link.label}
                </a>
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
            <a href={docsUrl('')} target="_blank" rel="noreferrer" className="text-sm text-gray-500 hover:text-gray-700">Search the documentation site →</a>
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
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noreferrer"
                        className="group flex items-start gap-2 text-sm"
                      >
                        <span className="text-blue-600 group-hover:text-blue-700 font-medium transition flex-shrink-0">
                          {link.label}
                        </span>
                        <span className="text-gray-400">—</span>
                        <span className="text-gray-500 group-hover:text-gray-700 transition">
                          {link.desc}
                        </span>
                      </a>
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
                <a href={docsUrl('api/endpoints')} target="_blank" rel="noreferrer" className="hover:text-white transition">API Reference</a>
                <a href={docsUrl('sdk/javascript')} target="_blank" rel="noreferrer" className="hover:text-white transition">SDKs</a>
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

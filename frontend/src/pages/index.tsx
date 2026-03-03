import Head from 'next/head';

export default function Home() {
  return (
    <>
      <Head>
        <title>Experimently - Modern Experimentation Platform</title>
        <meta name="description" content="The modern product experimentation platform. A/B testing, feature flags, sequential testing, CUPED, and AI-powered experiment design — all in one platform." />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <div className="min-h-screen bg-white">
        {/* Navigation */}
        <nav className="border-b border-gray-100 bg-white sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-6 lg:px-8">
            <div className="flex justify-between items-center h-20">
              <div className="flex items-center gap-12">
                <span className="text-2xl font-semibold text-gray-900">
                  Experimently
                </span>
                <div className="hidden lg:flex items-center gap-8">
                  <a href="#features" className="text-gray-600 hover:text-gray-900 text-sm font-medium transition">Features</a>
                  <a href="#compare" className="text-gray-600 hover:text-gray-900 text-sm font-medium transition">Compare</a>
                  <a href="#pricing" className="text-gray-600 hover:text-gray-900 text-sm font-medium transition">Pricing</a>
                  <a href="/docs" className="text-gray-600 hover:text-gray-900 text-sm font-medium transition">Docs</a>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <a href="https://app.getexperimently.com/login" className="text-gray-600 hover:text-gray-900 text-sm font-medium">
                  Sign in
                </a>
                <a href="https://app.getexperimently.com/signup" className="bg-blue-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition">
                  Get started free
                </a>
              </div>
            </div>
          </div>
        </nav>

        {/* Hero Section */}
        <section className="pt-24 pb-16 px-6">
          <div className="max-w-5xl mx-auto text-center">
            <div className="inline-flex items-center gap-2 bg-blue-50 text-blue-700 px-4 py-2 rounded-full text-sm font-medium mb-8">
              <span className="w-2 h-2 bg-blue-600 rounded-full"></span>
              Now processing 1B+ events daily · Free Preview available
            </div>
            <h1 className="text-5xl md:text-6xl lg:text-7xl font-bold text-gray-900 mb-6 leading-tight">
              The modern product
              <br />
              experimentation platform
            </h1>
            <p className="text-xl md:text-2xl text-gray-600 mb-10 max-w-3xl mx-auto leading-relaxed">
              Sequential testing, CUPED variance reduction, multi-armed bandits, and AI-powered experiment design — enterprise statistics at every tier.
            </p>
            <p className="text-sm text-gray-500 mb-6 font-medium tracking-wide">
              Java, Python, React &amp; JS SDKs &nbsp;·&nbsp; SOC 2 compliant &nbsp;·&nbsp; Deploy to your AWS
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center items-center">
              <a href="https://app.getexperimently.com/signup" className="bg-blue-600 text-white px-8 py-4 rounded-lg text-base font-semibold hover:bg-blue-700 transition shadow-sm">
                Start experimenting free
              </a>
              <a href="#features" className="bg-white border-2 border-gray-200 text-gray-900 px-8 py-4 rounded-lg text-base font-semibold hover:border-gray-300 transition">
                Explore features
              </a>
            </div>
            <p className="text-sm text-gray-500 mt-6">Free Preview · All features included · No credit card required</p>
          </div>
        </section>

        {/* Stats Section */}
        <section className="py-16 border-t border-b border-gray-100 bg-gray-50">
          <div className="max-w-7xl mx-auto px-6">
            <div className="grid grid-cols-2 md:grid-cols-6 gap-8">
              <div className="text-center">
                <div className="text-4xl font-bold text-gray-900 mb-2">1B+</div>
                <div className="text-sm text-gray-600">Events daily</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-bold text-gray-900 mb-2">&lt;50ms</div>
                <div className="text-sm text-gray-600">P99 latency</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-bold text-gray-900 mb-2">99.99%</div>
                <div className="text-sm text-gray-600">Uptime SLA</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-bold text-gray-900 mb-2">20–40%</div>
                <div className="text-sm text-gray-600">Sample size reduction via CUPED</div>
              </div>
              <div className="text-center">
                <div className="text-4xl font-bold text-gray-900 mb-2">5</div>
                <div className="text-sm text-gray-600">SDK languages (Python, JS, Java, React, Go)</div>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-gray-900 mb-2">SOC 2</div>
                <div className="text-sm text-gray-600">SOC 2 / ISO 27001 ready</div>
              </div>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section id="features" className="py-24 px-6 bg-white">
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-20">
              <h2 className="text-4xl md:text-5xl font-bold text-gray-900 mb-4">
                Everything you need to experiment
              </h2>
              <p className="text-xl text-gray-600 max-w-2xl mx-auto">
                From feature flags to enterprise-grade statistical methods — all included
              </p>
            </div>

            {/* Core Features */}
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-6">Core Platform</p>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 mb-16">
              {/* A/B Testing */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">A/B Testing</h3>
                <p className="text-gray-600 leading-relaxed">
                  Run multivariate experiments with statistical rigor. Built-in significance testing, confidence intervals, and automated SHIP / KEEP / CONTINUE recommendations.
                </p>
              </div>

              {/* Feature Flags */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-indigo-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Feature Flags</h3>
                <p className="text-gray-600 leading-relaxed">
                  Deploy safely with gradual rollouts, staged schedules, and kill switches. Bulk toggle, SSE audit stream, and full change history included.
                </p>
              </div>

              {/* Real-time Analytics */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-purple-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Real-time Analytics</h3>
                <p className="text-gray-600 leading-relaxed">
                  See results as they happen. Trend charts, cumulative and daily views, sample size meters, and days-to-significance estimates.
                </p>
              </div>

              {/* Safety First */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-green-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Safety Monitoring</h3>
                <p className="text-gray-600 leading-relaxed">
                  Automated guardrails monitor error rates and performance. Auto-rollback on anomaly detection protects your users from bad releases.
                </p>
              </div>

              {/* Advanced Targeting */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-orange-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-orange-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Advanced Targeting</h3>
                <p className="text-gray-600 leading-relaxed">
                  20+ targeting operators including semantic versioning, geo-distance, time windows, and JSON path. Rules engine evaluates 125K+ ops/sec.
                </p>
              </div>

              {/* Developer First */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-pink-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-pink-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Developer First</h3>
                <p className="text-gray-600 leading-relaxed">
                  SDKs for Python, JavaScript, Java, and React. RESTful APIs with OpenAPI docs. RBAC with custom roles — ADMIN, DEVELOPER, ANALYST, VIEWER.
                </p>
              </div>
            </div>

            {/* Advanced Stats Features */}
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-6">Advanced Statistical Methods</p>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8 mb-16">
              {/* Sequential Testing */}
              <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-8 rounded-2xl border border-blue-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Sequential Testing</h3>
                <p className="text-gray-600 leading-relaxed">
                  mSPRT-based early stopping with always-valid confidence intervals. Stop experiments early when you have evidence, without inflating false positive rates. Alpha spending via O'Brien-Fleming and Pocock boundaries.
                </p>
              </div>

              {/* CUPED */}
              <div className="bg-gradient-to-br from-purple-50 to-pink-50 p-8 rounded-2xl border border-purple-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-purple-600 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">CUPED Variance Reduction</h3>
                <p className="text-gray-600 leading-relaxed">
                  Reach significance 20–40% faster using pre-experiment covariate adjustment (OLS θ). Winsorization handles outliers. Works for both conversion and numeric metrics.
                </p>
              </div>

              {/* Multi-Armed Bandit */}
              <div className="bg-gradient-to-br from-green-50 to-teal-50 p-8 rounded-2xl border border-green-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-green-600 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Multi-Armed Bandit</h3>
                <p className="text-gray-600 leading-relaxed">
                  Maximize conversions during experiments. Choose Thompson Sampling, UCB1, or Epsilon-Greedy. Background scheduler auto-reallocates traffic to winning variants.
                </p>
              </div>

              {/* Interaction Detection */}
              <div className="bg-gradient-to-br from-yellow-50 to-orange-50 p-8 rounded-2xl border border-yellow-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-yellow-600 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Interaction Detection</h3>
                <p className="text-gray-600 leading-relaxed">
                  Detect cross-experiment interference before it corrupts your results. Jaccard overlap analysis, chi-squared interaction tests, novelty effect detection, and SUTVA violation alerts.
                </p>
              </div>

              {/* AI Experiment Design */}
              <div className="bg-gradient-to-br from-indigo-50 to-blue-50 p-8 rounded-2xl border border-indigo-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-indigo-600 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">AI Experiment Design</h3>
                <p className="text-gray-600 leading-relaxed">
                  Claude API–powered hypothesis generation and design suggestions. MCP Server integrates with Claude Code, Cursor, and other coding assistants so your AI tools can design and interpret experiments.
                </p>
              </div>

              {/* Warehouse Analytics */}
              <div className="bg-gradient-to-br from-gray-50 to-slate-50 p-8 rounded-2xl border border-gray-100 hover:shadow-lg transition">
                <div className="w-12 h-12 bg-gray-700 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582 4-8 4" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Warehouse-Native Analytics</h3>
                <p className="text-gray-600 leading-relaxed">
                  Query experiment results directly in Snowflake, BigQuery, or Redshift. SQL-sanitized sync keeps your warehouse as the source of truth.
                </p>
              </div>
            </div>

            {/* Additional Features */}
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-6">Traffic Management & Governance</p>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
              {/* Mutual Exclusion */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-red-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Mutual Exclusion Groups</h3>
                <p className="text-gray-600 leading-relaxed">
                  Prevent experiment contamination using consistent-hashing traffic partitioning. Global holdout groups measure the cumulative impact of your entire experimentation program.
                </p>
              </div>

              {/* Dimensional Analysis */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-teal-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-teal-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Dimensional Analysis</h3>
                <p className="text-gray-600 leading-relaxed">
                  Break down results by device, country, plan, or any user attribute. Bonferroni-corrected per-segment analysis with heterogeneous treatment effect (HTE) detection.
                </p>
              </div>

              {/* Audit Logging & Compliance */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-gray-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Audit Logging &amp; Compliance</h3>
                <p className="text-gray-600 leading-relaxed">
                  HMAC-SHA256 signed tamper-proof audit trail with real-time SSE stream. SOC 2 Type II &amp; ISO 27001 compliance reports with CSV/JSON export. Custom RBAC roles and effective permissions resolution.
                </p>
              </div>
            </div>

            {/* SDK Ecosystem & Integrations */}
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-6 mt-16">SDK Ecosystem &amp; Integrations</p>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
              {/* Java SDK */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-red-100 rounded-xl flex items-center justify-center mb-6">
                  <span className="text-red-700 font-bold text-lg">☕</span>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Java SDK</h3>
                <p className="text-gray-600 leading-relaxed">
                  Native Java integration with Spring Boot auto-configuration starter. OkHttp client, LRU+TTL caching, and MD5-based consistent hash bucketing for stable variant assignment.
                </p>
              </div>

              {/* React SDK */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-cyan-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-cyan-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">React SDK</h3>
                <p className="text-gray-600 leading-relaxed">
                  React hooks and HOC — <code className="bg-gray-100 px-1 rounded text-sm">useFeatureFlag</code>, <code className="bg-gray-100 px-1 rounded text-sm">useExperiment</code>, <code className="bg-gray-100 px-1 rounded text-sm">useMultipleFlags</code>, and <code className="bg-gray-100 px-1 rounded text-sm">withExperimentation</code> HOC. SSR support via <code className="bg-gray-100 px-1 rounded text-sm">ServerClient</code> with no hydration mismatch.
                </p>
              </div>

              {/* Third-party Integrations */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Third-party Integrations</h3>
                <p className="text-gray-600 leading-relaxed">
                  Jira, Salesforce, and GitHub webhooks — sync experiment status, automatically create issues, and push results to your existing toolchain without leaving the platform.
                </p>
              </div>

              {/* Full Bayesian Statistics */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-violet-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-violet-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Full Bayesian Statistics</h3>
                <p className="text-gray-600 leading-relaxed">
                  Beta-Binomial posteriors, Monte Carlo PtBB simulations, Bayes Factor (BF10) via Savage-Dickey, credible intervals, and an automatic Bayesian stopping rule — alongside your frequentist analysis.
                </p>
              </div>

              {/* Split URL Testing */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-amber-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">Split URL Testing</h3>
                <p className="text-gray-600 leading-relaxed">
                  Server-side URL splitting via Lambda@Edge — no client-side JavaScript, works with any frontend framework. Persistent cookie-based assignment ensures a consistent experience across visits.
                </p>
              </div>

              {/* No-Code Experiment Builder */}
              <div className="bg-white p-8 rounded-2xl border border-gray-100 hover:shadow-lg hover:border-gray-200 transition">
                <div className="w-12 h-12 bg-emerald-100 rounded-xl flex items-center justify-center mb-6">
                  <svg className="w-6 h-6 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                </div>
                <h3 className="text-xl font-semibold text-gray-900 mb-3">No-Code Experiment Builder</h3>
                <p className="text-gray-600 leading-relaxed">
                  5-step guided wizard for experiment creation — define hypotheses, set variants, choose metrics, configure targeting, and launch — all without writing a line of code.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Integration Section */}
        <section className="py-24 px-6 bg-gray-50 border-t border-gray-100">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
                Works with your stack
              </h2>
              <p className="text-lg text-gray-600">
                Seamlessly integrate with the tools you already use
              </p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">AWS</div>
                <div className="text-sm text-gray-500">Cloud Infrastructure</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Snowflake</div>
                <div className="text-sm text-gray-500">Data Warehouse</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">BigQuery</div>
                <div className="text-sm text-gray-500">Data Warehouse</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Redshift</div>
                <div className="text-sm text-gray-500">Data Warehouse</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Segment</div>
                <div className="text-sm text-gray-500">CDP Integration</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Slack</div>
                <div className="text-sm text-gray-500">Notifications</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">SendGrid</div>
                <div className="text-sm text-gray-500">Email Alerts</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Claude</div>
                <div className="text-sm text-gray-500">AI Design via MCP</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Jira</div>
                <div className="text-sm text-gray-500">Issue Sync</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">Salesforce</div>
                <div className="text-sm text-gray-500">CRM Integration</div>
              </div>
              <div className="bg-white p-8 rounded-xl border border-gray-200 text-center">
                <div className="text-2xl font-bold text-gray-400 mb-2">GitHub</div>
                <div className="text-sm text-gray-500">Webhook &amp; Issues</div>
              </div>
            </div>
          </div>
        </section>

        {/* Code Example Section */}
        <section className="py-24 px-6">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-12">
              <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
                Simple to integrate
              </h2>
              <p className="text-lg text-gray-600">
                Get started in minutes — SDKs for Python, JavaScript, Java, and React
              </p>
              <div className="flex flex-wrap justify-center gap-2 mt-4">
                {['JavaScript', 'Python', 'Java', 'React'].map((lang) => (
                  <span key={lang} className="bg-gray-100 text-gray-700 px-3 py-1 rounded-full text-sm font-medium">{lang}</span>
                ))}
              </div>
            </div>
            <div className="grid md:grid-cols-2 gap-6">
              {/* JavaScript */}
              <div className="bg-gray-900 rounded-2xl p-6 overflow-hidden">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-red-500"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  <span className="ml-2 text-xs text-gray-400 font-mono">JavaScript</span>
                </div>
                <pre className="text-sm text-gray-300 overflow-x-auto">
                  <code>{`import { Experimently } from '@experimently/sdk';

const client = new Experimently('YOUR_API_KEY');

// Get variant + track conversion
const variant = await client.getVariant(
  'checkout-redesign', userId
);

client.track('purchase_completed', userId, {
  revenue: 99.99
});

// Feature flag with targeting
const isEnabled = await client.isEnabled(
  'new-checkout', userId,
  { country: 'US', plan: 'enterprise' }
);`}</code>
                </pre>
              </div>

              {/* Java */}
              <div className="bg-gray-900 rounded-2xl p-6 overflow-hidden">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-red-500"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  <span className="ml-2 text-xs text-gray-400 font-mono">Java (Spring Boot)</span>
                </div>
                <pre className="text-sm text-gray-300 overflow-x-auto">
                  <code>{`// application.properties
experimently.api-key=YOUR_API_KEY
experimently.cache.ttl-seconds=60

// Auto-configured via Spring starter
@Autowired
ExperimentlyClient client;

String variant = client.getVariant(
    "checkout-redesign", userId
);

boolean enabled = client.isEnabled(
    "new-checkout", userId,
    Map.of("country", "US", "plan", "enterprise")
);`}</code>
                </pre>
              </div>

              {/* React */}
              <div className="bg-gray-900 rounded-2xl p-6 overflow-hidden">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-red-500"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  <span className="ml-2 text-xs text-gray-400 font-mono">React</span>
                </div>
                <pre className="text-sm text-gray-300 overflow-x-auto">
                  <code>{`import {
  ExperimentlyProvider,
  useFeatureFlag,
  useVariant,
} from '@experimently/react';

// Wrap your app
<ExperimentlyProvider apiKey="YOUR_API_KEY">
  <App />
</ExperimentlyProvider>

// Use in any component
function Checkout() {
  const variant = useVariant('checkout-redesign');
  const isNewUi = useFeatureFlag('new-checkout');

  return isNewUi ? <NewFlow /> : <OldFlow />;
}`}</code>
                </pre>
              </div>

              {/* Python */}
              <div className="bg-gray-900 rounded-2xl p-6 overflow-hidden">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-3 h-3 rounded-full bg-red-500"></div>
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <div className="w-3 h-3 rounded-full bg-green-500"></div>
                  <span className="ml-2 text-xs text-gray-400 font-mono">Python</span>
                </div>
                <pre className="text-sm text-gray-300 overflow-x-auto">
                  <code>{`from experimently import ExperimentlyClient

client = ExperimentlyClient(api_key="YOUR_API_KEY")

# Get experiment variant
variant = client.get_variant(
    "checkout-redesign", user_id
)

# Track conversion
client.track("purchase_completed", user_id,
    properties={"revenue": 99.99})

# Feature flag with targeting
enabled = client.is_enabled(
    "new-checkout", user_id,
    context={"country": "US", "plan": "enterprise"}
)`}</code>
                </pre>
              </div>
            </div>
          </div>
        </section>

        {/* Competitor Comparison Section */}
        <section id="compare" className="py-24 px-6 bg-gray-50 border-t border-gray-100">
          <div className="max-w-7xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-4xl md:text-5xl font-bold text-gray-900 mb-4">
                How we compare
              </h2>
              <p className="text-xl text-gray-600 max-w-3xl mx-auto">
                Enterprise-grade statistical methods at every tier — without the enterprise price tag
              </p>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b-2 border-gray-200">
                    <th className="text-left py-4 px-4 font-semibold text-gray-700 w-64">Feature</th>
                    <th className="text-center py-4 px-4 font-bold text-blue-600 bg-blue-50 rounded-t-lg">Experimently</th>
                    <th className="text-center py-4 px-4 font-semibold text-gray-600">Optimizely</th>
                    <th className="text-center py-4 px-4 font-semibold text-gray-600">Statsig*</th>
                    <th className="text-center py-4 px-4 font-semibold text-gray-600">Amplitude</th>
                    <th className="text-center py-4 px-4 font-semibold text-gray-600">LaunchDarkly</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {[
                    ['A/B / Multivariate Testing', '✅', '✅', '✅', '✅', '⚠️ Add-on'],
                    ['Feature Flags', '✅', '✅', '✅', '✅', '✅'],
                    ['Sequential Testing (mSPRT)', '✅', '✅', '✅', '✅', '❌'],
                    ['CUPED Variance Reduction', '✅ (binary + numeric)', '⚠️ Numeric only', '✅', '✅', '⚠️ Add-on'],
                    ['Multi-Armed Bandit', '✅ (3 algorithms)', '✅', '✅', '✅', '❌'],
                    ['Full Bayesian (BF10 + Monte Carlo)', '✅', '❌', '⚠️ Partial', '❌', '❌'],
                    ['Split URL Testing (Lambda@Edge)', '✅', '✅', '❌', '❌', '❌'],
                    ['Interaction Detection', '✅', '⚠️ Partial', '❌', '❌', '❌'],
                    ['Mutual Exclusion Groups', '✅', '⚠️ Partial', '✅', '⚠️ Partial', '❌'],
                    ['Global Holdout Group', '✅', '✅', '⚠️', '❌', '❌'],
                    ['Dimensional Analysis', '✅ + Bonferroni', '⚠️ Partial', '✅', '⚠️ Partial', '❌'],
                    ['No-Code Experiment Wizard', '✅', '✅', '⚠️', '✅ (Web)', '❌'],
                    ['AI Experiment Design', '✅ (Claude + MCP)', '✅ (Opal AI)', '❌', '❌', '❌'],
                    ['Warehouse Analytics', '✅ (3 warehouses)', '✅', '✅', '✅ (Snowflake)', '❌'],
                    ['Jira / Salesforce / GitHub Integration', '✅', '⚠️ Partial', '❌', '❌', '⚠️ Partial'],
                    ['Java SDK', '✅ (Spring Boot starter)', '✅', '✅', '⚠️', '✅'],
                    ['React SDK (hooks + SSR)', '✅', '✅', '✅', '⚠️', '✅'],
                    ['SOC 2 / ISO 27001 Compliance Export', '✅ (HMAC-signed)', '✅', '⚠️ Enterprise', '⚠️ Enterprise', '✅'],
                    ['Audit Log + SSE Stream', '✅', '⚠️', '⚠️', '❌', '✅'],
                    ['Deploy in Your AWS Account', '✅', '❌', '❌', '❌', '❌'],
                    ['Pricing (entry)', '🎉 Free Preview', '$36K+/year', 'Free → $150+/mo', 'Free → Custom', 'Free → $20K+/year'],
                  ].map(([feature, ...cols], i) => (
                    <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                      <td className="py-3.5 px-4 font-medium text-gray-700">{feature}</td>
                      <td className="py-3.5 px-4 text-center bg-blue-50 font-medium text-gray-900">{cols[0]}</td>
                      <td className="py-3.5 px-4 text-center text-gray-600">{cols[1]}</td>
                      <td className="py-3.5 px-4 text-center text-gray-600">{cols[2]}</td>
                      <td className="py-3.5 px-4 text-center text-gray-600">{cols[3]}</td>
                      <td className="py-3.5 px-4 text-center text-gray-600">{cols[4]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-gray-400 mt-4 text-center">
              * Statsig acquired by OpenAI for $1.1B in September 2025. Future roadmap subject to change. ⚠️ = Partial or enterprise-only feature.
            </p>
            <div className="text-center mt-8">
              <a href="#compare" className="text-blue-600 hover:text-blue-700 text-sm font-medium">
                View full detailed comparison →
              </a>
            </div>
          </div>
        </section>

        {/* Pricing Section */}
        <section id="pricing" className="py-24 px-6 bg-white border-t border-gray-100">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-4xl md:text-5xl font-bold text-gray-900 mb-4">
                Simple, transparent pricing
              </h2>
              <p className="text-xl text-gray-600">
                Start free with everything included. Enterprise pricing coming soon.
              </p>
            </div>

            <div className="grid md:grid-cols-2 gap-8 max-w-3xl mx-auto">
              {/* Free Preview */}
              <div className="bg-white rounded-2xl border-2 border-blue-600 p-8 relative shadow-xl">
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-blue-600 text-white px-4 py-1 rounded-full text-sm font-semibold">
                  Available Now
                </div>
                <div className="mb-8">
                  <h3 className="text-2xl font-bold text-gray-900 mb-2">Free Preview</h3>
                  <p className="text-gray-600 mb-6">All features included during preview</p>
                  <div className="flex items-baseline">
                    <span className="text-5xl font-bold text-gray-900">$0</span>
                    <span className="text-gray-600 ml-2">/month</span>
                  </div>
                </div>
                <ul className="space-y-4 mb-8">
                  {[
                    'Unlimited A/B experiments',
                    'Feature flags with staged rollouts',
                    'Sequential testing (mSPRT)',
                    'CUPED variance reduction',
                    'Multi-armed bandit (3 algorithms)',
                    'Full Bayesian (BF10, Monte Carlo, credible intervals)',
                    'Split URL testing via Lambda@Edge',
                    'Interaction detection',
                    'Mutual exclusion groups',
                    'AI experiment design (Claude API)',
                    'Warehouse analytics (Snowflake, BigQuery, Redshift)',
                    'Java SDK + Spring Boot starter',
                    'React SDK (hooks, HOC, SSR)',
                    'Jira, Salesforce & GitHub integrations',
                    'SOC 2 / ISO 27001 compliance reports (HMAC-signed)',
                    'Full audit log + SSE stream',
                    'Custom RBAC roles',
                    'Slack + email alerting',
                  ].map((item, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <svg className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      <span className="text-gray-700">{item}</span>
                    </li>
                  ))}
                </ul>
                <a href="https://app.getexperimently.com/signup" className="block w-full text-center bg-blue-600 text-white px-6 py-3.5 rounded-lg font-semibold hover:bg-blue-700 transition shadow-sm">
                  Start for free
                </a>
              </div>

              {/* Enterprise */}
              <div className="bg-white rounded-2xl border-2 border-gray-200 p-8">
                <div className="mb-8">
                  <h3 className="text-2xl font-bold text-gray-900 mb-2">Enterprise</h3>
                  <p className="text-gray-600 mb-6">Commercial pricing — coming soon</p>
                  <div className="flex items-baseline">
                    <span className="text-4xl font-bold text-gray-900">TBD</span>
                  </div>
                </div>
                <ul className="space-y-4 mb-8">
                  {[
                    'Everything in Free Preview',
                    'Deploy to your own AWS account',
                    'Data stays in your infrastructure',
                    'SOC 2 / ISO 27001 compliance',
                    'HIPAA BAA available',
                    'Dedicated support + SLA',
                    'Custom contracts',
                    'Volume pricing',
                  ].map((item, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <svg className="w-5 h-5 text-gray-400 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                      </svg>
                      <span className="text-gray-700">{item}</span>
                    </li>
                  ))}
                </ul>
                <a href="mailto:hello@getexperimently.com" className="block w-full text-center bg-gray-100 text-gray-900 px-6 py-3.5 rounded-lg font-semibold hover:bg-gray-200 transition">
                  Contact us
                </a>
              </div>
            </div>

            <div className="text-center mt-10 p-6 bg-blue-50 rounded-2xl max-w-3xl mx-auto">
              <p className="text-blue-800 font-medium">
                🎉 We&apos;re in Free Preview — all enterprise features are available at no cost while we finalize commercial pricing. Lock in early access by signing up now.
              </p>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section className="py-24 px-6 bg-gradient-to-br from-blue-600 to-indigo-700">
          <div className="max-w-4xl mx-auto text-center">
            <h2 className="text-4xl md:text-5xl font-bold text-white mb-6">
              Start experimenting today
            </h2>
            <p className="text-xl text-blue-100 mb-10">
              Sequential testing, CUPED, Bayesian stats, Java/React/JS SDKs, and AI design — all free during preview. No credit card needed.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a href="https://app.getexperimently.com/signup" className="bg-white text-blue-600 px-8 py-4 rounded-lg text-lg font-semibold hover:bg-gray-50 transition shadow-lg">
                Start free — all features included
              </a>
              <a href="mailto:hello@getexperimently.com" className="bg-blue-700 text-white px-8 py-4 rounded-lg text-lg font-semibold hover:bg-blue-800 transition border-2 border-blue-500">
                Talk to the team
              </a>
            </div>
            <p className="text-blue-100 mt-6">Free Preview · No credit card required · All features unlocked</p>
          </div>
        </section>

        {/* Footer */}
        <footer className="bg-gray-900 text-white py-16 px-6">
          <div className="max-w-7xl mx-auto">
            <div className="grid md:grid-cols-6 gap-12 mb-12">
              <div className="md:col-span-2">
                <span className="text-2xl font-semibold text-white mb-4 block">
                  Experimently
                </span>
                <p className="text-gray-400 mb-6 max-w-sm">
                  The modern product experimentation platform with enterprise-grade statistics at every tier.
                </p>
                <div className="flex gap-4">
                  <a href="#" className="text-gray-400 hover:text-white transition">
                    <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M24 4.557c-.883.392-1.832.656-2.828.775 1.017-.609 1.798-1.574 2.165-2.724-.951.564-2.005.974-3.127 1.195-.897-.957-2.178-1.555-3.594-1.555-3.179 0-5.515 2.966-4.797 6.045-4.091-.205-7.719-2.165-10.148-5.144-1.29 2.213-.669 5.108 1.523 6.574-.806-.026-1.566-.247-2.229-.616-.054 2.281 1.581 4.415 3.949 4.89-.693.188-1.452.232-2.224.084.626 1.956 2.444 3.379 4.6 3.419-2.07 1.623-4.678 2.348-7.29 2.04 2.179 1.397 4.768 2.212 7.548 2.212 9.142 0 14.307-7.721 13.995-14.646.962-.695 1.797-1.562 2.457-2.549z" /></svg>
                  </a>
                  <a href="#" className="text-gray-400 hover:text-white transition">
                    <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
                  </a>
                  <a href="#" className="text-gray-400 hover:text-white transition">
                    <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" /></svg>
                  </a>
                </div>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-4">Documentation</h4>
                <ul className="space-y-3 text-gray-400">
                  <li><a href="/docs" className="hover:text-white transition">Docs Home</a></li>
                  <li><a href="/docs/quick-start" className="hover:text-white transition">Quick Start</a></li>
                  <li><a href="/docs/api-reference/endpoints" className="hover:text-white transition">API Reference</a></li>
                  <li><a href="/docs/integrations/warehouses" className="hover:text-white transition">Integrations</a></li>
                  <li><a href="/docs/security/soc2" className="hover:text-white transition">Security &amp; Compliance</a></li>
                  <li><a href="/docs/self-hosting/cdk" className="hover:text-white transition">Self-Hosting</a></li>
                  <li><a href="/docs/changelog" className="hover:text-white transition">Changelog</a></li>
                </ul>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-4">Developers</h4>
                <ul className="space-y-3 text-gray-400">
                  <li><a href="/docs/sdks/javascript" className="hover:text-white transition">JavaScript SDK</a></li>
                  <li><a href="/docs/sdks/python" className="hover:text-white transition">Python SDK</a></li>
                  <li><a href="/docs/sdks/java" className="hover:text-white transition">Java SDK</a></li>
                  <li><a href="/docs/sdks/react" className="hover:text-white transition">React SDK</a></li>
                  <li><a href="/docs/sdks/mcp" className="hover:text-white transition">MCP Server</a></li>
                </ul>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-4">Company</h4>
                <ul className="space-y-3 text-gray-400">
                  <li><a href="#about" className="hover:text-white transition">About</a></li>
                  <li><a href="mailto:hello@getexperimently.com" className="hover:text-white transition">Contact</a></li>
                  <li><a href="#" className="hover:text-white transition">Careers</a></li>
                  <li><a href="#" className="hover:text-white transition">Blog</a></li>
                </ul>
              </div>

              <div>
                <h4 className="font-semibold text-white mb-4">Legal</h4>
                <ul className="space-y-3 text-gray-400">
                  <li><a href="#" className="hover:text-white transition">Privacy</a></li>
                  <li><a href="#" className="hover:text-white transition">Terms</a></li>
                  <li><a href="#" className="hover:text-white transition">Security</a></li>
                  <li><a href="mailto:support@getexperimently.com" className="hover:text-white transition">Support</a></li>
                </ul>
              </div>
            </div>

            <div className="border-t border-gray-800 pt-8">
              <div className="flex flex-col md:flex-row justify-between items-center gap-4">
                <p className="text-gray-400 text-sm">
                  © 2026 Experimently. All rights reserved.
                </p>
                <p className="text-gray-500 text-sm">
                  Built with ❤️ for modern product teams
                </p>
              </div>
            </div>
          </div>
        </footer>
      </div>
    </>
  );
}

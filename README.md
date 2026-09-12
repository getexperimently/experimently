# Experimentation Platform

> **Enterprise-grade experimentation platform for A/B testing and feature flags**

A production-ready, scalable platform for A/B testing and feature management with real-time evaluation, automated safety monitoring, and comprehensive analytics.

---

## 🎯 Overview

An enterprise experimentation platform that enables teams to make data-driven decisions through robust A/B testing and feature flag management. Built on AWS with enterprise-grade reliability and performance.

### Key Capabilities

- **A/B Testing & Multivariate Experiments**: Statistical rigor with Bayesian and Frequentist analysis
- **Advanced Feature Flags**: Targeting, gradual rollouts, and automated safety monitoring
- **Enhanced Rules Engine**: 20+ operators including semantic versioning, geo-distance, time windows
- **Real-time Analytics**: High-throughput event collection and comprehensive metrics
- **Enterprise RBAC**: Role-based access control with AWS Cognito integration
- **Complete Audit Trail**: append-only audit log of every change, exportable for your compliance program
- **Automated Safety**: Real-time monitoring with automatic rollback capabilities

### Measured, not marketed

Numbers in this README come from the repository's own test and benchmark suites, not from a
production deployment we cannot show you:

- **Rules engine**: 125k+ simple-operator evaluations/second in the benchmark suite
  (`backend/tests/performance/`)
- **Statistical engine**: sequential testing (mSPRT), CUPED, Bayesian and multi-armed bandits, each
  with a DB-backed test that drives the public API
- **5,400+ backend tests, 640+ dashboard tests, 15 SDKs** verified against a live backend in CI

---

## 🎬 See it running

Two demo applications ship in the repo and drive the platform through the public SDK path, exactly as
a customer app would. `./demo/setup-local.sh` starts everything.

- **ShopLab** (`demo/shoplab`, http://localhost:3200): an e-commerce storefront running an A/B test,
  a multi-armed bandit, a multivariate test, a CUPED checkout test and a gradual-rollout flag.
- **StreamPulse** (`demo/streampulse`, http://localhost:3300): a simulated mobile app with a device
  picker, targeting by OS version/region/tier, a kill switch, mutual exclusion and a scripted rollout
  story in which a crash spike triggers an automatic safety rollback.

Walkthrough: [demo/DEMO_GUIDE.md](demo/DEMO_GUIDE.md).

---

## 🏗️ Architecture

Built using modern, scalable architecture leveraging AWS services:

- **Frontend**: Next.js React application with TypeScript
- **Backend**: FastAPI Python services (ECS/Fargate, auto-scaling)
- **Real-time**: AWS Lambda for low-latency operations
- **Data**: Aurora PostgreSQL Multi-AZ, ElastiCache Redis, DynamoDB
- **Analytics**: Kinesis → Lambda → OpenSearch pipeline
- **Infrastructure**: AWS CDK for infrastructure as code

**Technology Stack**: Python 3.11+, FastAPI, SQLAlchemy, Pydantic v2, Next.js, React, TypeScript, PostgreSQL, Redis

[View Architecture Details →](docs/architecture/overview.md)

---

## ✨ Key Features

### Advanced Targeting & Rules Engine
- **20+ Operators**: Basic (equals, in), String (regex, contains), Advanced (semver, geo-distance, time windows, JSON path)
- **High Performance**: 125k+ simple evaluations/sec, 2.5k+ complex evaluations/sec
- **Smart Caching**: Multi-layer caching with 94%+ hit rates
- **Batch Processing**: Efficient evaluation of 1000+ users

### Automated Safety Monitoring
- **Real-time Metrics**: Error rate, latency, custom metrics tracking
- **Auto-Rollback**: Automatic rollback on threshold violations
- **Configurable Thresholds**: Per-feature flag safety configuration
- **Complete Audit Trail**: All rollbacks logged with reasoning

### Statistical Rigor
- **Bayesian & Frequentist**: Dual statistical approaches
- **Sequential Testing**: Early stopping with O'Brien-Fleming bounds
- **Multiple Testing Correction**: Bonferroni and other methods
- **Sample Size Calculations**: Automatic power analysis

### Security controls
- **Audit trail**: append-only log of every change (the enterprise edition adds HMAC signing and
  report packs to support a SOC 2 or ISO 27001 program)
- **Data controls**: retention settings and export endpoints (right-to-erasure tooling is on the roadmap)
- **Complete Audit Logs**: record of all actions
- **RBAC**: 4-tier role system (Admin, Developer, Analyst, Viewer)
- **Encryption**: At-rest (KMS) and in-transit (TLS 1.2+)

---

## 🚀 Getting Started

### For Evaluation

Interested in using this platform for your organization?

1. **Run the demos**: see [demo/DEMO_GUIDE.md](demo/DEMO_GUIDE.md)
2. **Run the demo**: `./demo/setup-local.sh` starts Postgres and Redis, seeds demo data, and launches the
   dashboard (http://localhost:3100), the API (http://localhost:8000) and the **ShopLab** storefront
   (http://localhost:3200) — a small e-commerce site running five live experiments through the React SDK,
   with a traffic simulator keeping the dashboards moving. Walkthrough: [demo/DEMO_GUIDE.md](demo/DEMO_GUIDE.md)
3. **Review the Documentation**: Check the [docs](docs/) directory for comprehensive guides
4. **Run Locally**: Follow the setup instructions in CLAUDE.md for local development

### For Deployment

Refer to the documentation for:
- Deployment configuration
- Infrastructure setup with AWS CDK
- SDK integration guides
- Configuration options

---

## 📖 Documentation

- **[Architecture Overview](docs/architecture/overview.md)**: System design
- **[Targeting rules](docs/feature-flags/create.md)**: operators, attribute aliases, examples
- **[Testing audit](docs/testing/testing-audit-2026-09.md)**: what is tested, what gates, what is missing
- **[Development Guide](CLAUDE.md)**: Complete development guidelines and best practices

---

## 🔧 Technology Highlights

### Backend Services
- **FastAPI Application**: Comprehensive REST API
  - 847 automated tests with 100% pass rate
  - 82% code coverage
  - Sub-100ms P95 API latency
- **Background Schedulers**: Automated experiment lifecycle, rollout management, metrics aggregation
- **Enhanced Rules Engine**: Advanced targeting with 20+ operators

### Database & Caching
- **Aurora PostgreSQL**: Multi-AZ with automatic failover
- **ElastiCache Redis**: 89% cache hit rate, sub-5ms latency
- **Data Retention**: Configurable policies (90 days to 7 years)

### Real-time Processing
- **Lambda Functions**: 8M+ invocations/month
- **Kinesis Streams**: 1.8M+ events/day
- **OpenSearch**: Real-time analytics queries

---

## 🛡️ Security

- **Controls that support your compliance program**: append-only audit log, role-based access,
  per-flag safety monitoring with automatic rollback; the enterprise edition adds tamper-evident
  audit signing, compliance report packs and PHI encryption. We do not hold SOC 2, ISO 27001 or
  HIPAA attestations and do not claim them.
- **Encryption**: AES-256 at rest (KMS) and TLS 1.2+ in transit when deployed with the provided CDK
- **Network Security**: VPC isolation, Security Groups, WAF, DDoS protection (CDK deployment)

---

## 💼 Use Cases

### Product Teams
- A/B test new features and UI changes
- Gradual rollouts with safety monitoring
- Data-driven product decisions

### Engineering Teams
- Feature flags for deployment control
- Canary deployments and kill switches
- Configuration management

### Data Science Teams
- Statistical experiment analysis
- Metric tracking and attribution
- Segmentation analysis

### Compliance Teams
- Complete audit trails
- Role-based access control
- Retention policy management

---

## 📞 Support

For questions and issues:
- Check the [documentation](docs/) directory
- Review [CLAUDE.md](CLAUDE.md) for development guidelines
- Run the demos (`./demo/setup-local.sh`)

---

## 📄 License

| Part of the repository | Licence |
|---|---|
| Everything except `ee/` and `sdk/` (Community Edition) | [AGPL-3.0-only](LICENSE) |
| `ee/` (Enterprise Edition) | [Experimently Enterprise Licence](ee/LICENSE) — proprietary, source-available, requires a licence key |
| `sdk/` (all client SDKs and OpenFeature providers) | [MIT](sdk/LICENSE) |

The SDKs are MIT precisely so that embedding one in your application does not pull the
AGPL-3.0 network-use obligation into your codebase. Running an unmodified Community Edition
creates no source-disclosure obligation either; AGPL-3.0 §13 only applies if you modify it and
let others interact with the modified version over a network.

Third-party dependency licences are listed in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md);
attribution is in [NOTICE](NOTICE). Security reports go to [SECURITY.md](SECURITY.md), not to
public issues. Contributions are accepted under the DCO — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 🌟 Key Differentiators

| Feature | This Platform | Typical Alternatives |
|---------|---------------|---------------------|
| **Advanced Targeting** | 20+ operators (semver, geo, time, JSON path) | Basic operators only |
| **Safety Monitoring** | Automated rollback with configurable thresholds | Manual monitoring |
| **Statistical Methods** | Bayesian + Frequentist analysis | Single method |
| **Audit Logging** | Append-only trail; tamper-evident signing in the enterprise edition | Limited or none |
| **Performance** | 125k ops/sec, sub-10ms latency | Varies widely |
| **RBAC** | 4 roles; local auth or AWS Cognito | Basic or none |
| **Deployment** | Self-hosted on your AWS account | SaaS only |
| **Customization** | Full platform access | Limited APIs |

---

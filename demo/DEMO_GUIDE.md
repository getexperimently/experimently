# Experimently — Client Demo Guide

## Overview

This guide walks you through a 20-minute live demo of the Experimently experimentation platform. The demo environment comes pre-loaded with 100K+ historical events and a live simulator streaming new events in the background so charts update in real time during the presentation.

---

## Setup

### Local (recommended, ~2 min)

```bash
./demo/setup-local.sh
```

When complete, you'll see the "Ready!" box with URLs and credentials.

### AWS (15–20 min for first deploy)

```bash
./demo/setup-aws.sh
```

Teardown: `./demo/setup-aws.sh --destroy`

---

## Credentials

| Role      | Email              | Password   |
|-----------|--------------------|------------|
| Admin     | admin@demo.com     | Demo1234!  |
| Developer | dev@demo.com       | Demo1234!  |
| Analyst   | analyst@demo.com   | Demo1234!  |
| Viewer    | viewer@demo.com    | Demo1234!  |

---

## 20-Minute Demo Walkthrough

### Scene 0 — ShopLab storefront: experiments in a real app (4 min)

ShopLab is a small e-commerce site (`demo/shoplab`, http://localhost:3200) that runs five live experiments through the
React SDK and the public tracking API — the same path a customer's app would use. `setup-local.sh` seeds it, starts it,
and runs a traffic simulator against it so the dashboards fill up while you talk.

**What to show:**
- Open http://localhost:3200 — point at the **Experimently panel** (bottom-right): the visitor id, the variant this visitor
  got for each experiment, and the two feature flags.
  - "This is a real storefront calling our API with an API key. Every visitor is bucketed server-side, sticky, in one call."
- Click **Shop the collection** (or **Watch & shop** if you got the video hero) → the panel logs `hero_cta_click`
  - "That click just became a conversion for the hero experiment. Nothing else to wire up."
- On **/products** change nothing — explain the sort order is a **multi-armed bandit** (`shoplab_plp_sort`): Thompson Sampling
  moves traffic toward the algorithm with the best click rate. Click a product.
- On the product page the **buy button** is one of four multivariate treatments (`shoplab_pdp_buy_button`). Add to cart.
- **/checkout** is a 3-step vs one-page A/B test with CUPED enabled. Place the order → `purchase` with the order value.
- **/search** shows a gradual-rollout flag (`shoplab_new_search`, 10% → 50% → 100%) — press **New visitor** in the panel a
  few times to land in the 10% and see the "New search ✨" engine.
- Switch to the dashboard (http://localhost:3100/experiments): open **shoplab_hero_banner** — results are moving because
  the simulator is streaming visitors through the same API.

**Key talking points:**
- One SDK call per experiment, one call per event; no client-side bucketing to keep consistent
- Bandit, multivariate, sequential, CUPED and Bayesian all running on the same storefront at once
- Gradual rollout + kill switch (`shoplab_free_shipping_banner`) without a deploy

Run pieces by hand: `python backend/scripts/seed_shoplab.py` (seeds experiments, flags, API key, 14 days of history),
`cd demo/shoplab && npm run dev`, `python demo/shoplab/simulator/traffic.py --rate 3`. See `demo/shoplab/README.md`.

---

### Scene 1 — Feature Flags (3 min)

**What to show:**
- Navigate to `/feature-flags`
- Click **new_dashboard_ui** — show it's at 50% rollout with a 3-stage schedule
  - "We started at 10%, expanded to 25%, and now we're at 50%. The schedule automates this — zero manual work."
  - Point to the safety config: "If the error rate exceeds 5%, it auto-rolls back. We never break production."
- Click **beta_features** — show the targeting rule
  - "This uses our 20+ targeting operators. Users with role 'beta' or 'internal', OR an @acme.com email, get this flag. Everyone else doesn't see it."
- Toggle `beta_features` off and back on
  - "That change is live in milliseconds — no deploy needed."

**Key talking points:**
- Gradual rollouts with automated progression
- Advanced targeting (20+ operators: semver, geo, array, time windows)
- Safety monitoring with automatic rollback

---

### Scene 2 — Running A/B Test (4 min)

**What to show:**
- Navigate to `/experiments` → click **Checkout Button Color**
- Show: Status ACTIVE, 2 variants (blue 50% / green 50%), metric: checkout_completed
  - "This test has been running for 14 days. We've pre-seeded 30K historical events."
- Watch the results panel — numbers are ticking up
  - "These are updating right now. The live simulator is streaming ~3 events/second to both variants."
- Show the time-series chart — you can see the trend building
  - "Green is trending at 11% vs blue at 8%, but we don't have statistical significance yet. The platform tells us when we do."

**Key talking points:**
- Live data, not screenshots — the platform is actually running
- Consistent hash-based assignment (same user always gets same variant)
- Real-time results vs polling dashboards

---

### Scene 3 — Statistical Results (5 min)

**What to show:**
- Navigate to `/experiments` → click **Homepage Hero Copy Test**
- Status: COMPLETED — this experiment ran for 35 days with 50K events
- Show the results panel:
  - p-value < 0.001 — highly significant
  - 12% relative lift in signup conversion (7.5% → 8.4%)
  - Confidence interval doesn't cross zero
  - "The platform made the decision: Ship It. No analyst needed to interpret this."
- Click the **CUPED** tab
  - "CUPED reduces variance by 20–40% using pre-experiment data. That means we reach significance with fewer users and can ship faster."
- Click the **Sequential Testing** tab
  - "mSPRT lets us peek at results without inflating false positives. No more waiting for a fixed sample size."
- Show the **Bayesian** probability of superiority
  - "98.7% probability that new_copy is better. For decision-makers who don't speak p-values."

**Key talking points:**
- Multiple statistical methods in one platform (frequentist + Bayesian + sequential)
- CUPED for variance reduction
- Platform-generated decision ("Ship It") — removes analyst bottleneck

---

### Scene 4 — Multi-Armed Bandit (3 min)

**What to show:**
- Navigate to `/experiments` → click **Recommendation Algorithm MAB**
- Show: 3 variants (algo_v1, v2, v3), Thompson Sampling, ACTIVE
- Show the traffic allocation chart — algo_v2 is getting more traffic
  - "This started at 33/33/34%. Thompson Sampling has noticed v2 performs better (9% click rate vs 5–6%) and is routing more traffic there automatically."
  - "No one made that decision. The algorithm did."
- Watch the live updates — traffic percentages shifting
  - "While we're talking, the platform is learning and reallocating."

**Key talking points:**
- MAB for optimization problems where you can't wait for a winner
- Thompson Sampling, UCB1, Epsilon-Greedy all supported
- Automatic traffic reallocation — maximize conversions during the experiment

---

### Scene 5 — Enterprise / Admin (5 min)

**What to show:**

**Audit Trail:**
- Navigate to `/admin/audit`
- Show: HMAC-SHA256 signed entries — "Every action is tamper-proof. If someone changes a row, the signature breaks."
- Show the log: user logins, experiment starts, flag toggles, RBAC changes
  - "For SOC 2, you need a complete, verifiable audit trail. This is built in."
- Show compliance report export: `/api/v1/compliance/report` → downloads CSV/JSON

**RBAC:**
- Navigate to `/admin/users`
- Show 4 roles: Admin, Developer, Analyst, Viewer
  - "Analyst can view everything but can't create or modify. Viewer is read-only."
- Show **ReadOnlyAnalyst** custom role
  - "You can create custom roles. ReadOnlyAnalyst has read access to experiments and results but nothing else."
- "You can grant permissions at the resource level too — this person can manage feature flags but not experiments."

**API / Integrations:**
- Navigate to `/api/v1/docs` (Swagger UI)
  - "Full REST API. Your team can automate everything — CI/CD triggers experiments, Slack gets notified when tests complete, Jira tickets auto-close."
- Show the Jira integration config
  - "Point this at your Jira instance and experiment completions automatically update tickets."

**Key talking points:**
- SOC 2 / ISO 27001 ready — HMAC audit trail, compliance reports
- RBAC with custom roles and resource-level grants
- Full REST API + SDKs (Python, JavaScript, Java, React, Go)
- Deployable to your AWS account — you own the data, it never leaves your VPC

---

## FAQ / Objections

**"Can it connect to our data warehouse?"**
> Yes. Snowflake, BigQuery, and Redshift are all supported via the warehouse-native analytics feature. You can query your existing event data without moving it.

**"Is it SOC 2 compliant?"**
> The audit logging system uses HMAC-SHA256 signing (EP-033). Every action is cryptographically signed and the system can export SOC 2 and ISO 27001 compliance reports on demand.

**"What about our tech stack?"**
> We have SDKs for Python, JavaScript/TypeScript, Java (Spring Boot auto-configuration), and React (with hooks and SSR support). The REST API means you can integrate from anything.

**"How do we deploy? What's the infrastructure cost?"**
> One command: `./demo/setup-aws.sh`. It uses CDK to deploy into your AWS account — ECS Fargate, Aurora PostgreSQL, ElastiCache Redis. You own all the infrastructure. The demo environment runs on t3.small instances (~$50/month).

**"Can we run A/B tests across multiple products simultaneously?"**
> Yes. Mutual Exclusion Groups ensure users are never in conflicting experiments. The Global Holdout group lets you measure the cumulative impact of all experiments combined.

**"What if an experiment goes wrong?"**
> Safety monitoring watches error rates and latency in real time. If a feature flag causes problems, it auto-rolls back. For experiments, you can pause or stop at any time.

---

## Quick Reference URLs

| Page | URL |
|------|-----|
| ShopLab storefront | http://localhost:3200 |
| Home | http://localhost:3000 |
| Feature Flags | http://localhost:3000/feature-flags |
| Experiments | http://localhost:3000/experiments |
| Results (Hero) | http://localhost:3000/results/homepage_hero_copy |
| MAB | http://localhost:3000/experiments/recommendation_algorithm |
| Audit | http://localhost:3000/admin/audit |
| Users/RBAC | http://localhost:3000/admin/users |
| API Docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

---

## Stopping the Demo

```bash
./demo/teardown-local.sh
```

This stops all processes, shuts down Docker, and removes temporary files.

---

## Logs

```bash
# Live backend logs
tail -f demo/.logs/backend.log

# Live simulator stats
tail -f demo/.logs/simulator.log

# Frontend
tail -f demo/.logs/frontend.log

# ShopLab storefront and its traffic simulator
tail -f demo/.logs/shoplab.log
tail -f demo/.logs/shoplab-simulator.log
```

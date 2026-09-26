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

### AWS

There is no one-command AWS demo. The script that claimed to be one could not
work (it set neither of the two values the stacks refuse to synthesise
without, and created no image, repository or secret), and it has been retired
(#73). Deploying to AWS is the self-hosting path:
[AWS CDK deployment](../docs/self-hosting/cdk.md), then the ordered first-deploy
checklist in the [deployment guide](../docs/deployment/deployment-guide.md#1-before-the-first-deploy).
Budget for it: two or more hours the first time, and real monthly cost
(Aurora, NAT, the load balancer) -- `cdk.md` lists what a teardown leaves behind.

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

### Scene 0b — StreamPulse: feature flags on mobile (5 min)

StreamPulse (`demo/streampulse`, http://localhost:3300) is a simulated music app: a phone frame with seven screens and a
device picker. Every flag and experiment is evaluated for the chosen device through the React SDK, with the device's
attributes (OS, OS version, app version, region, tier, employee) sent as targeting context. A simulator streams thousands
of devices through the same API, and a scripted "rollout story" walks the platform through a real launch.

**What to show:**
- Pick **iPhone 15 · iOS 17.4 · US · premium** → the Search tab shows **AI search ✨**. Pick **Pixel 7 · Android 14 · DE**
  → keyword search. The Experimently panel shows `streampulse_ai_search: on (targeting_rule)` vs `off (rollout)`.
  - "That rule is `os = iOS AND os_version ≥ 17.0.0 AND region = US AND tier = premium`, built in the dashboard's targeting
    editor. Nothing is hard-coded in the app."
- Pick **Internal tester** → the Player tab shows the redesigned player (`streampulse_player_v2: on (targeting_rule)`,
  employee rule) while normal devices are in the 5% canary.
- Profile tab: `streampulse_wrapped` and `streampulse_profile_badges` are in a **mutual exclusion group** — the panel shows
  one assigned and the other "excluded: mutual exclusion". A few devices show "in global holdout" for every experiment.
- Kill switch: in the dashboard (http://localhost:3100/feature-flags) disable **streampulse_recs_v2** → within five seconds
  the Home tab falls back to the classic feed.
- The rollout story (drawer in the app, driven by `python demo/streampulse/simulator/rollout_story.py --auto`):
  1. player v2 at 5% + internal rule → 2. advance the schedule to 25% → 3. Android 12 devices start crashing (the simulator
  reports errors through the API) → 4. the safety monitor sees the error rate cross 5% and rolls the flag back to 5%
  automatically → 5. a fix ships: rule `app_version ≥ 3.2.1` → 6. 50% → 7. 100%.
  - "Targeting, gradual rollout, safety monitoring, auto-rollback and lifecycle management, in one walkthrough."

**Key talking points:**
- Server-side targeting with 20+ operators, including semantic versions
- Rollout schedules and safety monitoring work together: expand automatically, retreat automatically
- Kill switches take effect without a release, which is the whole point on mobile

Run pieces by hand: `python backend/scripts/seed_streampulse.py`, `cd demo/streampulse && npm run dev`,
`python demo/streampulse/simulator/traffic.py --rate 3`, `python demo/streampulse/simulator/rollout_story.py --auto`.
For the story to complete on its own, run the backend with `SAFETY_CHECK_INTERVAL_MINUTES=1 ROLLOUT_CHECK_INTERVAL_MINUTES=1`.
See `demo/streampulse/README.md`.

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

### Scene 5 — Modules / Admin (5 min)

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
- Four built-in roles are enforced today. Custom roles and resource-level grants exist in the data model but are
  not yet enforced by the permission checks, so do not demo them (tracked in the launch plan, P5).

**API / Integrations:**
- Navigate to `/api/v1/docs` (Swagger UI)
  - "Full REST API. Your team can automate everything — CI/CD can create and start experiments, and Slack/email
    alerts fire when tests complete."
- Jira/Salesforce/GitHub integrations are configurable but their outbound delivery has only been exercised with
  mocks; treat them as roadmap in demos until the P5 path tests are green.

**Key talking points:**
- SOC 2 / ISO 27001 ready — HMAC audit trail, compliance reports
- RBAC with four built-in roles (custom roles: roadmap)
- Full REST API + SDKs (Python, JavaScript, Java, React, Go)
- Deployable to your AWS account — you own the data, it never leaves your VPC

---

## FAQ / Objections

**"Can it connect to our data warehouse?"**
> Yes. Snowflake, BigQuery, and Redshift are all supported via the warehouse-native analytics feature. You can query your existing event data without moving it.

**"Is it SOC 2 compliant?"**
> The platform is not certified and we do not claim it. What it gives you are controls that support your own program: an append-only audit log of every change in the core profile, and with the `compliance` module HMAC-SHA256 signed audit events with exportable report packs. Your auditor decides what they satisfy.

**"What about our tech stack?"**
> We have SDKs for Python, JavaScript/TypeScript, Java (Spring Boot auto-configuration), and React (with hooks and SSR support). The REST API means you can integrate from anything.

**"How do we deploy? What's the infrastructure cost?"**
> Into your own AWS account with the AWS CDK — ECS Fargate, Aurora PostgreSQL, ElastiCache Redis — following docs/self-hosting/cdk.md, then dispatching the Deploy workflow for staging or prod. You own all the infrastructure. It is not one command, and the cost is real (Aurora, NAT gateways, a load balancer); cdk.md says what a teardown leaves behind.

**"Can we run A/B tests across multiple products simultaneously?"**
> Yes. Mutual Exclusion Groups ensure users are never in conflicting experiments. The Global Holdout group lets you measure the cumulative impact of all experiments combined.

**"What if an experiment goes wrong?"**
> Safety monitoring watches error rates and latency in real time. If a feature flag causes problems, it auto-rolls back. For experiments, you can pause or stop at any time.

---

## Quick Reference URLs

| Page | URL |
|------|-----|
| ShopLab storefront | http://localhost:3200 |
| StreamPulse mobile demo | http://localhost:3300 |
| Home | http://localhost:3100 |
| Feature Flags | http://localhost:3100/feature-flags |
| Experiments | http://localhost:3100/experiments |
| Results (Hero) | http://localhost:3100/results/homepage_hero_copy |
| MAB | http://localhost:3100/experiments/recommendation_algorithm |
| Audit | http://localhost:3100/admin/audit |
| Users/RBAC | http://localhost:3100/admin/users |
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

# StreamPulse and its device simulator
tail -f demo/.logs/streampulse.log
tail -f demo/.logs/streampulse-simulator.log
```

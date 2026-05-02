# Manual UAT & Real-World Validation Guide

**Audience**: Solo developer / product owner validating an LLM-built platform.
**Purpose**: Cover what automated tests cannot — *has a human ever used this product end-to-end as a customer would?*
**Companion to**: [`autonomous-testing-framework.md`](./autonomous-testing-framework.md) (automated tests) and [`integration-testing-plan.md`](./integration-testing-plan.md) (cross-SDK).

---

## Why this doc exists

The platform has ~4,600 automated tests but **no human has walked through the product end-to-end as a customer would**. Automated tests verify *the code behaves as the LLM expected*. They do not verify:

- Whether the frontend even renders without JS errors
- Whether the integration developer experience is acceptable (SDK install → first event → see result)
- Whether the dashboard is *trustworthy* — would you bet a $1M product decision on it?
- Whether realistic data flows produce sane results (winning, null, novelty effect, SRM)

This guide closes that gap with three validation tracks.

---

## Two paths: triage vs. comprehensive

Pick one before committing.

| Path | Time | When to use | Output |
|---|---|---|---|
| **Triage** | 2-3 days | First pass — is the platform 80% there or 20% there? | One-page "what works / what's broken" report |
| **Comprehensive** | 3-4 weeks | Pre-launch hardening, or after triage shows the platform is viable | Per-track sign-off + bug backlog + integration tutorials |

**Recommendation**: do triage this week. Decide afterward whether comprehensive is worth the investment.

---

## Track 1 — Can it even start?

**Goal**: Stand the platform up locally and confirm the surface works. This usually surfaces 30-50% of real bugs in 4 hours.

**Time**: 4 hours (triage) → 1-2 days (comprehensive, with bug-fix loop)

### Pre-flight

```bash
# From repo root
docker-compose up -d
docker-compose logs -f api  # Watch for startup errors
```

If the backend won't start, **stop here** and fix wiring issues before anything else. LLM-built code commonly has missing env vars, broken migrations, or import-time crashes.

### Track 1 checklist

| # | Step | Expected | Record if broken |
|---|---|---|---|
| 1 | `docker-compose up -d` exits 0 | All containers `Up` in `docker ps` | Container name, error from `docker logs <name>` |
| 2 | `curl localhost:8000/health` | `200 OK`, JSON with `status: healthy` | Status code, response body |
| 3 | `curl localhost:8000/docs` | Swagger UI HTML | What renders instead |
| 4 | Open `localhost:3000` in browser | Login or landing page renders | Screenshot, browser console errors |
| 5 | Create a user (signup or seed) | Can log in, lands on dashboard | Where it failed |
| 6 | Click every nav item | Each page loads without error | Page name, error |
| 7 | Open DevTools → Network on each page | No 404s, 500s, or CORS errors | Failing requests |
| 8 | Open DevTools → Console on each page | No red errors | Error message |
| 9 | Try to create one experiment via UI | Save succeeds, appears in list | Where the form broke |
| 10 | Try to create one feature flag via UI | Same | Same |
| 11 | Pick 5 endpoints in `/docs`, try each | Each returns valid response | Endpoint, error |

### Track 1 output template

Create `uat-reports/track-1-baseline.md`:

```markdown
# Track 1 Baseline — <date>

## What works
- [list]

## What's broken
| Severity | Page/endpoint | Symptom | Console/log error |
|---|---|---|---|

## What's empty/confusing
- [list — e.g., "Experiments page renders but shows no data and no empty state"]

## Decision
- [ ] Platform is usable enough for Track 2 — proceed
- [ ] Foundational issues — fix before Track 2 (list blocking bugs)
```

---

## Track 2 — Real-world integration ergonomics

**Goal**: Answer "how easy is it for a developer to integrate this into a real app?" The only honest way to answer this is *to actually integrate it*.

**Time**: 2-3 days per toy app (triage = 1 app, comprehensive = 3 apps)

### The three toy apps

Each app should be ~150-300 lines. The point isn't the app — it's discovering integration friction.

| App | Stack | Use case | SDK exercised | What it tests |
|---|---|---|---|---|
| **Toy Shop** | Next.js + JS SDK | A/B test "Buy Now" button color, measure click-through | `sdk/javascript/` | Frontend variant assignment, event tracking, results dashboard |
| **Pricing API** | Python Flask + Python SDK | Multi-variant pricing, server-side assignment | `sdk/python/` | Backend evaluation, segment targeting, consistent hashing |
| **Mobile Rollout Sim** | curl scripts + Go SDK | Gradual feature flag rollout from 5% → 100% | `sdk/go/` | Rollout schedules, kill-switch, % bucketing stability |

### Track 2 checklist (per app)

| # | Step | Record |
|---|---|---|
| 1 | Read SDK quickstart docs cold | Time to "I understand what to do" |
| 2 | Install SDK, init client | Lines of config, errors hit |
| 3 | Create the experiment in the platform UI | Fields that confused you, undocumented requirements |
| 4 | Wire the experiment into the toy app | First-event-fired time, debugging needed |
| 5 | Generate 1,000 fake user requests | Variants assigned consistently? Network errors? |
| 6 | Open results dashboard | Data appears? Latency from event → dashboard? |
| 7 | Let it run for ~10 minutes | Numbers update? P-values look sensible? |
| 8 | Kill-switch the experiment | Takes effect within how long? |

### Track 2 output template

Create `uat-reports/track-2-<app-name>.md`:

```markdown
# Track 2 — Toy Shop integration — <date>

## Time to first variant assignment
- Reading docs: __ min
- Installing SDK: __ min
- Wiring into app: __ min
- First event in dashboard: __ min
- **Total**: __ min

## Friction points
1. [doc said X, actual API is Y]
2. [SDK swallowed an error silently]
3. [had to read source code to figure out Z]

## Bugs found
| Where | Symptom | Severity |
|---|---|---|

## Would I integrate this into a real app?
- [ ] Yes, after fixing the bugs above
- [ ] No — fundamental issues with [API design / SDK ergonomics / docs]
```

---

## Track 3 — Realistic scenarios

**Goal**: Verify that with realistic data flows, the platform produces *trustworthy* outputs. Statistical correctness matters as much as code correctness.

**Time**: 3-5 days

The repo already has a `data-generator` agent (EP-047) and a `validator` agent. Use them — but seed scenarios that mirror real experiment lifecycles, not just "valid shapes."

### The five canonical scenarios

| # | Scenario | Setup | Expected outcome | Catches |
|---|---|---|---|---|
| 1 | **Winning variant** | 10k users, B has +8% conversion vs A | p < 0.05 around day 7; results UI shows clear winner | Stats engine sanity |
| 2 | **Null result** | 10k users, A and B identical | p stays > 0.05; UI calls it inconclusive at planned end | False-positive control |
| 3 | **Novelty effect** | B wins week 1 (+15%), regresses to flat by week 3 | Sequential test (mSPRT) doesn't prematurely declare winner; final result is null | EP-021 sequential testing |
| 4 | **Sample ratio mismatch** | Assignment is broken — 60/40 split when targeting 50/50 | Platform alerts SRM; results flagged as untrustworthy | SRM detection (EP-025/EP-028) |
| 5 | **Interaction effect** | Two concurrent experiments with overlapping users contaminate each other | Mutual exclusion (EP-022) prevents overlap; or interaction detection flags it | EP-022 / Issue #25 |

### Track 3 checklist (per scenario)

| # | Step | Pass criterion |
|---|---|---|
| 1 | Generate scenario data via `data-generator` agent | Data lands in DB, user count matches |
| 2 | Walk the dashboard as a PM would | Charts render, numbers update |
| 3 | Read the experiment's results page | Verdict matches expected outcome |
| 4 | Check what the platform *says* vs. what's *true* | Match (or document the divergence) |
| 5 | Ask the killer question | "Would I bet a $1M decision on this?" |

### Track 3 output template

Create `uat-reports/track-3-scenarios.md`:

```markdown
# Track 3 — Scenario validation — <date>

| # | Scenario | Expected | Actual | Trust verdict |
|---|---|---|---|---|
| 1 | Winning variant | p<0.05 by day 7 |  | ✅/❌ |
| 2 | Null result | p>0.05 throughout |  | ✅/❌ |
| 3 | Novelty effect | Final = null |  | ✅/❌ |
| 4 | SRM | Alert raised |  | ✅/❌ |
| 5 | Interaction | Mutex prevents or flags |  | ✅/❌ |

## Statistical issues found
- [list — wrong p-value formula, miscalibrated CIs, etc.]

## Trust verdict overall
- [ ] Trustworthy enough to make real product decisions
- [ ] Numbers are right but UI presentation is misleading
- [ ] Numbers are wrong — do not use for decisions
```

---

## The 2-hour starter exercise

If you want one concrete first action *right now*, do this:

```bash
# 1. Bring the stack up
docker-compose up -d
sleep 30  # let migrations run

# 2. Verify health
curl -s localhost:8000/health | jq
curl -s localhost:3000 -o /dev/null -w "%{http_code}\n"

# 3. Walk the UI (use the scenario-runner agent for screenshots)
# Open localhost:3000, screenshot every page, note every error

# 4. Send 100 fake assignments
for i in $(seq 1 100); do
  curl -s -X POST localhost:8000/api/v1/assignments \
    -H "Content-Type: application/json" \
    -d "{\"experiment_key\": \"test-exp\", \"user_id\": \"user-$i\"}"
done

# 5. Check if results appear in the dashboard
```

**This single exercise tells you more than any test suite.** Output goes in `uat-reports/2-hour-starter.md`.

---

## How this fits with automated tests

| Question | Answered by |
|---|---|
| Does the code behave as designed? | Unit tests (`backend/tests/unit/`) |
| Do components integrate? | Integration tests (`backend/tests/integration/`) |
| Does the API work end-to-end with no mocks? | Smoke tests (`backend/tests/smoke/`) |
| Do the SDKs all hash identically? | Contract tests (`backend/tests/contract/`) |
| Does the dashboard render without crashing? | E2E Playwright (`frontend/tests/e2e/`) |
| **Is the product trustworthy and usable?** | **This guide** |
| **Can a real developer integrate it?** | **This guide (Track 2)** |

Automated tests are necessary but not sufficient. This guide is the human layer.

---

## Bug-tracking convention

For every bug found during UAT, file a GitHub issue with:

- **Label**: `uat-track-1`, `uat-track-2`, or `uat-track-3`
- **Body**: which checklist step, what you saw, what you expected, screenshot if UI
- **Severity**: `blocker` (cannot proceed), `major` (workaround exists), `minor` (cosmetic)

Triage rule: do not start the next track if there are open `blocker`s in the current track.

---

## Sign-off criteria

The platform is "ready for paid customers" when:

- [ ] Track 1: zero `blocker`s, zero console errors on any dashboard page
- [ ] Track 2: at least one toy app integrated end-to-end with documented < 30 min "time to first event"
- [ ] Track 3: scenarios 1, 2, and 4 pass; novelty + interaction documented (even if not fully passing)
- [ ] Bug backlog has been reviewed and prioritized
- [ ] One non-author has run Track 1 independently and produced their own report

The platform is "ready for free open-source release" when Track 1 passes.

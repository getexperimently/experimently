# User Guide

Guide for product managers, experimenters, and analysts using Experimently.

---

## Introduction

Experimently enables you to:
- **A/B test** product changes with statistical rigor
- **Feature flag** new functionality for controlled rollouts
- **Analyze results** with real-time statistical significance reporting
- **Target users** with precise rules-based segmentation

---

## Accessing the Platform

Open the dashboard at http://localhost:3000 (development) or your production URL.

You'll need an account with one of the following roles:

| Role | What You Can Do |
|------|----------------|
| **ADMIN** | Manage users; create experiments and change any experiment, but schedule and delete only your own; all flags |
| **DEVELOPER** | Create experiments and change any experiment, but schedule and delete only your own; create and manage any feature flag |
| **ANALYST** | View all experiments, results, and reports, and every feature flag (read-only) |
| **VIEWER** | View every experiment and its results, and every feature flag (read-only) |

Contact your platform admin to request access or role changes.

---

## Experiments

### What Is an A/B Test?

An A/B test (experiment) splits your users into groups, shows each group a different version of a feature, and measures which version performs better on a defined metric.

**Key concepts:**
- **Control** — the current/existing experience (your baseline)
- **Treatment/Variant** — the new experience you're testing
- **Metric** — what you're measuring (conversion rate, revenue, clicks)
- **Statistical significance** — confidence that the difference is real, not random noise

### Creating an Experiment

**Experiments → + New Experiment** opens *guided setup*, five short steps. Your answers
stay in this browser tab until you press **Create Experiment**; reloading starts over.
If you prefer every field on one page, choose **Use the single-page form (advanced)** —
your answers carry over.

**Step 1: Type**

Choose **A/B Test** or **Multivariate**. Split URL and bandit experiments need settings
guided setup does not ask for; create those through the API or an SDK.

**Step 2: Details**

- **Name**: Descriptive name, e.g., "Homepage CTA Button Color Q1 2026"
- **Key**: generated from the name until you edit it, e.g., `homepage_cta_button_color_q1_2026` — your code passes this as `experiment_key`
- **Description**: Background context, links to design doc, Jira ticket
- **Hypothesis**: "Changing the CTA button from blue to green will increase click-through rate by 10%"

Then choose what to measure. Mark one metric as the **primary metric** (the one you decide
on); any others are tracked alongside it.

| Metric Type | When to Use | Example |
|-------------|-------------|---------|
| **CONVERSION** | Binary outcome (did it happen?) | Clicked CTA, completed checkout, signed up |
| **REVENUE** | Dollar amounts | Order value, LTV increase |
| **COUNT** | How many times | Page views per session, actions taken |
| **DURATION** | Time measurements | Session duration, time to first action |

The metric's **event name** must match exactly what your engineers track in code (e.g., `checkout_complete`).

**Step 3: Variants**

Every experiment needs a control; mark one variant as it:

| Variant | Is Control | Traffic % |
|---------|-----------|-----------|
| Control (Blue Button) | ✅ | 50% |
| Treatment (Green Button) | — | 50% |

The traffic split must add up to exactly 100%.

For multivariate tests, add more variants:

| Variant | Is Control | Traffic % |
|---------|-----------|-----------|
| Control | ✅ | 34% |
| Green Button | — | 33% |
| Red Button | — | 33% |

Only want to test on specific users? Add targeting rules on the same step:

- Country is in [US, CA]
- Subscription plan is "premium"
- Account age is greater than 30 days

Users who don't match targeting rules are excluded from the experiment entirely.

Every condition needs an attribute, an operator and (for most operators) a value. If one is
missing, **Create Experiment** stops and the problem is shown beside the targeting rules; a
condition the server cannot apply is reported there too.

**Step 4: Estimate (optional)**

Enter your baseline conversion rate and the smallest change worth detecting — a
*relative* change, so 5% on a 12% baseline means 12% → 12.6% — and press **Calculate
estimate**. At 80% power and 5% significance that example needs 47,034 users per variant.
Add your daily users to see roughly how many days that takes. The estimate is advisory:
nothing here is saved with the experiment.

**Step 5: Review and create**

Check the summary, use **Edit** to go back to any step, then press **Create Experiment**.
The experiment is created as a draft and you land on its page.

**Then: start the experiment**

Click **Start** on the experiment's page. The status changes to `ACTIVE`.

You can also schedule automatic start and end dates. The dashboard has no schedule
screen yet, so this is an API call: `PUT /api/v1/experiments/{experiment_id}/schedule`,
on a `DRAFT` experiment, with an ADMIN or DEVELOPER token. The experiment activates at
`start_date` and completes at `end_date`, which must be at least an hour later. A date you
leave out of the request is left as it is, and `null` clears it. A date written without a
UTC offset is read in `time_zone`, an IANA name such as `America/Los_Angeles` (default
`UTC`); a date with an offset, like the ones below, keeps it. Dates are stored in UTC.

```{.bash skip reason="server: needs a running API, a signed-in token in TOKEN and a draft experiment's id in EXPERIMENT_ID"}
curl -s -X PUT "localhost:8000/api/v1/experiments/$EXPERIMENT_ID/schedule" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"start_date": "2026-11-02T09:00:00Z", "end_date": "2026-11-16T09:00:00Z"}'
```

---

### Pausing and Stopping

**Pause**: Temporarily halt assignment of new users. Existing assignments are preserved. Use when you need to investigate anomalies or if there's a critical bug.

A paused experiment stays paused until you click **Start** again. Nothing resumes it
behind your back: not the scheduler, and not a restart of the service.

To have it resume by itself at a set time, schedule a resume *after* pausing: the same
`PUT /api/v1/experiments/{experiment_id}/schedule` call, where `start_date` is the time
to resume at. It is stored as `resume_at` (returned with the experiment); the experiment's own
start date does not move. On a paused experiment:

- `"start_date": null` cancels a scheduled resume;
- a field you leave out is left as it is, as on a draft;
- `end_date` must be later than the experiment's start date and, with a resume scheduled,
  at least an hour after the resume time.

Starting, completing or archiving the experiment cancels a scheduled resume, and so does
any other change of status.

**Complete**: Stop the experiment. Use when you have sufficient data and are ready to make a decision. Existing data is preserved.

**Rules for stopping early:**
- You need statistical significance (p-value < 0.05) AND practical significance (effect size is meaningful)
- Resist the urge to stop as soon as significance is reached — this inflates false positive rates
- Use the **Sample Size Meter** to confirm you've reached the required sample size before deciding

---

### Reading Results

Navigate to **Experiments → [Your Experiment] → Results** or http://localhost:3000/results/EXPERIMENT_ID.

#### Experiment Summary Card

Shows at a glance:
- **Status**: Active / Completed
- **Duration**: Days running
- **Total Users**: Participants across all variants
- **Recommendation**: SHIP VARIANT / KEEP CONTROL / CONTINUE TESTING / INCONCLUSIVE

#### Recommendation Meanings

| Recommendation | Meaning | Action |
|----------------|---------|--------|
| **SHIP VARIANT** | Treatment is significantly better | Deploy the treatment to all users |
| **KEEP CONTROL** | Control is significantly better | Do not ship the treatment |
| **CONTINUE TESTING** | Not enough data yet | Wait for more data before deciding |
| **INCONCLUSIVE** | No meaningful difference detected | Consider whether the change is worth shipping anyway |

#### Metric Comparison Table

For each metric and variant pair:

| Column | Meaning |
|--------|---------|
| **Sample Size** | Users assigned to this variant |
| **Value** | Conversion rate or average value for this variant |
| **Improvement** | How much better/worse vs. control (e.g., +12.3%) |
| **p-value** | Probability the difference is due to chance (lower = more confident) |
| **Significance** | p-value < (1 - confidence level), e.g., < 0.05 for 95% confidence |

The table has no effect size or confidence interval column yet. Both are in the API
response: `GET /api/v1/results/{experiment_id}` returns `effect_size`, `effect_size_label`
(negligible / small / medium / large) and `confidence_interval` for each variant.

**Green** = statistically significant improvement
**Red** = statistically significant degradation
**Gray** = not statistically significant

#### Trend Chart

Shows conversion rate over time for each variant. Two modes:
- **Cumulative**: Running total from experiment start (recommended — smooths noise)
- **Daily**: Day-by-day rate (useful for detecting novelty effects or day-of-week patterns)

Look for:
- Parallel lines early → diverging lines → stable difference (healthy experiment)
- Crossing lines → potential interaction effects or bugs
- Spike on day 1 → novelty effect (users excited about newness)

#### Sample Size Meter

Shows current vs. required sample size:
- **Green (>100%)**: Adequate — you have enough data for a reliable decision
- **Amber (80-100%)**: Almost there — wait a bit longer
- **Red (<80%)**: Not enough data — results are unreliable, don't make a decision

"Days to Significance" estimates how long until you reach the required sample size at the current rate.

---

### Making a Decision

Once your experiment is adequately powered and statistically significant:

1. **Check primary metric**: Is the direction positive? Is the effect meaningful?
2. **Check secondary metrics**: Did anything unexpected change (e.g., revenue went up but customer satisfaction dropped)?
3. **Check for novelty effect**: Did the initial spike smooth out? Are trends stable?
4. **Consult stakeholders**: Share results and the recommendation with the team

**Ship**: Deploy the winning variant to 100% of users. Mark the experiment as **Completed**.

**Keep control**: The change didn't work. Archive or redesign the hypothesis.

**Document your decision**: Add a note in the experiment description with the outcome and rationale. This creates institutional memory.

---

## Feature Flags

Feature flags let you control which users see a feature without deploying new code. They're useful for:

- **Canary releases**: Deploy to 5% of users first, monitor, then expand
- **Kill switches**: Instant rollback without a code deploy
- **Beta programs**: Enable features for specific user groups
- **Gradual rollouts**: Expand from 10% → 50% → 100% over time

### Creating a Feature Flag

Navigate to **Feature Flags → New Flag**:

- **Key**: Identifier used in code, e.g., `new-checkout-flow` (cannot change after creation)
- **Name**: Human-readable name
- **Description**: What this flag controls
- **Rollout Percentage**: Start at 0 for a disabled flag

### Controlling Rollout

**Manual rollout:**

Open the flag, move the **Rollout percentage** slider to the desired value and press **Save Changes**. Changes take effect within 60 seconds (cache TTL).

| Percentage | Meaning |
|------------|---------|
| 0% | Feature disabled for all users |
| 5% | 1 in 20 users sees the feature |
| 50% | Half of users |
| 100% | All users see the feature |

**Who gets the feature?**
The platform uses a deterministic hash of the user's ID. The same user always gets the same result (sticky assignment). This means:
- If you set 5%, the same 5% of users will consistently see the feature
- If you increase to 50%, the original 5% are still included (plus 45% more)

**Adding targeting rules:**

Optionally restrict to specific users:
- Enable only for users in the US
- Only for users on the "enterprise" plan
- Only for users who signed up before a certain date

### Scheduled Rollouts

For gradual rollouts on a schedule:

The dashboard has no screen for creating a rollout schedule yet. Create it through the
API with `POST /api/v1/rollout-schedules` (the stages go in its `stages` list; see
[Rollouts](../feature-flags/rollouts.md) for the full contract), then start it with
`POST /api/v1/rollout-schedules/{schedule_id}/activate`. The flag's page in the dashboard
shows the schedule, its status and its stages, read-only. A schedule like this one:

| Stage | Target % | Trigger Type | Start Date |
|-------|----------|-------------|-----------|
| Stage 1 | 5% | Time-based | Apr 1, 2026 |
| Stage 2 | 25% | Time-based | Apr 8, 2026 |
| Stage 3 | 100% | Manual | — |

The platform automatically advances time-based stages. A manual stage waits until you
advance it. The dashboard has no button for that yet, so it is an API call:
`POST /api/v1/rollout-schedules/stages/{stage_id}/advance`.

**Best practice:** End your schedule with a manual stage for the final 100% rollout. This gives you a human approval gate before full deployment.

### Disabling / Rolling Back

To instantly disable a flag:
1. Set the rollout percentage to 0 and press **Save Changes**
2. Or turn the flag off with the switch at the top of its page; it then shows **Not serving**

If you have safety monitoring configured, the platform can auto-rollback if error rates spike.

---

## Analytics & Reporting

### Viewing All Experiments

**Experiments list** shows all experiments with their name, status, type, number of
variants and creation date.

Filter by status: All / Draft / Active / Paused / Completed. There is no filter by date,
owner or experiment type yet.

### Exporting Results

The Results page has no export button yet. Use the API:
- **CSV export**: `GET /api/v1/export/variants` downloads per-variant results as CSV
  (`?format=json` for JSON); see [Data Export](../api/data-export.md)
- **Full results**: `GET /api/v1/results/{experiment_id}` returns JSON with all statistics

---

## Targeting Rules Reference

### Basic Rules

```text
country IN [US, CA, GB]          → User's country is one of the list
plan EQUALS premium              → Exact match
age GREATER_THAN 18              → Numeric comparison
email CONTAINS @company.com     → String match
app_version SEMVER_GT 2.0.0     → Semantic version comparison
```

### Logical Operators

```text
AND: all rules must match
OR:  at least one rule must match
NOT: rule must NOT match
```

### Complex Example

Target US/EU premium users who are active:
```text
AND:
  country IN [US, GB, DE, FR]
  plan IN [pro, enterprise]
  days_since_last_login LESS_THAN 30
```

Target either new users OR power users (but not average users):
```text
OR:
  account_age_days LESS_THAN 7
  AND:
    lifetime_purchases GREATER_THAN 20
    plan EQUALS enterprise
```

---

## Best Practices

### Experiment Design

**Do:**
- Define your hypothesis and primary metric BEFORE starting the experiment
- Run the experiment for at least one full week to capture weekly patterns
- Wait for statistical significance AND adequate sample size before deciding
- Document your hypothesis, result, and decision for future reference
- Run one change at a time per experiment (isolate variables)

**Don't:**
- Stop the experiment as soon as you see significance (peeking inflates false positives)
- Change the experiment configuration after it's started
- Run too many concurrent experiments on the same users (interaction effects)
- Use the novelty effect as evidence (users are excited about newness, not the feature)

### Feature Flags

**Do:**
- Always start at 0% and ramp up gradually for risky changes
- Set up safety monitoring for flags that touch payments, auth, or core flows
- Document what the flag controls and who to contact if issues arise
- Clean up flags after full rollout — don't leave them in code forever

**Don't:**
- Jump straight to 100% for significant changes
- Leave flags enabled indefinitely — schedule cleanup
- Use flags to hide incomplete features in production without testing

### Statistical Significance

- **p-value < 0.05**: 95% confident the difference is real (not random)
- **p-value < 0.01**: 99% confident — use for high-stakes decisions
- **Always check effect size**: A p-value of 0.001 means nothing if the effect is 0.1%
- **Minimum detectable effect**: Design experiments to detect a meaningful improvement (e.g., 5%), not just any improvement

---

## Advanced Statistical Methods

### Sequential Testing — Stop Experiments Early

Standard A/B tests require a fixed sample size decided upfront. Sequential testing lets you monitor results continuously and stop as soon as you have enough evidence — without inflating your false positive rate.

**When to use it:** When you need results faster, or when you need to stop early if a variant is performing significantly worse.

Access via the **Sequential** tab on any experiment results page, or via:
```text
GET /api/v1/results/{experiment_id}/sequential
```

The platform uses **mSPRT** (mixture Sequential Probability Ratio Test). When `recommended_action` is `stop_for_effect`, it is safe to stop. An experiment running well past its expected duration is flagged `at_risk`; that is advisory, not a reason to conclude there is no effect. See the [Sequential Testing Guide](../api/sequential-testing.md) for details.

---

### CUPED — Reach Significance Faster

**Beta: not yet a pre-experiment covariate.** The CUPED endpoint does not yet use a pre-experiment metric as the covariate, so in this release it removes almost no variance ([#217](https://github.com/getexperimently/experimently/issues/217)).

CUPED reduces result noise by adjusting for each user's pre-experiment behavior; how much depends on how well that behavior predicts the outcome.

**When to use it:** When you have historical metric data for your users (e.g., prior revenue, prior sessions). Works best when the covariate is strongly correlated with the outcome.

The dashboard has no CUPED tab; it is available through the API:
```text
GET /api/v1/results/{experiment_id}/cuped
```

See the [CUPED Guide](../api/cuped.md) for covariate selection guidance.

---

### Dimensional Analysis — Did the Effect Vary by Segment?

After an experiment concludes, use dimensional analysis to understand whether the treatment worked differently for different groups (mobile vs desktop, new vs returning users, etc.).

**Important:** Segment findings are always exploratory. Use them to generate hypotheses for follow-up experiments, not as final conclusions.

Access via the **Breakdowns** tab on any experiment results page, or via:
```text
GET /api/v1/experiments/{experiment_id}/segmented-results/{segment_by}?dimension=device
```

See the [Dimensional Analysis Guide](../api/dimensional-analysis.md).

---

### Multi-Armed Bandit — Maximize Conversions During the Experiment

A bandit experiment automatically shifts traffic toward the better-performing variant as data accumulates. Use this when maximizing conversions during the experiment matters more than getting precise effect size estimates.

**When to use it:** Short-lived promotions, content recommendations, or situations where you have many variants to test quickly.

Set `optimization_type` to `thompson_sampling`, `ucb1`, or `epsilon_greedy` when creating an experiment. See the [Multi-Armed Bandit Guide](../api/multi-armed-bandit.md).

---

### Interaction Detection — Are Your Experiments Interfering?

When multiple experiments run simultaneously on overlapping user populations, they can distort each other's results. Run an interaction scan to find the pairs that share users. Only the overlap is measured yet: the interaction, novelty and SUTVA results are `null` ([#219](https://github.com/getexperimently/experimently/issues/219)).

Access via:
```text
GET /api/v1/interactions/scan
```

If high-risk pairs are found, add the experiments to a [Mutual Exclusion Group](../api/mutual-exclusion-groups.md) to prevent overlap in future runs. See the [Interaction Detection Guide](../api/interaction-detection.md).

---

## Getting Help

- **API Documentation**: http://localhost:8000/api/v1/docs
- **Technical Guide**: See [Technical Guide](../architecture/technical-guide.md) for implementation details
- **Testing Guide**: See [Testing Guide](../development/testing-guide.md) for test workflows
- **Issues**: https://github.com/getexperimently/experimently/issues
- **Slack**: #experimently channel

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
| **ADMIN** | Everything — manage users, all experiments, all flags |
| **DEVELOPER** | Create and manage your own experiments; create and manage any feature flag |
| **ANALYST** | View all experiments, results, and reports, and every feature flag (read-only) |
| **VIEWER** | View approved experiments and their results, and every feature flag |

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

**Step 1: Define the experiment**

Navigate to **Experiments → New Experiment** and fill in:

- **Name**: Descriptive name, e.g., "Homepage CTA Button Color Q1 2026"
- **Key**: Auto-generated slug, e.g., `homepage-cta-color` — this is used in code
- **Hypothesis**: "Changing the CTA button from blue to green will increase click-through rate by 10%"
- **Description**: Background context, links to design doc, Jira ticket

**Step 2: Add variants**

Every experiment needs at least one control and one treatment:

| Variant | Is Control | Traffic % |
|---------|-----------|-----------|
| Control (Blue Button) | ✅ | 50% |
| Treatment (Green Button) | — | 50% |

Traffic allocation must total ≤ 100%. The remaining percentage is excluded from the experiment.

For multivariate tests, add more variants:

| Variant | Is Control | Traffic % |
|---------|-----------|-----------|
| Control | ✅ | 34% |
| Green Button | — | 33% |
| Red Button | — | 33% |

**Step 3: Define metrics**

Choose what to measure. Every experiment should have one **primary metric** (your north star for the decision) and optional secondary metrics.

| Metric Type | When to Use | Example |
|-------------|-------------|---------|
| **CONVERSION** | Binary outcome (did it happen?) | Clicked CTA, completed checkout, signed up |
| **REVENUE** | Dollar amounts | Order value, LTV increase |
| **COUNT** | How many times | Page views per session, actions taken |
| **DURATION** | Time measurements | Session duration, time to first action |

The metric's **event name** must match exactly what your engineers track in code (e.g., `checkout_complete`).

**Step 4: Set targeting rules (optional)**

Only want to test on specific users? Add targeting rules:

- Country is in [US, CA]
- Subscription plan is "premium"
- Account age is greater than 30 days

Users who don't match targeting rules are excluded from the experiment entirely.

**Step 5: Start the experiment**

Click **Start Experiment**. The status changes to `ACTIVE`.

You can also schedule automatic start/end dates: go to **Experiment → Schedule** and set future dates. The experiment will auto-activate at the start date and auto-complete at the end date.

---

### Pausing and Stopping

**Pause**: Temporarily halt assignment of new users. Existing assignments are preserved. Use when you need to investigate anomalies or if there's a critical bug.

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
| **Rate/Mean** | Conversion rate or average value for this variant |
| **Relative Improvement** | How much better/worse vs. control (e.g., +12.3%) |
| **p-value** | Probability the difference is due to chance (lower = more confident) |
| **Significant** | p-value < (1 - confidence level), e.g., < 0.05 for 95% confidence |
| **Effect Size** | Practical magnitude: negligible / small / medium / large |
| **Confidence Interval** | Range where the true difference likely falls |

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

Go to the flag → Edit → set `Rollout Percentage` to the desired value. Changes take effect within 60 seconds (cache TTL).

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

Go to **Flag → Rollout Schedule → Create Schedule**:

| Stage | Target % | Trigger Type | Start Date |
|-------|----------|-------------|-----------|
| Stage 1 | 5% | Time-based | Apr 1, 2026 |
| Stage 2 | 25% | Time-based | Apr 8, 2026 |
| Stage 3 | 100% | Manual | — |

The platform automatically advances time-based stages. Manual stages require you to explicitly click **Advance Stage** in the UI.

**Best practice:** End your schedule with a manual stage for the final 100% rollout. This gives you a human approval gate before full deployment.

### Disabling / Rolling Back

To instantly disable a flag:
1. Set `Rollout Percentage = 0`
2. Or click **Deactivate** to change status to `INACTIVE`

If you have safety monitoring configured, the platform can auto-rollback if error rates spike.

---

## Analytics & Reporting

### Viewing All Experiments

**Experiments list** shows all experiments with status, owner, and quick stats.

Filter by:
- Status: DRAFT / ACTIVE / PAUSED / COMPLETED
- Date range
- Owner
- Experiment type

### Exporting Results

From the Results page:
- **CSV export**: Download variant-level metric data
- **API access**: `GET /api/v1/results/{id}` returns full JSON with all statistics

---

## Targeting Rules Reference

### Basic Rules

```
country IN [US, CA, GB]          → User's country is one of the list
plan EQUALS premium              → Exact match
age GREATER_THAN 18              → Numeric comparison
email CONTAINS @company.com     → String match
app_version SEMVER_GT 2.0.0     → Semantic version comparison
```

### Logical Operators

```
AND: all rules must match
OR:  at least one rule must match
NOT: rule must NOT match
```

### Complex Example

Target US/EU premium users who are active:
```
AND:
  country IN [US, GB, DE, FR]
  plan IN [pro, enterprise]
  days_since_last_login LESS_THAN 30
```

Target either new users OR power users (but not average users):
```
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
```
GET /api/v1/results/{experiment_id}/sequential
```

The platform uses **mSPRT** (mixture Sequential Probability Ratio Test). When `recommended_action` is `stop_for_effect` or `stop_for_futility`, it is safe to stop. See the [Sequential Testing Guide](../api/sequential-testing.md) for details.

---

### CUPED — Reach Significance Faster

CUPED reduces result noise by adjusting for each user's pre-experiment behavior. This typically cuts the required sample size by 20–40%.

**When to use it:** When you have historical metric data for your users (e.g., prior revenue, prior sessions). Works best when the covariate is strongly correlated with the outcome.

Access via the **CUPED** tab on any experiment results page, or via:
```
GET /api/v1/results/{experiment_id}/cuped
```

See the [CUPED Guide](../api/cuped.md) for covariate selection guidance.

---

### Dimensional Analysis — Did the Effect Vary by Segment?

After an experiment concludes, use dimensional analysis to understand whether the treatment worked differently for different groups (mobile vs desktop, new vs returning users, etc.).

**Important:** Segment findings are always exploratory. Use them to generate hypotheses for follow-up experiments, not as final conclusions.

Access via the **Breakdowns** tab on any experiment results page, or via:
```
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

When multiple experiments run simultaneously on overlapping user populations, they can distort each other's results. Run an interaction scan to check.

Access via:
```
GET /api/v1/interactions/scan
```

If high-risk pairs are found, add the experiments to a [Mutual Exclusion Group](../api/mutual-exclusion-groups.md) to prevent overlap in future runs. See the [Interaction Detection Guide](../api/interaction-detection.md).

---

## Getting Help

- **API Documentation**: http://localhost:8000/docs
- **Technical Guide**: See [Technical Guide](../architecture/technical-guide.md) for implementation details
- **Testing Guide**: See [Testing Guide](../development/testing-guide.md) for test workflows
- **Issues**: https://github.com/getexperimently/experimently/issues
- **Slack**: #experimently channel

Run the full autonomous testing loop for the Experimently platform.

Usage: /autotest [scenario_name or "all"]

If no scenario is provided, defaults to "ab_test_lifecycle".

## What This Does

This skill chains four specialized agents in sequence to test the platform
end-to-end — from realistic data generation through statistical validation,
with optional auto-repair if anything fails.

```
data-generator → scenario-runner → validator → reviewer → tester → (auto-fixer if failures)
```

## Execution Plan

### Phase 1: Generate Realistic Data

Use the `data-generator` agent to seed the platform with statistically realistic
scenario data.

Instructions for data-generator:
- Run scenario: "$ARGUMENTS" (if empty, use "ab_test_lifecycle")
- First do a dry run and print the summary
- If the platform is running (check health endpoint), seed the data
- Return: experiment_id (if seeded), user count, event count, expected significance, z-score

### Phase 2: Simulate User Behavior (UI)

Use the `scenario-runner` agent to walk through the dashboard as a real user.

Instructions for scenario-runner:
- Check if the frontend is running at http://localhost:3000
- If running: execute the full scenario UI walkthrough matching the scenario name
  - "ab_test_lifecycle" → Scenario 1: A/B Experiment Lifecycle
  - "feature_flag_rollout" → Scenario 2: Feature Flag Gradual Rollout
  - Default → Scenarios 1 + 3 (lifecycle + RBAC check)
- Also run Scenario 3 (RBAC) regardless of which scenario was requested
- If frontend is not running: skip UI validation and note it in the report
- Return: steps passed/failed, any unexpected UI states

### Phase 3: Validate Statistical Correctness

Use the `validator` agent to verify results are mathematically correct.

Instructions for validator:
- Use the experiment_id from Phase 1 (if available)
- Validate: basic significance, CUPED (if results endpoint supports it), sequential testing status
- If no experiment_id: validate the data generator's statistical properties directly
- Return: validation results for each check (pass/fail with values)

### Phase 4: Review Recent Code Changes

Use the `reviewer` agent to review any code changed since the last commit.

Instructions for reviewer:
- Run `git diff HEAD~1..HEAD --name-only` to find changed files
- Review each changed file for correctness, security, and pattern adherence
- Pay special attention to: import paths, async/sync patterns, RBAC checks
- Return: APPROVED / APPROVED WITH SUGGESTIONS / CHANGES REQUESTED

### Phase 5: Check Test Coverage

Use the `tester` agent to verify test coverage for changed code.

Instructions for tester:
- For each file changed since last commit, verify a corresponding test file exists
- Run the relevant tests and report pass/fail count
- If coverage gaps exist, note them but don't block the autotest run
- Return: test pass rate, any new coverage gaps

### Phase 6: Auto-Fix Failures (if any)

If Phases 2, 3, 4, or 5 produced failures, use the `auto-fixer` agent.

Instructions for auto-fixer:
- Collect all failures from all phases
- For each failure: diagnose root cause, write minimal fix, verify it passes
- If auto-fix is not possible, produce a diagnosis report
- Return: fixed issues, blocked issues (needing human review)

## Final Report

After all agents complete, produce a consolidated report:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AUTOTEST REPORT — Experimently Platform
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scenario:      <name>
Run at:        <timestamp>
Duration:      <elapsed minutes>

Phase 1 — Data Generation
  Status:      PASS / FAIL
  Users:       <n>
  Events:      <n>
  Z-score:     <value> (<significant/not significant>)

Phase 2 — UI Simulation
  Status:      PASS / FAIL / SKIPPED (frontend not running)
  Steps:       <n>/<total> passed
  Issues:      <list or "none">

Phase 3 — Statistical Validation
  Status:      PASS / FAIL / SKIPPED (no experiment seeded)
  Checks:      <n>/<total> passed
  Issues:      <list or "none">

Phase 4 — Code Review
  Status:      APPROVED / CHANGES REQUESTED / NO CHANGES
  Findings:    <summary>

Phase 5 — Test Coverage
  Status:      PASS / GAPS FOUND
  Tests run:   <n> passed, <n> failed
  Gaps:        <list or "none">

Phase 6 — Auto-Fix
  Status:      <N/A / FIXED n issues / BLOCKED>
  Fixed:       <list or "none">
  Needs review: <list or "none">

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OVERALL: ✓ PASS  |  ✗ FAIL  |  ⚠ PASS WITH WARNINGS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Quick Run (all defaults)

/autotest

## Specific Scenarios

/autotest ab_test_lifecycle
/autotest feature_flag_rollout
/autotest statistical_edge_cases
/autotest concurrent_experiments
/autotest all

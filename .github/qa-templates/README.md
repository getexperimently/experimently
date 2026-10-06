# QA output templates

The fixed wording of everything the automated QA workflows post where anyone can
read it: the synthetic check's issue and comments, the API fuzzing summaries and
issue, the docs-journey summaries and per-guide report headers, and the
docs-defect issue. This repository is public, so every workflow log, step
summary, issue and comment written from here is public the moment it is posted,
and editing it afterwards does not recall the notification e-mail.

`backend/tests/unit/infrastructure/test_qa_templates_public_text.py` reads every
file in this directory on every pull request (see "The test" below).

## Why here

- Every workflow that posts one of these reads it from its own checkout of this
  repository; nothing has to be packaged or copied.
- Not `.github/ISSUE_TEMPLATE/`: GitHub offers every Markdown file there on the
  "New issue" page.
- Not under `docs/`: the site would publish them, and a pull request that
  changes only `docs/` is classed documentation-only by
  `scripts/classify_changes.py`, so the unit job that runs the test above would
  only report. A change here runs the full gate.

## Format

- One `.tmpl` file per output. Its text is Markdown, which GitHub renders when
  it is posted (issue bodies, comments, step summaries), so lines meant to
  stand apart are separated by a blank line. It is not named `.md` because it
  is not a documentation page: every Markdown file in the repository belongs to
  the documentation examples contract (`[meta] universe` in
  `scripts/doc_examples.toml`), and this README is the one page here that is
  listed there.
- A file whose name ends in `-issue.tmpl` is an issue: line 1 is the title,
  line 2 is blank, and the rest is the body.
- A placeholder is a name in braces, such as `{date}`, and braces appear
  nowhere else. A workflow renders a template by replacing each placeholder
  with its value from one fixed mapping of name to value, and refuses a
  placeholder it has no value for. It never renders one through a shell, a
  heredoc or `envsubst`: those expand whatever variable a template names, and
  the runner's environment holds the credentials.
- A workflow posts only a rendered template (`gh issue create --body-file`,
  `gh issue comment --body-file`, or the file appended to the step summary),
  never a body it builds inline.

## Placeholders

Only these names may appear. Each is one of the kinds the QA plan allows in
public text (date, commit, run link, check name, step, HTTP status, count,
seed, duration, and for the docs runs the guide path, step number and
heading). A value is never a response or request body, a key or any part of
one, a token, a user or experiment id, an e-mail address, or a hostname.

| Placeholder | Kind | Value |
|---|---|---|
| `{date}` | date | the UTC date, `2026-10-06` |
| `{date_time}` | date | the UTC date and minute, `2026-10-06 14:17 UTC` |
| `{sha}` | commit | a commit of this repository, full or abbreviated |
| `{run_link}` | run link | the workflow run's URL on github.com |
| `{check}` | check name | synthetic: `staging` or `production`; fuzzing: the pass, `superuser`, `viewer` or `sdk` |
| `{step}` | step | the synthetic check's step, `1` to `8` |
| `{status}` | HTTP status | a status code such as `503`, or `no answer` |
| `{seed}` | seed | the fuzzing seed, an integer |
| `{duration}` | duration | how long a failure lasted, `2 h 30 min` |
| `{count_runs}` | count | runs in a row that failed |
| `{count_fuzzed}` | count | operations fuzzed in this pass |
| `{count_operations}` | count | operations this pass selects (the served API document minus the pass's exclusions) |
| `{count_5xx}` | count | operations that answered 5xx |
| `{count_5xx_unlisted}` | count | of those, operations not in the known list |
| `{count_known_quiet}` | count | known-list entries whose operation answered no 5xx |
| `{count_reached}` | count | operations reached |
| `{count_unreached}` | count | operations not reached, every one listed with a reason |
| `{count_unreached_unlisted}` | count | operations not reached and not listed |
| `{count_unreached_stale}` | count | operations listed as not reached that were reached |
| `{count_pass}` | count | guides that pass |
| `{count_fail}` | count | guides that fail |
| `{count_partial}` | count | guides with steps not run |
| `{count_nav}` | count | pages in the `mkdocs.yml` nav |
| `{count_not_covered}` | count | nav pages with no journey |
| `{count_steps}` | count | steps in a guide |
| `{count_steps_pass}` | count | steps of a guide that pass |
| `{count_not_run}` | count | steps of a guide not run |
| `{guide_path}` | guide path | the page's path in the repository, as `mkdocs.yml` names it |
| `{step_number}` | step number | the guide step's number |
| `{heading_guide}` | heading | the guide's title, its first heading |
| `{heading_step}` | heading | the guide step's own heading |

A new placeholder is added to the test's `PLACEHOLDERS` and to this table in
the same pull request, and its name starts with its kind.

## The templates

| File | Posted by | Where |
|---|---|---|
| `synthetic-issue.tmpl` | the synthetic check | the issue opened after repeated failures (rules below) |
| `synthetic-step-changed.tmpl` | the synthetic check | a comment on that issue when the failing step changes |
| `synthetic-recovered.tmpl` | the synthetic check | the comment that closes it |
| `fuzz-green.tmpl` | each fuzzing pass | the step summary of a green pass |
| `fuzz-red.tmpl` | each fuzzing pass | the step summary of a red pass, and each comment on the open fuzzing issue |
| `fuzz-issue.tmpl` | API fuzzing | the issue opened on the first red pass; its body is `fuzz-red.tmpl` |
| `docs-run-green.tmpl`, `docs-run-red.tmpl` | the docs journeys | the top of the run's step summary |
| `docs-guide-pass.tmpl`, `docs-guide-fail.tmpl`, `docs-guide-partial.tmpl` | the docs journeys | the top of each guide's report |
| `docs-defect-issue.tmpl` | the docs journeys | one issue per measured docs defect (rules below) |

Each output says what it is in its first two lines: a verdict word (GREEN, RED,
PASS, FAIL, PARTIAL, or "is red", "failed"), and either "What to do" or a
count. Every output that is not green says "What to do" in those two lines. For
an issue, the title carries the verdict and the body's first two lines carry the
rest.

## The synthetic check's issue

The synthetic workflow follows these rules; the issue body states them for the
reader.

1. One issue per target, labelled `synthetic-failure`, opened from
   `synthetic-issue.tmpl` after 3 failed runs in a row on staging, or 2 on
   production. Never one per run.
2. While it is open, a comment (`synthetic-step-changed.tmpl`) is added only when
   the failing step differs from the step the issue or its latest comment
   names. A failure at the same step adds nothing.
3. The first run that passes comments `synthetic-recovered.tmpl` and closes the
   issue.
4. A run that is skipped (`SYNTH_ENABLED` not `true`) counts as neither a
   failure nor a pass.

## The docs-defect issue

Filed only after the same step has failed in two runs. One defect per issue: a
second failing step in the same guide is a second issue, unless it was NOT RUN
because an earlier step failed. Labels: `documentation` and `qa-agent`, plus
`launch-blocking` for a guide with a release recording, `post-launch` for any
other.

## Labels

No label is created by a pull request. A workflow creates its label the first
time it needs one, the way `nightly-qa.yml` creates `nightly-failure`
(`gh label create ... || true`), with the colour and description below.

| Label | Colour | Description | Applied to |
|---|---|---|---|
| `synthetic-failure` | `B60205` | Synthetic check failed | `synthetic-issue.tmpl` |
| `fuzz-failure` | `B60205` | API fuzzing failed | `fuzz-issue.tmpl` |
| `docs-journey-failure` | `B60205` | Docs journey failed | the issue for a failing guide |
| `qa-agent` | `5319E7` | Filed by automated QA after reproduction | `docs-defect-issue.tmpl`, and public bugs filed from QA findings |

`documentation`, `launch-blocking` and `post-launch` already exist. No
`stats-failure` label is needed: the statistics batteries run in the unit job of
every pull request and of the nightly run.

## The test

`test_qa_templates_public_text.py` fails when:

- this directory holds a file the test does not list, or lacks one it does;
- a template uses a placeholder outside the table above, a brace that is not a
  placeholder, or another placeholder syntax (a dollar sign, angle brackets,
  printf-style);
- a template's placeholders differ from the set the test pins for it, title and
  body separately for an issue;
- a template or this file contains an e-mail address outside the example.com domain, an
  `@` mention, a UUID, a run of seven or more digits, anything shaped like a key,
  token or credential header, a fenced code block, a URL other than this
  repository's or its documentation site's, a hostname, or one of the words the
  project keeps out of automated public text;
- a template's first two lines break the rule above;
- the synthetic issue does not list exactly the eight steps, or the fuzzing
  issue's body is not `fuzz-red.tmpl`.

Each of those refusals is also planted against a good template in the test
itself, so a rule that stops firing fails too.

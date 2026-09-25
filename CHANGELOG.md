# Changelog

Notable changes to Experimently. Dates are release dates.

This file is written by hand, and is a carry-over from when this repository
was published by exporting a private one: release-please ran there, and its
commit links pointed at hashes this repository does not contain, because the
export rewrote history. Development moved here on 2026-09-25, so that no
longer applies and release-please can generate this file directly. Until it
does, entries below 0.2.2 are hand-written and the links in them are the
reason why.

## 0.2.0 — 2026-09-24

The first public release.

### Assignment now agrees across every implementation

The API and the Lambda assigned the same user to different variants. Both now
use one consistent hash — MD5 of `{user_id}:{key}`, first four bytes read
little-endian, divided by 2^32 — pinned to the golden vectors in
`tests/sdk-contract/golden-vectors.json` that the SDKs are tested against.
Verified over 2,000 users with zero differing buckets.

If you ran an earlier build, **assignments may change on upgrade** for users
the two paths disagreed about. Results gathered before and after are not
directly comparable for an experiment that was live across the upgrade.

### Security

- `gunicorn` 21.2.0 → 22.0.0, closing two request-smuggling advisories.
- Cleared the critical `handlebars` advisory and every high-severity one in
  the SDK lockfiles.
- Two security groups that were open to the whole internet are closed.
- The experiments list endpoint enforces the LIST permission.

### Deployment

- The CDK dependency cycle is broken, and a real `cdk synth` runs on every
  pull request rather than a stubbed one.
- Rollbacks go through CodeDeploy, and a traffic shift is approved rather than
  assumed.
- Resource names are deterministic and consistent across trees — the ECS
  cluster, the ECR repository and one Glue catalog instead of two.
- The published images no longer include an arm64 build that could not run.

### Dashboard

- A public homepage at `/`, with every dashboard route still behind
  authentication.
- A rate-limited login now reads as a rate-limited login rather than a dead
  API.

### Documentation

Every documentation link in the dashboard pointed at a site that had never
been built. The docs now resolve, and the tree they point into has been
checked: no broken links or anchors, no API endpoint that does not exist, and
no code example importing something that is not there.

## 0.1.0

Internal only; never published.

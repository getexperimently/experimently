# Changelog

Notable changes to Experimently. Dates are release dates.

This file is written by hand, and is a carry-over from when this repository
was published by exporting a private one: release-please ran there, and its
commit links pointed at hashes this repository does not contain, because the
export rewrote history. Development moved here on 2026-09-25, so that no
longer applies and release-please can generate this file directly. Until it
does, entries below 0.2.2 are hand-written and the links in them are the
reason why.

## [0.5.0](https://github.com/getexperimently/experimently/compare/v0.4.0...v0.5.0) (2026-09-26)


### Features

* **deploy:** check and pin the dashboard's running digest before cdk deploy ([#69](https://github.com/getexperimently/experimently/issues/69)) ([#170](https://github.com/getexperimently/experimently/issues/170)) ([837cc4f](https://github.com/getexperimently/experimently/commit/837cc4fb13ffe216ffcf571e1e71a18edf06ef46))
* **deploy:** deploy, migrate and roll back staging or prod from one path ([#138](https://github.com/getexperimently/experimently/issues/138), [#71](https://github.com/getexperimently/experimently/issues/71), [#70](https://github.com/getexperimently/experimently/issues/70), [#73](https://github.com/getexperimently/experimently/issues/73), [#140](https://github.com/getexperimently/experimently/issues/140), [#144](https://github.com/getexperimently/experimently/issues/144)) ([#160](https://github.com/getexperimently/experimently/issues/160)) ([d23964c](https://github.com/getexperimently/experimently/commit/d23964c9f41e2ad28d8a8b21f4afbc5409770ef7))
* **deploy:** the forward deploy shifts traffic and completes ([#143](https://github.com/getexperimently/experimently/issues/143)) ([#171](https://github.com/getexperimently/experimently/issues/171)) ([dbaadd2](https://github.com/getexperimently/experimently/commit/dbaadd2ea1190e37ccba197b095a6586b604b71f))


### Documentation

* close the two code fences left open at end of file ([#95](https://github.com/getexperimently/experimently/issues/95), [#96](https://github.com/getexperimently/experimently/issues/96)) ([#163](https://github.com/getexperimently/experimently/issues/163)) ([9ac7513](https://github.com/getexperimently/experimently/commit/9ac7513b998fef9fc389b0db58c2d766421c0ad9))
* example lines that do the wrong thing when pasted into zsh ([#98](https://github.com/getexperimently/experimently/issues/98), part) ([#176](https://github.com/getexperimently/experimently/issues/176)) ([1e48fe6](https://github.com/getexperimently/experimently/commit/1e48fe685e19fe3cb932a34f24164d14531260a4))
* name the language of every unlabelled code fence (Stream E pre) ([#175](https://github.com/getexperimently/experimently/issues/175)) ([2e32527](https://github.com/getexperimently/experimently/commit/2e32527604e4fd76d04e61b11ef7bc2f913ffd0c))
* remove the page about the maintainers' agent tooling ([#174](https://github.com/getexperimently/experimently/issues/174)) ([000afce](https://github.com/getexperimently/experimently/commit/000afced384d59542c54fee97a97cddac42d1db7))
* remove the Route 53 page, which describes hosting the marketing site ([#173](https://github.com/getexperimently/experimently/issues/173)) ([d782a46](https://github.com/getexperimently/experimently/commit/d782a46e97f834db8d32566d269a41b3c7f1e62b))
* say which packages are not published yet, and how to install from source ([#177](https://github.com/getexperimently/experimently/issues/177)) ([82c4511](https://github.com/getexperimently/experimently/commit/82c4511f9dc838f691483dd2af60143d3a591aac))
* the CDK runs the dashboard service; correct the pages that say it does not ([#69](https://github.com/getexperimently/experimently/issues/69), [#167](https://github.com/getexperimently/experimently/issues/167)) ([#169](https://github.com/getexperimently/experimently/issues/169)) ([a14ba38](https://github.com/getexperimently/experimently/commit/a14ba3864b5936a60395ccf4aa4841562c51bffb))

## [0.4.0](https://github.com/getexperimently/experimently/compare/v0.3.0...v0.4.0) (2026-09-26)


### ⚠ BREAKING CHANGES

* **infra:** an environment deployed before this change cannot be updated in place -- the ECS cluster rename changes an export the fargate stack imports, and CloudFormation refuses that. For each such environment: `cdk destroy --exclusively experimentation-fargate-<env>`, delete the log groups /ecs/experimentation-backend-<env> and /ecs/experimentation-dashboard-<env> that the old template retained, then `cdk deploy experimentation-compute-<env>`, `cdk deploy experimentation-fargate-<env>`, and `cdk deploy --all`. The analytics stack is not destroyed. See docs/self-hosting/cdk.md, "Moving an environment deployed before the rename".

### Features

* **infra:** dashboard ECS service and ALB path routing ([#69](https://github.com/getexperimently/experimently/issues/69)) ([#145](https://github.com/getexperimently/experimently/issues/145)) ([cdd8abc](https://github.com/getexperimently/experimently/commit/cdd8abce5bfdb74bbbd88a75adef2e05466a2b28))


### Bug Fixes

* **api:** the feature-flag list and detail no longer return 500 under production settings ([#152](https://github.com/getexperimently/experimently/issues/152)) ([d74dd4b](https://github.com/getexperimently/experimently/commit/d74dd4b85bf85e11add30fe391fcfc647f20f0af))
* **infra:** deployed tasks reach Aurora ([#78](https://github.com/getexperimently/experimently/issues/78), [#146](https://github.com/getexperimently/experimently/issues/146)) ([#156](https://github.com/getexperimently/experimently/issues/156)) ([8e2df8a](https://github.com/getexperimently/experimently/commit/8e2df8ac29db07f1990bf7fb518ce4474dd15273))
* **infra:** deployed tasks reach Redis over TLS ([#147](https://github.com/getexperimently/experimently/issues/147)) ([#159](https://github.com/getexperimently/experimently/issues/159)) ([1c32bbc](https://github.com/getexperimently/experimently/commit/1c32bbc40cd8b545a77bbd58bd67d66703b68458))
* **infra:** environments neither collide nor leave billed residue ([#139](https://github.com/getexperimently/experimently/issues/139), [#142](https://github.com/getexperimently/experimently/issues/142)) ([#157](https://github.com/getexperimently/experimently/issues/157)) ([3519958](https://github.com/getexperimently/experimently/commit/35199583b01c22a3b5089572ed13f257c2041a7c))
* **sso:** org_domain is normalised on write; docs/auth/sso.md describes the SSO that exists ([#151](https://github.com/getexperimently/experimently/issues/151)) ([9ae7ebd](https://github.com/getexperimently/experimently/commit/9ae7ebd3b0556ce7a0ea6edf8e7e07cbb7ea1d3f))

## [0.3.0](https://github.com/getexperimently/experimently/compare/v0.2.7...v0.3.0) (2026-09-26)


### Features

* **sso:** sign in with SSO from the dashboard ([#66](https://github.com/getexperimently/experimently/issues/66)) ([#135](https://github.com/getexperimently/experimently/issues/135)) ([aba5780](https://github.com/getexperimently/experimently/commit/aba57803f66033d2c8e390719bc2dcb8dadde4e5))


### Bug Fixes

* **sso:** accept email_verified sent as the string "true" ([#134](https://github.com/getexperimently/experimently/issues/134)) ([518eb93](https://github.com/getexperimently/experimently/commit/518eb9352d8a6c746f8611035ef6e7c3bcbe9958))

## [0.2.7](https://github.com/getexperimently/experimently/compare/v0.2.6...v0.2.7) (2026-09-26)


### Bug Fixes

* **api:** CORS origins are normalised, so BACKEND_CORS_ORIGINS matches ([#126](https://github.com/getexperimently/experimently/issues/126)) ([#132](https://github.com/getexperimently/experimently/issues/132)) ([db54023](https://github.com/getexperimently/experimently/commit/db540235582f8c747773da8392c28cdf2e205f3d))
* **sso:** OIDC sign-in bound to the browser that started it, with PKCE and a verified email ([#66](https://github.com/getexperimently/experimently/issues/66)) ([#129](https://github.com/getexperimently/experimently/issues/129)) ([0274a21](https://github.com/getexperimently/experimently/commit/0274a21d5dc9476180fda57a22922c5401eb65c6))

## [0.2.6](https://github.com/getexperimently/experimently/compare/v0.2.5...v0.2.6) (2026-09-26)


### Bug Fixes

* **api:** unhandled 500s carry CORS and request-id headers ([#72](https://github.com/getexperimently/experimently/issues/72)) ([#118](https://github.com/getexperimently/experimently/issues/118)) ([ab18a43](https://github.com/getexperimently/experimently/commit/ab18a433ed0df33f6e3a0b16fc0f90fe75304f92))
* **dashboard:** say "server error" with a request id, not "can't reach the API" ([#117](https://github.com/getexperimently/experimently/issues/117)) ([beffdf7](https://github.com/getexperimently/experimently/commit/beffdf79b36f042876face40f539d29cf56a9c6b))
* **sso:** signing in no longer changes an existing account's role or provisions outside the configured domain ([#128](https://github.com/getexperimently/experimently/issues/128)) ([32ecbab](https://github.com/getexperimently/experimently/commit/32ecbabf098c495b4bcf5d0612c4a4c460ab3205))
* **sso:** token-exchange and userinfo errors no longer echo provider or connection text ([#116](https://github.com/getexperimently/experimently/issues/116)) ([b8ba9ec](https://github.com/getexperimently/experimently/commit/b8ba9ecf03de8c303adec5d8de1eee6702217f71))


### Documentation

* **deploy:** describe the AWS deployment that exists ([#69](https://github.com/getexperimently/experimently/issues/69)) ([#124](https://github.com/getexperimently/experimently/issues/124)) ([ddf2c0b](https://github.com/getexperimently/experimently/commit/ddf2c0b20c1e2a232ae1d56bcd190745363c8e73))

## [0.2.5](https://github.com/getexperimently/experimently/compare/v0.2.4...v0.2.5) (2026-09-25)


### Bug Fixes

* **docs:** feature-flags/create.md describes the real flag contract ([#103](https://github.com/getexperimently/experimently/issues/103)) ([d0fb6d7](https://github.com/getexperimently/experimently/commit/d0fb6d73e9c7dbb1bb10109d2680401b33245744))
* **docs:** the quick-start runs as written, and pastes into zsh ([#99](https://github.com/getexperimently/experimently/issues/99)) ([d77c18e](https://github.com/getexperimently/experimently/commit/d77c18e9d9f76b4469ba42f61d29034492175c21))


### Documentation

* **feature-flags:** describe flag access by role, not ownership ([#104](https://github.com/getexperimently/experimently/issues/104)) ([d99c154](https://github.com/getexperimently/experimently/commit/d99c1545887d872aaaee06fc5e7b500ca4732da5))
* plan, review and sign-off before building ([#89](https://github.com/getexperimently/experimently/issues/89)) ([399bcce](https://github.com/getexperimently/experimently/commit/399bccedd9acb34765643b9ed69e14788126f287))

## [0.2.4](https://github.com/getexperimently/experimently/compare/v0.2.3...v0.2.4) (2026-09-25)


### Bug Fixes

* **feature-flags:** record the creator as owner and apply one access rule to every flag change ([#101](https://github.com/getexperimently/experimently/issues/101)) ([1fbd549](https://github.com/getexperimently/experimently/commit/1fbd5495d36b8bc7d68825f130414f17e3abc43c))

## [0.2.3](https://github.com/getexperimently/experimently/compare/v0.2.2...v0.2.3) (2026-09-25)


### Bug Fixes

* **security:** refuse a request whose Host header is not one of ours ([#61](https://github.com/getexperimently/experimently/issues/61)) ([2970ff7](https://github.com/getexperimently/experimently/commit/2970ff7a5aa95901983dde2cd8de8f33e3ae7d87))
* **security:** stop trusting every peer's X-Forwarded-* headers ([#62](https://github.com/getexperimently/experimently/issues/62)) ([db82ecc](https://github.com/getexperimently/experimently/commit/db82eccb2bdc3fdcff675893bc2071fc71e2cf13))
* **sso:** bound the OIDC state store ([#63](https://github.com/getexperimently/experimently/issues/63)) ([8764277](https://github.com/getexperimently/experimently/commit/876427705565367406a17c865ba8d92c11f32c08))
* **sso:** build the OIDC redirect_uri from configuration, not the request ([#59](https://github.com/getexperimently/experimently/issues/59)) ([e7a2f03](https://github.com/getexperimently/experimently/commit/e7a2f03bf55d304518ef7b46e481d5c8240cb8c5))


### Documentation

* the public changelog ([e5abf96](https://github.com/getexperimently/experimently/commit/e5abf96a182dd6cce3e0c765235b980fdeb0bea9))

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

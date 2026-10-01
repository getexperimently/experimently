# Changelog

Notable changes to Experimently. Dates are release dates.

This file is written by hand, and is a carry-over from when this repository
was published by exporting a private one: release-please ran there, and its
commit links pointed at hashes this repository does not contain, because the
export rewrote history. Development moved here on 2026-09-25, so that no
longer applies and release-please can generate this file directly. Until it
does, entries below 0.2.2 are hand-written and the links in them are the
reason why.

## [0.16.2](https://github.com/getexperimently/experimently/compare/v0.16.1...v0.16.2) (2026-10-01)


### Bug Fixes

* **api:** audit-log filters name the accepted values in their 400 ([#568](https://github.com/getexperimently/experimently/issues/568)) ([af712b1](https://github.com/getexperimently/experimently/commit/af712b1fe95c5f9e8939913f9ec2e8819f05b969))
* **api:** unexpected errors answer a fixed message with the request ID ([#567](https://github.com/getexperimently/experimently/issues/567)) ([d19741a](https://github.com/getexperimently/experimently/commit/d19741adda67ba6fdbd2e9699a4ed1ff09a6e390))

## [0.16.1](https://github.com/getexperimently/experimently/compare/v0.16.0...v0.16.1) (2026-10-01)


### Bug Fixes

* **api:** ETL job and crawler failures answer a fixed message with the request ID ([#563](https://github.com/getexperimently/experimently/issues/563)) ([cb791e2](https://github.com/getexperimently/experimently/commit/cb791e2f8d46f419379df33394272fd0db7e828b))
* **api:** wizard steps and experiment numbers out of range answer 422 ([#562](https://github.com/getexperimently/experimently/issues/562)) ([00e6dc7](https://github.com/getexperimently/experimently/commit/00e6dc716f4f00893f9e9a7d8282e3b650799d63))

## [0.16.0](https://github.com/getexperimently/experimently/compare/v0.15.0...v0.16.0) (2026-10-01)


### ⚠ BREAKING CHANGES

* **api:** an experiment's status changes only through start, pause, complete and archive ([#553](https://github.com/getexperimently/experimently/issues/553))
* **api:** experiment targeting rules are validated on create ([#539](https://github.com/getexperimently/experimently/issues/539))
* **api:** an experiment's targeting can be changed only while it is draft or paused ([#538](https://github.com/getexperimently/experimently/issues/538))

### Features

* **dashboard:** see and change who can join an experiment ([#556](https://github.com/getexperimently/experimently/issues/556)) ([3572180](https://github.com/getexperimently/experimently/commit/3572180f36d74cfaae38819bbbe37f9aa2e10935))


### Bug Fixes

* **api:** an experiment update refuses null for required fields ([#550](https://github.com/getexperimently/experimently/issues/550)) ([be77284](https://github.com/getexperimently/experimently/commit/be772847ca09f3c23d6d86c9d86f629a5cce2446))
* **api:** an experiment's status changes only through start, pause, complete and archive ([#553](https://github.com/getexperimently/experimently/issues/553)) ([d5fdea5](https://github.com/getexperimently/experimently/commit/d5fdea57c63967cc4f4b12183168bafcd09a40ae))
* **api:** an experiment's targeting can be changed only while it is draft or paused ([#538](https://github.com/getexperimently/experimently/issues/538)) ([63c4184](https://github.com/getexperimently/experimently/commit/63c4184b2cb4467576c5cac8daf4b6fa7bf28cae))
* **api:** experiment and results errors answer a fixed message with the request ID ([#545](https://github.com/getexperimently/experimently/issues/545)) ([15ab23b](https://github.com/getexperimently/experimently/commit/15ab23b10457fdc0b1c1590351c415c026c46779))
* **api:** experiment metric fields over their length answer 422 ([#555](https://github.com/getexperimently/experimently/issues/555)) ([0029f17](https://github.com/getexperimently/experimently/commit/0029f17f59c8c0f0bf70938111335621032a71ef))
* **api:** experiment metrics keep their type and can be replaced by name ([#561](https://github.com/getexperimently/experimently/issues/561)) ([3a33ddd](https://github.com/getexperimently/experimently/commit/3a33dddc1d6adb9e8e80fc14c00dab9b2052fbcb))
* **api:** experiment targeting rules are validated on create ([#539](https://github.com/getexperimently/experimently/issues/539)) ([33bd440](https://github.com/getexperimently/experimently/commit/33bd440bdf4ef6156622c9f8855baf6df6409a0d))
* **api:** SDK routes answer 422 for a NUL or unpaired surrogate in the path ([#548](https://github.com/getexperimently/experimently/issues/548)) ([8ab4df6](https://github.com/getexperimently/experimently/commit/8ab4df6266fb54a55398718d753d0bd0379a56b8))
* **api:** tracking requests with NUL or unpaired surrogate characters answer 422 ([#546](https://github.com/getexperimently/experimently/issues/546)) ([79e728a](https://github.com/getexperimently/experimently/commit/79e728acbc8280bb0e13c29f046425a555175f8a))

## [0.15.0](https://github.com/getexperimently/experimently/compare/v0.14.0...v0.15.0) (2026-09-30)


### ⚠ BREAKING CHANGES

* **api:** experiment targeting rules are validated on update ([#532](https://github.com/getexperimently/experimently/issues/532))

### Features

* **analysis:** mean-metric results from sufficient statistics ([#510](https://github.com/getexperimently/experimently/issues/510)) ([748839d](https://github.com/getexperimently/experimently/commit/748839d67759ab13509ac7531cbd50c3c5c61ae0))
* **warehouse:** mean metrics are analysed in warehouse runs ([#522](https://github.com/getexperimently/experimently/issues/522)) ([332b8db](https://github.com/getexperimently/experimently/commit/332b8db514fb3c47aaa4976ac9fb2abbb9be1b6d))


### Bug Fixes

* **api:** bad sample-size input answers 422, not 500 ([#528](https://github.com/getexperimently/experimently/issues/528)) ([59d5beb](https://github.com/getexperimently/experimently/commit/59d5beb911f9eaf0b03610d9ace2311ba87e945f))
* **api:** experiment targeting rules are validated on update ([#532](https://github.com/getexperimently/experimently/issues/532)) ([679eb40](https://github.com/getexperimently/experimently/commit/679eb40359658294479d900d6a1db92a99e77ee5))
* **api:** wizard drafts are per user; the wizard endpoints are deprecated ([#530](https://github.com/getexperimently/experimently/issues/530)) ([1307b7f](https://github.com/getexperimently/experimently/commit/1307b7f071e9a411f3904f045fbb27fab8e4d3c7))
* **deps:** PyJWT 2.15.1 ([#534](https://github.com/getexperimently/experimently/issues/534)) ([fef205b](https://github.com/getexperimently/experimently/commit/fef205b6df9ae0772a9f76325b0b57e23f3ac6e2))
* **deps:** urllib3 2.8.0 in both image locks ([#527](https://github.com/getexperimently/experimently/issues/527)) ([af54af2](https://github.com/getexperimently/experimently/commit/af54af2dc2d9be1ae7afa59203ba2755dcc84e94))

## [0.14.0](https://github.com/getexperimently/experimently/compare/v0.13.0...v0.14.0) (2026-09-30)


### ⚠ BREAKING CHANGES

* **users:** a client that changes the signed-in user's own password must use `POST /api/v1/users/me/password` with `current_password` and `new_password`. Sending your own `password` to `PUT /api/v1/users/{user_id}` or `PUT /api/v1/admin/users/{user_id}` now returns 403. An empty or weak `password` on those routes returns 422. `PUT /api/v1/admin/users/{user_id}` now resets another user's password.
* **infra:** API tasks no longer run migrations; the deploy's migration task does ([#499](https://github.com/getexperimently/experimently/issues/499))

### Features

* **infra:** API tasks no longer run migrations; the deploy's migration task does ([#499](https://github.com/getexperimently/experimently/issues/499)) ([a6401ec](https://github.com/getexperimently/experimently/commit/a6401ec81aa8e430493ff58a80ea34b94d738a53))


### Bug Fixes

* **api:** validation errors no longer repeat the submitted values ([#509](https://github.com/getexperimently/experimently/issues/509)) ([756e1f4](https://github.com/getexperimently/experimently/commit/756e1f4d114a5b27eacf9babab3c75432538c220))
* **bootstrap:** a first-admin password longer than 72 bytes is refused with a clear message ([#506](https://github.com/getexperimently/experimently/issues/506)) ([69eb5ca](https://github.com/getexperimently/experimently/commit/69eb5cafa7d0fd43df0406216c1490a790c564de))
* **demo:** the setup and teardown scripts and the rollout story work as documented ([#491](https://github.com/getexperimently/experimently/issues/491)) ([6088458](https://github.com/getexperimently/experimently/commit/6088458ab9bc1e239b9049b649c1ba557fc19eec))
* **docker:** the backend image installs the current OpenSSL packages ([#514](https://github.com/getexperimently/experimently/issues/514)) ([27fbaa7](https://github.com/getexperimently/experimently/commit/27fbaa70ccff390c69b1284d2e3f726421ab910c))
* **docs:** the doc-examples runner measures teardown and survives a dropped connection ([#494](https://github.com/getexperimently/experimently/issues/494)) ([baac924](https://github.com/getexperimently/experimently/commit/baac924f93f0a76df17b5a35361a4bcb846ca9f5))
* **infra:** the API task is given the counters table name and access to it ([#488](https://github.com/getexperimently/experimently/issues/488)) ([3b84714](https://github.com/getexperimently/experimently/commit/3b8471464809c9d12809d8ad34d8658ab46e893d))
* **users:** changing your own password requires the current password ([#516](https://github.com/getexperimently/experimently/issues/516)) ([34dae20](https://github.com/getexperimently/experimently/commit/34dae2085e76cabadb6ed7cdc0d20ec7e75ae283))


### Documentation

* **api:** /edge/bootstrap is deprecated in favour of the ruleset route ([#495](https://github.com/getexperimently/experimently/issues/495)) ([1cbadfd](https://github.com/getexperimently/experimently/commit/1cbadfdd48d0a6fca2cf44d5d834f0ec43978c7e))
* links to the API docs point at /api/v1/docs ([#493](https://github.com/getexperimently/experimently/issues/493)) ([3633da6](https://github.com/getexperimently/experimently/commit/3633da6e8fe3bf778e8dc6d70df6a7e8a08c5202))

## [0.13.0](https://github.com/getexperimently/experimently/compare/v0.12.0...v0.13.0) (2026-09-30)


### Features

* **api:** a setting for how often the experiment scheduler runs ([#486](https://github.com/getexperimently/experimently/issues/486)) ([d127407](https://github.com/getexperimently/experimently/commit/d127407b84f58539e32a1c4f6363a6466775302a))
* **db:** experiments gain a nullable resume_at column ([#477](https://github.com/getexperimently/experimently/issues/477)) ([2ea6580](https://github.com/getexperimently/experimently/commit/2ea65803d35c48ece136902a8ce5f80f847693cc))


### Bug Fixes

* **api:** a warehouse run's SQL is returned to analysts and above ([#468](https://github.com/getexperimently/experimently/issues/468)) ([94654a6](https://github.com/getexperimently/experimently/commit/94654a6accf19de3b4f79fc77f08f82fe5e2824a))
* **api:** admins and developers can schedule and delete any experiment ([#469](https://github.com/getexperimently/experimently/issues/469)) ([9c9715c](https://github.com/getexperimently/experimently/commit/9c9715ca30809f5df0442cb3ba2b0495f05a7411))
* **api:** audit records for experiment and flag changes are saved ([#475](https://github.com/getexperimently/experimently/issues/475)) ([b275b26](https://github.com/getexperimently/experimently/commit/b275b26bb78ba0ad3f3294dc41373e9893cb480d))
* **assignment:** mutual exclusion holds when a sibling experiment is activated ([#478](https://github.com/getexperimently/experimently/issues/478)) ([edb5071](https://github.com/getexperimently/experimently/commit/edb5071639b8dc973ae5f44ae72fae47825c7d41))
* **dashboard:** the View SQL button appears only for roles that can see it ([#472](https://github.com/getexperimently/experimently/issues/472)) ([04b8b4a](https://github.com/getexperimently/experimently/commit/04b8b4a4ccf5d4b19e6eb41343894a130d7d22c0))
* **experiments:** a paused experiment stays paused until it is started or a resume is scheduled ([#485](https://github.com/getexperimently/experimently/issues/485)) ([b363453](https://github.com/getexperimently/experimently/commit/b363453a6c2130cee562dded326caa8135fb11bd))


### Documentation

* CLAUDE.md states the bandit source rule and drops a note about a removed function ([#463](https://github.com/getexperimently/experimently/issues/463)) ([817cd8a](https://github.com/getexperimently/experimently/commit/817cd8ab2473781ce822a423640d939d32e7daaa))

## [0.12.0](https://github.com/getexperimently/experimently/compare/v0.11.0...v0.12.0) (2026-09-29)


### Features

* **dashboard:** run a warehouse analysis and read its results (beta) ([#421](https://github.com/getexperimently/experimently/issues/421)) ([2b5931a](https://github.com/getexperimently/experimently/commit/2b5931a1bef76ce6dc088a7ee9f9813f5ccfe599))
* **dashboard:** warehouse connections and metric sources (beta) ([#420](https://github.com/getexperimently/experimently/issues/420)) ([ca44cef](https://github.com/getexperimently/experimently/commit/ca44cef8c626e9552ef883765cc7b0bfc311df6e))
* **deploy:** refuse a deploy while an API 5xx alarm is firing ([#366](https://github.com/getexperimently/experimently/issues/366)) ([1366f1d](https://github.com/getexperimently/experimently/commit/1366f1dab9230012ead9d692315c42fbb86ff592))
* **sdk:** the JavaScript SDK evaluates flags locally from the ruleset (beta) ([#368](https://github.com/getexperimently/experimently/issues/368)) ([4263f60](https://github.com/getexperimently/experimently/commit/4263f60a90e54a3b193a1e64d73ec0bcf96eb8f6))
* **sdk:** the Python SDK evaluates flags locally from the ruleset (beta) ([#374](https://github.com/getexperimently/experimently/issues/374)) ([817963a](https://github.com/getexperimently/experimently/commit/817963a626f76fca5cf783ef77240563c52a7173))
* **warehouse:** BigQuery connector, disabled until verified ([#371](https://github.com/getexperimently/experimently/issues/371)) ([4137f8a](https://github.com/getexperimently/experimently/commit/4137f8a001126966ee0a193b3a3a2253a9e3af8d))
* **warehouse:** Snowflake connector with key-pair sign-in, disabled until verified ([#380](https://github.com/getexperimently/experimently/issues/380)) ([d9f2f91](https://github.com/getexperimently/experimently/commit/d9f2f91da9398a6cb1926d90e9604f43038864f7))
* **warehouse:** warehouse analyses for proportion metrics with SRM (beta) ([#412](https://github.com/getexperimently/experimently/issues/412)) ([01a96fc](https://github.com/getexperimently/experimently/commit/01a96fc297541ff022b514f87690864abbb902ac))


### Bug Fixes

* **api:** a failed lookup in a batch no longer fails the items after it ([#414](https://github.com/getexperimently/experimently/issues/414)) ([c3bbaca](https://github.com/getexperimently/experimently/commit/c3bbacab036e29c147e196a3719c0230ad1a505f))
* **api:** analysts and viewers can read every experiment's results, and change none ([#460](https://github.com/getexperimently/experimently/issues/460)) ([86aa27a](https://github.com/getexperimently/experimently/commit/86aa27a57a6b723de4bad78a2c36db0c5e6f0ea0))
* **api:** creating an experiment whose key is taken answers 409 with a plain message ([#395](https://github.com/getexperimently/experimently/issues/395)) ([90d48f4](https://github.com/getexperimently/experimently/commit/90d48f4177c7d2e42f0c42edd32dcdfbdbb8845d))
* **api:** experiment owners and permitted roles can open an experiment again ([#451](https://github.com/getexperimently/experimently/issues/451)) ([7342f48](https://github.com/getexperimently/experimently/commit/7342f48aec23197a8495297c91f0943d6ccc8410))
* **api:** experiment routes work with the cache enabled ([#437](https://github.com/getexperimently/experimently/issues/437)) ([ae5f091](https://github.com/getexperimently/experimently/commit/ae5f091e60e7d1fb3a83599aaf40f7d90005292d))
* **api:** feature-flag routes work with the flag cache enabled ([#427](https://github.com/getexperimently/experimently/issues/427)) ([493e782](https://github.com/getexperimently/experimently/commit/493e7824448306f3c3a9a7b4453ddaf07d382ed2))
* **api:** integer bounds in the API description fit a JSON number ([#462](https://github.com/getexperimently/experimently/issues/462)) ([d5f852b](https://github.com/getexperimently/experimently/commit/d5f852b241e73edfc6ef8bf1f5302c0ad2276796))
* **api:** tracking and error-report failures answer a short message with the request ID ([#411](https://github.com/getexperimently/experimently/issues/411)) ([9e96ba5](https://github.com/getexperimently/experimently/commit/9e96ba58b89c860a57d5af06e0a2c452ef25d7c2))
* **auth:** Cognito-only auth routes answer 404 when AUTH_PROVIDER is not cognito ([#397](https://github.com/getexperimently/experimently/issues/397)) ([e8a16f8](https://github.com/getexperimently/experimently/commit/e8a16f82c4c4177a598e6d2f81efcbdb50803c07))
* **bandit:** a partial DynamoDB count no longer replaces the complete PostgreSQL count ([#430](https://github.com/getexperimently/experimently/issues/430)) ([fb3f629](https://github.com/getexperimently/experimently/commit/fb3f629c3e9f1ea8348da57350ee77bf45c62758))
* **ci:** regression-guard no longer fails without a merge base or blocks on a cancelled run ([#418](https://github.com/getexperimently/experimently/issues/418)) ([d2c0afc](https://github.com/getexperimently/experimently/commit/d2c0afc9c3a73664450c029f67ebc2b3204d63d1))
* **dashboard:** creating an experiment keeps your answers on a sign-in or key error ([#415](https://github.com/getexperimently/experimently/issues/415)) ([6fd886c](https://github.com/getexperimently/experimently/commit/6fd886c3e3e9a170fa21e1669720a2e827b2e93f))
* **dashboard:** show the request ID once when the error message already includes it ([#403](https://github.com/getexperimently/experimently/issues/403)) ([da58d9a](https://github.com/getexperimently/experimently/commit/da58d9a906326f393db14f77d3b02b11f2aaf82a))
* **dashboard:** the experiment page offers changes only to roles that can make them ([#461](https://github.com/getexperimently/experimently/issues/461)) ([3e6bf38](https://github.com/getexperimently/experimently/commit/3e6bf3800ad3753469c7d4b73bdd46d965d9dbf8))
* **deploy:** rollback fails loudly when a stopped deployment does not finish ([bc7bb07](https://github.com/getexperimently/experimently/commit/bc7bb0764fe908d6bff5618dc1f76624b84a6089))
* **logging:** evaluation and assignment no longer log the user id ([#365](https://github.com/getexperimently/experimently/issues/365)) ([a254b59](https://github.com/getexperimently/experimently/commit/a254b59e53f86aa607150541721edb3a90069112))
* **rules:** contains_all and contains_any do not match a non-list attribute instead of raising ([#423](https://github.com/getexperimently/experimently/issues/423)) ([a66db26](https://github.com/getexperimently/experimently/commit/a66db263dc682de10cbe4a0a7f4aed207a6b06cf))
* **sdk:** the OpenFeature provider takes @openfeature/server-sdk as a peer dependency ([#367](https://github.com/getexperimently/experimently/issues/367)) ([2b1d6b2](https://github.com/getexperimently/experimently/commit/2b1d6b2c97d30edf0736618331abb832bf8c6004))
* **tests:** the rollout schedule API tests use the configured database ([#360](https://github.com/getexperimently/experimently/issues/360)) ([e45d7c1](https://github.com/getexperimently/experimently/commit/e45d7c156b98c4cefadfd2bb249b63b0cb496438))
* **workspaces:** show the invitation link after creating it, and fill in the invitation page ([#381](https://github.com/getexperimently/experimently/issues/381)) ([33a1a71](https://github.com/getexperimently/experimently/commit/33a1a71723da86ab792fa1a42c2f261826723688))
* **workspaces:** the invitation preview shows the invited address in full only to that account ([#372](https://github.com/getexperimently/experimently/issues/372)) ([59536d9](https://github.com/getexperimently/experimently/commit/59536d949eec42867b7d06aa95a368d320efc591))


### Dependencies

* **backend:** pytest 9 and pytest-asyncio 1.3 ([#359](https://github.com/getexperimently/experimently/issues/359)) ([f7f8de8](https://github.com/getexperimently/experimently/commit/f7f8de8cb5b866e7c096d0f34b5b9929a8c40f76))


### Documentation

* **deploy:** disaster-recovery.md describes what the CDK actually creates ([bc7bb07](https://github.com/getexperimently/experimently/commit/bc7bb0764fe908d6bff5618dc1f76624b84a6089))
* **llm:** the quickstart's completion steps are secret skips, not bug [#196](https://github.com/getexperimently/experimently/issues/196) ([bc7bb07](https://github.com/getexperimently/experimently/commit/bc7bb0764fe908d6bff5618dc1f76624b84a6089))
* pages describe the infrastructure the stacks actually create ([bc7bb07](https://github.com/getexperimently/experimently/commit/bc7bb0764fe908d6bff5618dc1f76624b84a6089))
* the FAQ describes dashboard deploys, and shell examples paste cleanly into zsh ([#422](https://github.com/getexperimently/experimently/issues/422)) ([664eab1](https://github.com/getexperimently/experimently/commit/664eab1cbe9cdccb61517020effc80fe5da31905))
* the secrets-management rotation steps render as a code block again ([#459](https://github.com/getexperimently/experimently/issues/459)) ([ddb2d31](https://github.com/getexperimently/experimently/commit/ddb2d311dff11981e5585e59dd407c6aa5e4f749))

## [0.11.0](https://github.com/getexperimently/experimently/compare/v0.10.0...v0.11.0) (2026-09-28)


### ⚠ BREAKING CHANGES

* **warehouse:** warehouse analysis tables; saved warehouse connections are removed ([#322](https://github.com/getexperimently/experimently/issues/322))
* **api:** a staging or production API with neither `CORS_ORIGINS` nor `BACKEND_CORS_ORIGINS` set no longer allows the localhost origins. A browser client on another origin (a local dashboard or demo app, or a site running the browser SDK) needs its origin in `CORS_ORIGINS` (Helm: `corsOrigins`), or in `DASHBOARD_ORIGINS` for a dashboard on its own host. Cross-origin responses no longer carry `Access-Control-Allow-Credentials`. Development and test are unchanged.
* **api:** POST /api/v1/openfeature/evaluate and POST /api/v1/openfeature/bulk-evaluate are removed and now answer 404. They could not evaluate an existing flag (they read a FeatureFlag.enabled attribute the model does not have), and neither provider called them. The OpenFeature providers use GET /api/v1/feature-flags/evaluate/{key} and are unaffected. GET /api/v1/openfeature/flags is deprecated and unchanged.

### Features

* **modules:** a bounded outbound layer for warehouse connectors ([#321](https://github.com/getexperimently/experimently/issues/321)) ([24b9958](https://github.com/getexperimently/experimently/commit/24b995842073fa52abdbc0cbb56bdd757125abdd))
* **tracking:** record locally evaluated flags so safety monitoring keeps its denominator (beta) ([#226](https://github.com/getexperimently/experimently/issues/226)) ([#296](https://github.com/getexperimently/experimently/issues/296)) ([8a64d22](https://github.com/getexperimently/experimently/commit/8a64d22725c91e5ee144e52cb8d47f8d06cf54ae))
* **warehouse:** warehouse analysis tables; saved warehouse connections are removed ([#322](https://github.com/getexperimently/experimently/issues/322)) ([5c5720f](https://github.com/getexperimently/experimently/commit/5c5720fd3776bc2867cf910f5ffdc850c2509401))


### Bug Fixes

* **analysis:** count converting users without joining events to assignments ([#356](https://github.com/getexperimently/experimently/issues/356)) ([bcd4a01](https://github.com/getexperimently/experimently/commit/bcd4a011bf4328b2ba3c7f14add9b2812556982b))
* **analysis:** every endpoint counts converting users, not conversion events ([#337](https://github.com/getexperimently/experimently/issues/337)) ([ca3e7b9](https://github.com/getexperimently/experimently/commit/ca3e7b9dc8395e5ee3940ba2ba05bc49aa2c97bb))
* **api:** remove the OpenFeature evaluate routes, which never returned a result, and deprecate /openfeature/flags ([#345](https://github.com/getexperimently/experimently/issues/345)) ([2373367](https://github.com/getexperimently/experimently/commit/2373367b8b8bbf18be9bf6b57cefafa2b4fb1be3))
* **api:** staging and production allow only configured browser origins ([#349](https://github.com/getexperimently/experimently/issues/349)) ([07a408c](https://github.com/getexperimently/experimently/commit/07a408c9bcd481933867e28425e6f8893a412004))
* **deploy:** workflow runs never print the AWS account ID ([#311](https://github.com/getexperimently/experimently/issues/311)) ([1812f6e](https://github.com/getexperimently/experimently/commit/1812f6e966a739f7b957ce88be63cc161dba1a1f))
* **sso:** SAML sign-in errors carry a fixed message, and the docs say SAML sign-in is not available yet ([#346](https://github.com/getexperimently/experimently/issues/346)) ([91f7e0f](https://github.com/getexperimently/experimently/commit/91f7e0f515527db511325125afc6adc582ce333b))
* **workspaces:** an invite can be accepted only by the account it was sent to ([#348](https://github.com/getexperimently/experimently/issues/348)) ([d5ec4ae](https://github.com/getexperimently/experimently/commit/d5ec4ae4efb8ff696203214f1e11e74b6c93de8b))

## [0.10.0](https://github.com/getexperimently/experimently/compare/v0.9.0...v0.10.0) (2026-09-28)


### ⚠ BREAKING CHANGES

* **users:** Non-superusers now get 403 when a PUT /api/v1/users/{id} request changes email or username. Administrators change them through /api/v1/admin/users/{id}.

### Features

* **dashboard:** results show the beta notice the API sends ([#314](https://github.com/getexperimently/experimently/issues/314)) ([eceba3f](https://github.com/getexperimently/experimently/commit/eceba3f156324869a3be9389ffda5a6ea22f8c24))
* **infra:** alarms email a required address, and the rollback alarms announce themselves ([#308](https://github.com/getexperimently/experimently/issues/308)) ([9e50305](https://github.com/getexperimently/experimently/commit/9e503053eb8a11044806e171b965c8ec5f403291))
* **infra:** staging runs one small Redis node ([#301](https://github.com/getexperimently/experimently/issues/301)) ([c400adc](https://github.com/getexperimently/experimently/commit/c400adc5a35b853e7c8d5d2101138ee13772a7e4))
* **modules:** a key-list setting and helper for encrypting stored credentials ([#317](https://github.com/getexperimently/experimently/issues/317)) ([4a08a34](https://github.com/getexperimently/experimently/commit/4a08a3487f261de760e8b5a7048d4902c884dbdf))
* **sdk:** assignments carry whether the user was enrolled and why ([#315](https://github.com/getexperimently/experimently/issues/315)) ([c9b3023](https://github.com/getexperimently/experimently/commit/c9b3023e1ef8f38a223032bbb81ecd235275c1a1))


### Bug Fixes

* **api-keys:** only roles that can change flags can create server-side evaluation keys ([#305](https://github.com/getexperimently/experimently/issues/305)) ([3d459e2](https://github.com/getexperimently/experimently/commit/3d459e2cf156fd0776e71d1c0f8724ec00ae9194))
* **config:** the API starts only with an explicit ENVIRONMENT, and a weak first-admin password is refused outside development ([#310](https://github.com/getexperimently/experimently/issues/310)) ([9d27c3f](https://github.com/getexperimently/experimently/commit/9d27c3f95cf8c2acca44a1a61f48f61dc1d232a9))
* **users:** only a superuser can change a user's email or username ([#340](https://github.com/getexperimently/experimently/issues/340)) ([03b0c20](https://github.com/getexperimently/experimently/commit/03b0c2066d41bfeb1ea25720eec7c57362696b0c))

## [0.9.0](https://github.com/getexperimently/experimently/compare/v0.8.0...v0.9.0) (2026-09-28)


### ⚠ BREAKING CHANGES

* **modules:** remove the warehouse endpoints and the ad-hoc ETL query endpoint ([#318](https://github.com/getexperimently/experimently/issues/318))

### Bug Fixes

* **deploy:** workflow AWS sessions last as long as the job can ([#302](https://github.com/getexperimently/experimently/issues/302)) ([cbf1db8](https://github.com/getexperimently/experimently/commit/cbf1db81b7c7a6c85d60e3333a4080b474681467))
* **modules:** remove the warehouse endpoints and the ad-hoc ETL query endpoint ([#318](https://github.com/getexperimently/experimently/issues/318)) ([fdfae20](https://github.com/getexperimently/experimently/commit/fdfae2047f7a48df27a06e2f3bc46c15be071685))

## [0.8.0](https://github.com/getexperimently/experimently/compare/v0.7.0...v0.8.0) (2026-09-27)


### Features

* **chart:** a Helm chart for self-hosting, with render-time checks ([#257](https://github.com/getexperimently/experimently/issues/257)) ([70a5db3](https://github.com/getexperimently/experimently/commit/70a5db39b92f8edc454fec53fc704e05e0092b9c))
* **deploy:** a production compose file that runs the published images ([#252](https://github.com/getexperimently/experimently/issues/252)) ([634da12](https://github.com/getexperimently/experimently/commit/634da12ad9c828498db9fb25f1b73fda0f6298f8))


### Bug Fixes

* **api-keys:** one scope parser, and the dashboard stops offering scopes nothing enforces ([#243](https://github.com/getexperimently/experimently/issues/243)) ([8f4e507](https://github.com/getexperimently/experimently/commit/8f4e507af196866e5fc4c916ced7698b099bf2bb))
* **api:** a rejected Host names the setting that fixes it, and the dashboard explains it ([#274](https://github.com/getexperimently/experimently/issues/274)) ([1eaf65c](https://github.com/getexperimently/experimently/commit/1eaf65c973232d399e8cbba6c6ff5e993713e0e3))
* **api:** Bayesian analysis can be enabled through the experiments API ([#254](https://github.com/getexperimently/experimently/issues/254)) ([24b6215](https://github.com/getexperimently/experimently/commit/24b621580676f2c57d4754479fd3afaba6a9255e))
* **api:** CUPED and interaction analysis say what they compute, and are marked beta ([#280](https://github.com/getexperimently/experimently/issues/280)) ([bc770f0](https://github.com/getexperimently/experimently/commit/bc770f0855296f9a6303252aaf50cdbf006ea000))
* **api:** production start-up lists every missing setting at once ([#277](https://github.com/getexperimently/experimently/issues/277)) ([74371a0](https://github.com/getexperimently/experimently/commit/74371a0f2f6fe13c95f2b52866ed95ed9c10aaad))
* **api:** results breakdowns name each variant and know which is the control ([#276](https://github.com/getexperimently/experimently/issues/276)) ([4b3643e](https://github.com/getexperimently/experimently/commit/4b3643e7e515cb7eeffc2141ef7895543dd8a1a4))
* **api:** sequential analysis honours alpha and stops returning a planned-looks table it does not compute ([#282](https://github.com/getexperimently/experimently/issues/282)) ([860d891](https://github.com/getexperimently/experimently/commit/860d891da7621840eddd02747e6dd4e3f24f9af3))
* **config:** TESTING cannot be combined with a staging or production environment, and the image refuses ENVIRONMENT=test ([#284](https://github.com/getexperimently/experimently/issues/284)) ([c885f02](https://github.com/getexperimently/experimently/commit/c885f023fbba1d9c7f2c7a7a63b8c08078465a38))
* **db:** an older image meeting a newer database says so, and never advises deleting alembic_version rows ([#250](https://github.com/getexperimently/experimently/issues/250)) ([2232cc2](https://github.com/getexperimently/experimently/commit/2232cc29b33528e03d602257cb695ecbc2722ff2))
* **deploy:** a transient AWS error no longer ends a rollback mid-wait ([#215](https://github.com/getexperimently/experimently/issues/215)) ([#224](https://github.com/getexperimently/experimently/issues/224)) ([5944322](https://github.com/getexperimently/experimently/commit/5944322b2b40b272973bb59aa1c15c94d72c202d))
* **deps:** the API image includes the Anthropic and OpenAI SDKs its LLM features import ([#253](https://github.com/getexperimently/experimently/issues/253)) ([8059755](https://github.com/getexperimently/experimently/commit/80597554d95c8538a57aeb900d142a16881f7fec))
* **infra:** Aurora uses an orderable engine version and valid memory settings ([#300](https://github.com/getexperimently/experimently/issues/300)) ([71932b4](https://github.com/getexperimently/experimently/commit/71932b40c17078778a652e8411ca88f98996f2cb))
* **llm:** the Gemini provider calls the REST API instead of a package the image does not ship ([#275](https://github.com/getexperimently/experimently/issues/275)) ([b1db69f](https://github.com/getexperimently/experimently/commit/b1db69fdad1ffe761448d7f5e6d559a8ba9f5057))
* **redis:** every Redis client uses REDIS_PASSWORD ([#248](https://github.com/getexperimently/experimently/issues/248)) ([76cca1a](https://github.com/getexperimently/experimently/commit/76cca1ad8aa40442f56f22ed611bfe04977a709f))
* **release:** release notes and image labels describe what is actually published ([#246](https://github.com/getexperimently/experimently/issues/246)) ([eb6cc53](https://github.com/getexperimently/experimently/commit/eb6cc5362c83a95d24b831e34b20a9d5a323e12c))
* **rules:** evaluation no longer logs user attribute values ([#273](https://github.com/getexperimently/experimently/issues/273)) ([5e687d8](https://github.com/getexperimently/experimently/commit/5e687d8be2b14edbadd8e42e7ac68af60a68ed67))
* **safety:** count errors in the database, and time and size-bound client error reports ([#306](https://github.com/getexperimently/experimently/issues/306)) ([fd9c419](https://github.com/getexperimently/experimently/commit/fd9c419ecdc7c14e21b52527ac251d4f736b65f0))
* **seed:** demo seeds run only in development and test ([#249](https://github.com/getexperimently/experimently/issues/249)) ([c8ecdc3](https://github.com/getexperimently/experimently/commit/c8ecdc3bab8acfb2a512cafb65fe7e7437e0fd72))
* **test:** the data seeder fails loudly and reports what the platform stored ([#245](https://github.com/getexperimently/experimently/issues/245)) ([6df9e10](https://github.com/getexperimently/experimently/commit/6df9e1017df462298379464423742954f9889a9f))
* **workspaces:** enforce owner-only role changes and scope key operations to their workspace ([#266](https://github.com/getexperimently/experimently/issues/266)) ([9454dde](https://github.com/getexperimently/experimently/commit/9454ddee827da51fd94918bcf183ea9ebf0f8691))


### Documentation

* **workspaces:** describe workspaces as grouping, not an access boundary ([#262](https://github.com/getexperimently/experimently/issues/262)) ([a350ba2](https://github.com/getexperimently/experimently/commit/a350ba20e429ba453895f1ca6cfeb236eb46d77f))

## [0.7.0](https://github.com/getexperimently/experimently/compare/v0.6.0...v0.7.0) (2026-09-27)


### ⚠ BREAKING CHANGES

* **rules:** regex targeting conditions (`regex` in the dashboard, `match_regex` in the rules engine) now use RE2 syntax (https://github.com/google/re2/wiki/Syntax), which differs from Python's:
    - `\w`, `\d`, `\s` and `\b` match ASCII only.
    - `$` matches only at the very end of the value, not before a final
    newline.
    - These are refused: lookahead and lookbehind, backreferences, `\Z`,
    `(?x)`, `(?u)`, `(?a)`, `\N{...}`, counted repetitions over 1000, and
    very large Unicode repetitions such as `[\p{L}\p{N}]{1,300}`.
    - Values longer than 256 characters are not evaluated.

    When a stored pattern is refused, or a value is longer than 256 characters
    or cannot be encoded as UTF-8, the rules holding it are not applied: the
    feature flag evaluates disabled with reason "error" (no fall-through to its
    rollout percentage), the user is ineligible for the experiment and gets the
    control variant, and the user is not a member of the segment.

    After upgrading, run `python -m backend.scripts.check_regex_rules` to list
    stored patterns that RE2 refuses or that use `\w`, `\d`, `\s`, `\b` or `$`.

### Bug Fixes

* **api:** export endpoints share one limit of 10 requests a minute per client ([#261](https://github.com/getexperimently/experimently/issues/261)) ([00870e4](https://github.com/getexperimently/experimently/commit/00870e4870ff3e13e0a2ac2265f5ba5e4f8efb84))
* **api:** exports carry the same results as the results API, and the report honours format=csv ([#259](https://github.com/getexperimently/experimently/issues/259)) ([c11a4a0](https://github.com/getexperimently/experimently/commit/c11a4a04415a4d23f50dec796f1ac757e27b8648))
* **rules:** regex conditions use RE2 syntax ([#260](https://github.com/getexperimently/experimently/issues/260)) ([5a3c940](https://github.com/getexperimently/experimently/commit/5a3c940dae073e377fe994bcd628c6436220e435))
* **segments:** audience preview rejects oversized rulesets ([#268](https://github.com/getexperimently/experimently/issues/268)) ([b654656](https://github.com/getexperimently/experimently/commit/b6546563856cf511173c292d751ce8247b5d2c1b))

## [0.6.0](https://github.com/getexperimently/experimently/compare/v0.5.0...v0.6.0) (2026-09-27)


### Features

* **deploy:** an ECS rolling rollout script that cannot mistake a circuit-breaker rollback for success ([#69](https://github.com/getexperimently/experimently/issues/69)) ([#172](https://github.com/getexperimently/experimently/issues/172)) ([38e8d14](https://github.com/getexperimently/experimently/commit/38e8d14e11990a6969157f2a2bb7e46570270fe2))
* **docs:** every documentation page with a shell example is under the runner's contract (E0a-1) ([#179](https://github.com/getexperimently/experimently/issues/179)) ([b16c2ab](https://github.com/getexperimently/experimently/commit/b16c2ab4d5dc646df3b87b800d1c709d0c270d0b))


### Bug Fixes

* **api:** audit log reads follow the role table ([#258](https://github.com/getexperimently/experimently/issues/258)) ([c1f559a](https://github.com/getexperimently/experimently/commit/c1f559a3572a49b332786b050968671ae6b3ef11))
* **api:** experiments report their bandit optimization type ([#197](https://github.com/getexperimently/experimently/issues/197)) ([#204](https://github.com/getexperimently/experimently/issues/204)) ([5ef8513](https://github.com/getexperimently/experimently/commit/5ef851324a8f347975cd2c38a3fdb27f5268ed6f))
* **api:** record when an API key was last used ([#198](https://github.com/getexperimently/experimently/issues/198)) ([#206](https://github.com/getexperimently/experimently/issues/206)) ([14d42ec](https://github.com/getexperimently/experimently/commit/14d42ec182c1b150744fb34c19b4e029769399fe))
* **deploy:** a crash in the serving check reads as "could not tell", not "not yet" ([#182](https://github.com/getexperimently/experimently/issues/182)) ([827671c](https://github.com/getexperimently/experimently/commit/827671ca12709ff8418ccd8b1118bbfb4e8ff88a))
* **deploy:** Rollback never reports success it did not achieve, and never stops CodeDeploy's own rollback ([#148](https://github.com/getexperimently/experimently/issues/148) PR-1) ([#214](https://github.com/getexperimently/experimently/issues/214)) ([18cf907](https://github.com/getexperimently/experimently/commit/18cf907559054e4357202c00713d067e16483869))


### Documentation

* deployment examples that do the wrong thing when pasted into zsh ([#98](https://github.com/getexperimently/experimently/issues/98), part) ([#187](https://github.com/getexperimently/experimently/issues/187)) ([ce5e7ad](https://github.com/getexperimently/experimently/commit/ce5e7ad63e66a5e15f8ff60c74314b197406ddbe))
* more API pages run their examples (Stream E batch 4) ([#223](https://github.com/getexperimently/experimently/issues/223)) ([dbad65e](https://github.com/getexperimently/experimently/commit/dbad65e59a02cf50541c7b27f53caef033156ff3))
* replace the internal incident-response plan with a short page for self-hosters ([#189](https://github.com/getexperimently/experimently/issues/189)) ([bf8ea56](https://github.com/getexperimently/experimently/commit/bf8ea560fe7ea7d8536bc7fea716ccb11a948ac3))
* the demo READMEs are under the documentation checks (Stream E batch 2) ([#194](https://github.com/getexperimently/experimently/issues/194)) ([4ca6b79](https://github.com/getexperimently/experimently/commit/4ca6b799f13036ea30b2690cb1b5055277e01fbf))
* the first integration pages run their examples (Stream E batch 3) ([#199](https://github.com/getexperimently/experimently/issues/199)) ([3b63f03](https://github.com/getexperimently/experimently/commit/3b63f033fd32f2787ee756b5a0d7644ac1d16af2))
* the front-door pages run their examples (Stream E batch 1) ([#188](https://github.com/getexperimently/experimently/issues/188)) ([29d2a8c](https://github.com/getexperimently/experimently/commit/29d2a8cd29c665b767241e27810edc9d27ba39b1))

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

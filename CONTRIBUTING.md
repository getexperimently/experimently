# Contributing to Experimently

Thanks for wanting to help. This document is the short version of everything you
need: how to sign your work, how to run the stack, and where code lives.

## Before you start

- **Bugs and features**: open an issue first for anything non-trivial, so we can
  agree on the shape before you spend an evening on it. Small fixes — a typo, a
  wrong URL, a one-line bug — can go straight to a pull request.
- **Security problems**: do **not** open an issue. Follow
  [SECURITY.md](SECURITY.md). A public issue for a vulnerability is itself the
  disclosure.
- **Conduct**: by participating you agree to the
  [Code of Conduct](CODE_OF_CONDUCT.md).

## Developer Certificate of Origin (DCO)

Experimently uses the [Developer Certificate of Origin](https://developercertificate.org/),
not a CLA. You keep the copyright in your contribution; you certify that you
have the right to submit it under the licence of the file you are changing.
There is no paperwork and no copyright assignment, anywhere in the tree.

Sign off every commit:

```bash
git commit -s -m "Fix flag evaluation for empty targeting rules"
```

`-s` appends a line to the commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

It must match the author of the commit. To set it up once:

```bash
git config user.name  "Your Name"
git config user.email "your.email@example.com"
```

To sign off a branch you already wrote:

```bash
git rebase --signoff main
```

A pull request with unsigned commits will be blocked by the DCO check until every
commit carries a sign-off.

**Licence of your contribution.** Everything except `sdk/` — the backend, the
optional modules under `modules/`, the dashboard, the docs — is
[Apache-2.0](LICENSE), and a contribution to any of it is made under Apache-2.0
(section 5 of the licence says exactly that). A contribution to `sdk/` is made
under [MIT](sdk/LICENSE). The `LICENSE` file covering the directory you touch is
the licence you are contributing under.

## Running the stack

Everything runs from the repository root. Prerequisites: Python 3.11, Node 22
(see `.nvmrc`), Docker.

```bash
make venv install     # virtualenv + backend deps, then frontend deps
make dev              # Postgres + Redis, bootstrap the schema and the first
                      # admin, then the API on :8000 with reload
make web              # in a second shell: the dashboard on :3100
```

`make dev` runs `AUTH_PROVIDER=local uvicorn backend.app.main:app` after
`docker compose up -d --wait postgres redis` and
`python -m backend.app.db.bootstrap`. Bootstrap is idempotent: it creates the
schema from the models and stamps the alembic heads on a fresh database, and runs
`alembic upgrade heads` on an existing one. Do not run `alembic upgrade heads` on
an empty database — the historical migration chain cannot replay from nothing.

`heads` is plural throughout: a full checkout has two — the core chain and the
`modules` branch, kept separate so that deleting `modules/` leaves a consistent
core chain. Do not merge them; a new revision names the head it extends
(`alembic revision --autogenerate --head modules@head -m "..."`).

Other useful targets — `make help` lists them all:

| Target | What it does |
|---|---|
| `make up` | The core stack in Docker (API, dashboard, Postgres, Redis) |
| `make demo` | The whole stack including the ShopLab and StreamPulse demo apps |
| `make down` | Stop everything and drop the volumes |
| `make bootstrap` | Create the schema and the first administrator |
| `make openapi` | Regenerate the OpenAPI fixtures: the frontend URL guard's and the two stable snapshots |
| `make core-build` | Prove the core profile stands alone (copy, delete `modules/`, rebuild, test) |
| `make full-build` | The same sequence on the full tree, `modules/` included |
| `make lock` | Regenerate both requirements locks (what the two API images install) |

### Tests

```bash
make test             # what a pull request must pass: backend + frontend
make test-unit        # backend unit tests (most need Postgres too)
make test-integration # backend integration tests (needs Postgres on localhost:5432)
make test-modules     # the modules' own suite (needs modules/requirements.txt installed)
make test-frontend    # dashboard jest tests, tsc --noEmit, production build
make test-sdk         # cross-SDK golden-vector contract tests
```

Both suites need PostgreSQL on **localhost:5432**. `make db` starts it. The unit
suite is not database-free despite the name: 26 of its files take the
`db_session` fixture, and `backend/tests/conftest.py` connects to
`localhost:5432` regardless of `POSTGRES_PORT`. The split is by what the test
exercises, not by whether it touches a database.
Run backend tests from the repository root; `pyproject.toml` is the single pytest
configuration and `testpaths` covers `backend/tests` and `modules/backend/tests`.

The test shell, if you run pytest by hand rather than through `make`:

```bash
source venv/bin/activate
export APP_ENV=test TESTING=true POSTGRES_SCHEMA=test_experimentation
python -m pytest backend/tests/unit -p no:cov -q
```

`POSTGRES_SCHEMA` matters more than it looks: the models bake the schema name
into index names and foreign-key targets at import time, and alembic reflects
whatever `POSTGRES_SCHEMA` names. The two must agree or `alembic revision
--autogenerate` compares one schema's models against another schema's tables
and proposes creating -- or dropping -- everything. The same export sequence
applies when generating a migration:

```bash
export APP_ENV=test TESTING=true POSTGRES_SCHEMA=test_experimentation
python -m alembic -c backend/app/db/alembic.ini revision --autogenerate --head <core head id> -m "..."
```

`backend/tests/integration/database/test_autogenerate_is_empty.py` is the
standing check that a freshly bootstrapped database produces an empty
migration; if you touch anything about schemas or reflection, run it.
Tests that need a module installed are marked `@pytest.mark.modules` and are
skipped in a core build.

Every bug fix needs a regression test. The `regression-guard` CI job fails a pull
request labelled `bug` that adds no test.

### Lint

```bash
make lint             # exactly what the `lint` CI job runs
make format           # ruff format + ruff check --fix, in place
```

`make lint` runs `ruff check backend/ modules/ scripts/`, `ruff format --check`,
`lint-imports` (the core/modules import contracts), `reuse lint` (every file
carries a licence: `REUSE.toml` covers the tree by directory, the texts live in
`LICENSES/`), the requirements-lock check, `npm run lint` and `npx tsc --noEmit`
in `frontend/`, plus `hadolint` on the Dockerfiles and `actionlint` on the
workflows when those two are installed (`brew install hadolint actionlint`).
`ruff` replaces black, isort and flake8 — do not add those back. A change to a
pin in `backend/requirements/runtime.txt` needs `make lock` afterwards: the API
image installs the hashed lock, not the loose pins.

## Layer map

```
backend/app/        FastAPI application: api/, core/, services/, models/, schemas/
backend/lambda/     Lambda handlers (assignment, event processor, flag evaluation)
backend/scripts/    One-off and seed scripts
backend/tests/      unit/ integration/ smoke/ e2e/ contract/ performance/ realistic/
frontend/           Next.js dashboard (TypeScript)
sdk/<lang>/         16 client SDKs — independent packages, MIT licensed
modules/            The optional modules (workspaces, rbac, sso, hipaa, compliance,
                    warehouse, integrations, counters, etl, split_url) — Apache-2.0,
                    contributions welcome like anywhere else
infrastructure/     AWS CDK stacks
demo/               ShopLab and StreamPulse demo applications
docs/               All documentation, including the modules
tests/sdk-contract/ Cross-SDK golden-vector tests
```

Rules that are easy to get wrong:

- **Backend imports are absolute and fully qualified**:
  `from backend.app.models.metrics.metric import RawMetric`. Never
  `from app.models...` and never a relative import across packages. Two import
  paths to one class make SQLAlchemy treat it as two mapped classes.
- **The entry point is `backend.app.main:app`**, run from the repository root —
  not `app.main:app` from inside `backend/`.
- **Tests are organised by directory, not by marker.** A test that needs no
  database goes in `backend/tests/unit/`; one that needs Postgres goes in
  `backend/tests/integration/`; one that asserts the app is wired correctly goes
  in `backend/tests/smoke/`. Markers exist (`unit`, `integration`, `api`,
  `regression`) but the directory is what CI selects on, and a module-level
  import cannot be skipped by a marker.
- **Nothing in `backend/` may import `modules`.** The core profile must build,
  boot and pass its tests with `modules/` deleted, and three things enforce
  it: `lint-imports` (contracts in `pyproject.toml` `[tool.importlinter]` and
  `backend/lambda/.importlinter`: `backend.app` and the Lambda functions never
  import `modules`; `backend.app` never imports `backend.tests`, `sdk`, `demo`
  or `infrastructure`), `backend/tests/smoke/test_core_boundary.py` (an AST
  scan against the module list in `modules-manifest.txt`, including string
  literals such as `patch()` targets), and `make core-build`
  (`scripts/core_build.sh`), which copies the checkout, deletes `modules/` and
  every manifest path, and then imports, bootstraps, tests, builds and scans
  what is left — the `core-build` CI job runs the same script on every pull
  request, and `full-build` runs the same sequence on the full tree.
  The modules plug into the core through the registration hooks and the
  loader under `backend/app/core/` and `backend/app/modules_loader.py`, never
  the other way round: the dependency arrow points from `modules/` into
  `backend/`, never back. A module that is not installed answers 501 on its
  routes; there is no other gate.
- **The public API has a stable snapshot.** `docs/api/openapi-v1.stable.json`
  (the core profile) and `docs/api/openapi-v1.full.json` (the full profile)
  are compared by `backend/tests/smoke/test_openapi_snapshot.py`: changing the
  shape of a stable route fails the smoke suite. A new or still-changing route
  is marked `openapi_extra={"x-stability": "beta"}` on its decorator, which
  turns the failure into a warning; `make openapi` regenerates the snapshots
  when a change is intended. See `docs/api/stability.md`.
- **SDKs are independent packages.** `sdk/js`, `sdk/python`, `sdk/go` and the
  thirteen others have their own manifests, their own tests and their own
  release pipelines, and they do not import from `backend/`. They share only the
  wire contract and the MD5 consistent-hashing algorithm, which is pinned by the
  golden vectors in `tests/sdk-contract/`. If you change assignment hashing, you
  change all sixteen or none.
- **New SQLAlchemy models must be imported in `backend/app/models/__init__.py`**
  so that standalone scripts can configure the mappers.
- **Pydantic v2 only**: `field_validator`, `model_validator`, `ConfigDict`,
  `pydantic_settings.BaseSettings`.

## Pull requests

1. Fork, then branch from `main` (`git checkout -b fix/flag-eval-empty-rules`).
2. Write the change and a test that fails without it.
3. `make lint && make test`.
4. Commit with `-s`. Conventional-commit prefixes (`fix:`, `feat:`, `docs:`,
   `chore:`) drive the changelog, so please use them.
5. Open the pull request and fill in the template. Describe what breaks without
   the change, not just what you did.

Keep pull requests focused. A refactor and a bug fix in one branch takes three
times as long to review, and a reverted refactor takes the fix with it.

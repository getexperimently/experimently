# Contributing to Experimently

Thanks for wanting to help. This document is the short version of everything you
need: how to sign your work, how to run the stack, where code lives, and which
part of the tree does not take outside contributions.

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

**Licence of your contribution.** A contribution to the Community Edition is
made under [AGPL-3.0-only](LICENSE); a contribution to `sdk/` is made under
[MIT](sdk/LICENSE). The `LICENSE` file covering the directory you touch is the
licence you are contributing under — there is no separate copyright assignment.

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
schema from the models and stamps the alembic head on a fresh database, and runs
`alembic upgrade head` on an existing one. Do not run `alembic upgrade head` on
an empty database — the historical migration chain cannot replay from nothing.

Other useful targets — `make help` lists them all:

| Target | What it does |
|---|---|
| `make up` | The core stack in Docker (API, dashboard, Postgres, Redis) |
| `make demo` | The whole stack including the ShopLab and StreamPulse demo apps |
| `make down` | Stop everything and drop the volumes |
| `make bootstrap` | Create the schema and the first administrator |
| `make openapi` | Regenerate the OpenAPI fixture the frontend URL guard checks |

### Tests

```bash
make test             # what a pull request must pass: backend + frontend
make test-unit        # backend unit tests (most need Postgres too)
make test-integration # backend integration tests (needs Postgres on localhost:5432)
make test-frontend    # dashboard jest tests, tsc --noEmit, production build
make test-sdk         # cross-SDK golden-vector contract tests
```

Both suites need PostgreSQL on **localhost:5432**. `make db` starts it. The unit
suite is not database-free despite the name: 26 of its files take the
`db_session` fixture, and `backend/tests/conftest.py` connects to
`localhost:5432` regardless of `POSTGRES_PORT`. The split is by what the test
exercises, not by whether it touches a database.
Run backend tests from the repository root; `pyproject.toml` is the single pytest
configuration and `testpaths` is `backend/tests`.

Every bug fix needs a regression test. The `regression-guard` CI job fails a pull
request labelled `bug` that adds no test.

### Lint

```bash
make lint             # exactly what the `lint` CI job runs
make format           # ruff format + ruff check --fix, in place
```

`make lint` runs `ruff check backend/`, `ruff format --check backend/`,
`npm run lint` and `npx tsc --noEmit` in `frontend/`, plus `hadolint` on the
Dockerfiles and `actionlint` on the workflows when those two are installed
(`brew install hadolint actionlint`). `ruff` replaces black, isort and flake8 —
do not add those back.

## Layer map

```
backend/app/        FastAPI application: api/, core/, services/, models/, schemas/
backend/lambda/     Lambda handlers (assignment, event processor, flag evaluation)
backend/scripts/    One-off and seed scripts
backend/tests/      unit/ integration/ smoke/ e2e/ contract/ performance/ realistic/
frontend/           Next.js dashboard (TypeScript)
sdk/<lang>/         16 client SDKs — independent packages, MIT licensed
ee/                 Enterprise Edition — proprietary, no outside contributions
infrastructure/     AWS CDK stacks
demo/               ShopLab and StreamPulse demo applications
docs/               All documentation, including Enterprise topics
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
- **Nothing in `backend/` may import `ee`.** The Community Edition must build,
  boot and pass its tests with `ee/` deleted. `backend/tests/smoke/test_ce_boundary.py`
  enforces the import direction today, reading the module list in
  `ee-manifest.txt`; the `community-build` CI job that actually deletes those
  paths and rebuilds lands with the physical move (issue #89).
  Enterprise code plugs into the Community Edition through the registration
  hooks and loader under `backend/app/core/`, never the other way round: the
  dependency arrow points from `ee/` into `backend/`, never back.
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

## `ee/` takes no outside contributions

`ee/` is the Enterprise Edition. It is proprietary and source-available under
[`ee/LICENSE`](ee/LICENSE), not open source, and `.github/CODEOWNERS` assigns it
to the repository owner.

**We will close, without review, any pull request that modifies a file under
`ee/`.** This is not a judgement about the contribution. The reason is licensing:
Experimently sells the Enterprise Edition, and selling code we do not wholly own
requires either a copyright assignment or a contributor licence agreement from
every contributor. We chose the DCO precisely so that contributing to the open
core stays frictionless — no paperwork, no assignment, you keep your copyright.
The price of that choice is that the proprietary directory has to stay
single-author.

What you can do instead:

- **File an issue** about an Enterprise feature. Bug reports, design feedback and
  reproduction cases for `ee/` are welcome and acted on.
- **Contribute to the seam.** The hooks, the registries, the edition endpoint,
  the licence verifier and the Enterprise loader all live in `backend/app/`
  under AGPL-3.0 and are open to contributions. Most of what people want to
  change about Enterprise behaviour is actually in the seam.

  To exercise the Enterprise path locally, mint yourself a development licence
  and put it where the runner you use will read it:

  ```bash
  python scripts/make_dev_license.py --features '*' --env-file .env.dev   # make dev
  python scripts/make_dev_license.py --features '*' --env-file .env       # docker compose
  ```

  `make dev` runs uvicorn with `DevSettings`, which reads `.env.dev`;
  `docker compose` reads `.env` and passes the two variables to the api
  service. `GET /api/v1/edition` tells you which one took: `"edition":
  "enterprise"` with `"status": "active"`.

  It signs with `kid="dev"`, which the verifier honours only when the process
  environment explicitly says `ENVIRONMENT=development` or `ENVIRONMENT=test` —
  so it unlocks your checkout and nothing else. The private key is written to
  `~/.experimently/`, mode 0600, and the script refuses to put one anywhere
  inside the repository.
- **Contribute to the docs.** Enterprise documentation lives in `docs/` under
  AGPL-3.0, not in `ee/`. Documentation is marketing; only the code is
  proprietary.

If you are unsure which side of the line a change falls on, open an issue and
ask before you write it.

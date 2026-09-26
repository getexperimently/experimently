# Database Migrations

The platform uses **Alembic** for PostgreSQL schema management. All schema changes — new tables, columns, indexes, and constraints — are expressed as versioned migration scripts that can be applied forward or rolled back.

---

## Overview

Migration files live in `backend/app/db/migrations/versions/`. Each file represents one atomic schema change, identified by a unique revision ID. Alembic tracks which migrations have been applied in the `alembic_version` table in your database.

**Two branches, two heads.** A full-profile checkout also has
`modules/backend/app/db/migrations/versions/`, a separate branch labelled
`modules` for the schema the optional modules own. A core checkout has no
`modules/` directory and therefore one head; a full checkout has two, and
`alembic_version` holds one row per head. That is why every command below says
`heads` (plural) and never `head`: alembic refuses the singular when more than
one head exists. Run every command from the repository root, or with an
absolute `-c` path — the config resolves both branches from any directory.

---

## Running All Migrations

To apply all pending migrations to the latest schema version:

```bash
# Always activate your virtualenv first
source venv/bin/activate

# Set required environment variables
export POSTGRES_DB=experimentation
export POSTGRES_SCHEMA=experimentation
export POSTGRES_SERVER=localhost
export POSTGRES_USER=postgres
export POSTGRES_PASSWORD=your-password

# Run migrations
python -m alembic -c backend/app/db/alembic.ini upgrade heads
```

`heads` refers to the latest migration of every branch. This command applies all
unapplied migrations in order.

On a database with no tables at all, run the bootstrap instead — the historical
migration chain cannot be replayed from zero, so a fresh schema is created from
the models and stamped:

```bash
python -m backend.app.db.bootstrap
```

The bootstrap is also what the API container runs on start-up
(`RUN_MIGRATIONS=true`, the default), and it is what makes a **profile switch**
work; see "Switching profile" below.

---

## Viewing Migration History

Show all migrations and whether they have been applied:

```bash
python -m alembic -c backend/app/db/alembic.ini history
```

Output:

```
ef1234567890 -> ab1234567890 (head), Add safety_settings table
cd1234567890 -> ef1234567890, Add split_url_config column to experiments
...
<base> -> a1b2c3d4e5f6, Initial schema
```

Revisions shown with `(head)` are the latest applied migration. Revisions not yet applied appear without a marker.

---

## Checking Current State

Show which migration is currently applied to the database:

```bash
python -m alembic -c backend/app/db/alembic.ini current
```

Output:

```
ab1234567890 (head)
```

This is the revision ID of the last migration that was applied to the database.

---

## Creating a New Migration

When you add or modify SQLAlchemy models, generate a migration script:

```bash
# Which head does this revision extend?  (A core checkout has only one and can
# leave --head out entirely.)
python -m alembic -c backend/app/db/alembic.ini heads

python -m alembic -c backend/app/db/alembic.ini revision --autogenerate \
    --head <core head id> -m "add email_verified column to users"
```

Alembic inspects the difference between the current models and the database schema, then generates a migration file next to the head it extends: `backend/app/db/migrations/versions/` for a core revision, `modules/backend/app/db/migrations/versions/` for `--head modules@head`. Without `--head` it refuses with "Multiple heads are present" rather than guessing — do **not** answer that with `alembic merge`: the merge file lands in the core chain with the module head in its `down_revision`, and a core checkout then cannot load the migration directory at all.

### Always Review the Generated File

Auto-generated migrations are a starting point, not a finished product. Always open and review the generated file before applying it:

```python
# Example generated migration
def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), nullable=True),
        schema='experimentation'
    )

def downgrade() -> None:
    op.drop_column('users', 'email_verified', schema='experimentation')
```

Check for:
- Correct `down_revision` pointing to the previous migration's ID
- Correct schema name (`schema='experimentation'`) on all operations
- No unintended table drops or data loss
- Correct data types and constraints

---

## Applying a Specific Migration

Apply migrations up to a specific revision (not necessarily the latest):

```bash
python -m alembic -c backend/app/db/alembic.ini upgrade ab1234567890
```

You can also use relative steps:

```bash
# Apply the next one migration
python -m alembic -c backend/app/db/alembic.ini upgrade +1

# Apply the next three migrations
python -m alembic -c backend/app/db/alembic.ini upgrade +3
```

---

## Rolling Back

Roll back the most recent migration **of one branch**. With two heads a bare
`-1` is ambiguous — alembic warns and picks one, which may not be the branch you
meant — so name the branch:

```bash
# the modules branch, one revision back (its only one today: modules_0001_rbac)
python -m alembic -c backend/app/db/alembic.ini downgrade modules@-1

# one step back on the core chain
python -m alembic -c backend/app/db/alembic.ini downgrade <core revision id>
```

**Not `modules@base`.** `modules_0001_rbac` is a child of the core revision
`a7b8c9d0e1f2`, not an alembic base, and with a single tree root alembic cannot
filter a downgrade by branch label: `downgrade modules@base` resolves to **26
revisions** — the whole core chain to base — and drops every table in the
schema.

`modules_0001_rbac` downgrades only the objects its own `upgrade()` created (it
marks them with a PostgreSQL COMMENT as it goes). On a database whose tables
came from the bootstrap rather than from that migration, its downgrade is a
no-op — it will not drop populated tables it never made.

Roll back to a specific revision:

```bash
python -m alembic -c backend/app/db/alembic.ini downgrade ab1234567890
```

Roll back all migrations (to the empty database state):

```bash
python -m alembic -c backend/app/db/alembic.ini downgrade base
```

**Note**: Not all migrations are safely reversible. If a migration deletes a column, the downgrade drops data. Review the `downgrade()` function in each migration file before rolling back in production.

---

## Stamping Without Running Migrations

The `stamp` command marks a migration as applied without actually running its SQL. Use this when:

- You have manually applied schema changes and want to bring Alembic in sync
- You are setting up Alembic on an existing database
- You need to skip a problematic migration after fixing it manually

```bash
# Mark current database state as "head"
python -m alembic -c backend/app/db/alembic.ini stamp heads

# Mark as a specific revision
python -m alembic -c backend/app/db/alembic.ini stamp ab1234567890
```

---

## Resolving "Multiple Heads" Errors

If two developers create migrations from the same base revision, Alembic ends up with two "heads" (two branches in the migration graph). This error looks like:

```
FAILED: Multiple head revisions are present for given argument 'head'
```

### Diagnosis

```bash
python -m alembic -c backend/app/db/alembic.ini heads
```

Output:

```
ab1234567890 (head)
cd1234567890 (head)
```

### Resolution

The `modules` branch is *not* one of these: it is two heads on purpose, and
`alembic heads` labels it. Never merge it. For two core revisions cut from the
same parent, create a merge migration that unifies them:

```bash
python -m alembic -c backend/app/db/alembic.ini merge -m "merge heads" ab1234567890 cd1234567890
```

This creates a new migration file with both revisions as its `down_revision`. The merge migration itself has no SQL operations — it exists only to reunify the graph. Apply it normally:

```bash
python -m alembic -c backend/app/db/alembic.ini upgrade heads
```

---

## Environment Variables

The following environment variables must be set before running any Alembic commands:

| Variable | Example | Description |
|----------|---------|-------------|
| `POSTGRES_SERVER` | `localhost` | Database host |
| `POSTGRES_PORT` | `5432` | Database port |
| `POSTGRES_USER` | `postgres` | Database username |
| `POSTGRES_PASSWORD` | `your-password` | Database password |
| `POSTGRES_DB` | `experimentation` | Database name |
| `POSTGRES_SCHEMA` | `experimentation` | PostgreSQL schema name |

On macOS, always use `localhost` (not `127.0.0.1`) for the database host when connecting to a Docker-hosted PostgreSQL instance.

---

## Migration Guidelines

### Do

- Generate migrations with `--autogenerate` and always review the output
- Test migrations on a copy of production data before applying to production
- Include both `upgrade()` and `downgrade()` functions
- Use descriptive migration names: `add_bayesian_config_to_experiments`
- Commit migration files to version control alongside the model changes that require them

### Do Not

- Edit migration files that have already been applied to production
- Use bare revision IDs in `down_revision` — always use the actual ID string, not a migration name
- Delete migration files from the versions directory
- Apply migrations without setting the correct `POSTGRES_SCHEMA` environment variable (the schema namespace will be wrong)

---

## Running Migrations in Production

In production (ECS Fargate), migrations are run as a one-off ECS task before the new application version is deployed:

```bash
# Run as a one-off ECS task
aws ecs run-task \
  --cluster experimentation-<env> \
  --task-definition experimentation-migrate-<env> \
  --overrides '{"containerOverrides":[{"name":"backend","command":["python","-m","alembic","-c","backend/app/db/alembic.ini","upgrade","heads"]}]}' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxx],securityGroups=[sg-xxxx]}"
```

The CDK deployment pipeline runs this task automatically before routing traffic to the new deployment. The exact command is
`MIGRATION_COMMAND` in `infrastructure/cdk/stacks/migration_task_stack.py`; the
path is relative to the image's `WORKDIR /app`, under which `backend/Dockerfile`
copies the repository layout unchanged.

---

## Switching Profile

The same database can be built by one profile and opened by the other. Both
documented paths handle it the same way: `python -m backend.app.db.bootstrap`
(what the API container runs on start-up) and `alembic upgrade heads` (what the
migration task runs) share the repairs below, because `backend/app/db/migrations/env.py` calls
them after a command-line upgrade.

**Core database, full image.** The core chain marks the revisions that once
created `workspaces`, `sso_configs`, `phi_audit_logs` and the rest as applied
without creating them, and the `modules` branch does not re-create them (it owns
the three RBAC tables only). So after the upgrade reaches this build's heads,
the module tables the models declare and the database lacks are created from
the models, the two `workspace_id` foreign keys are added, and a WARNING says
so. Only module tables are ever created this way — an unmigrated *core* model is
not, so a missing core migration still shows up as a missing table rather than
being papered over. `alembic upgrade heads --sql` (offline mode) has no
reconcile step: the SQL it emits for a profile switch is incomplete.

**Full database, core image.** `alembic_version` holds a revision a core build
has no file for. `alembic upgrade heads` answers in one of two ways: when the
core chain is already at its head there is nothing to apply, so it skips alembic,
leaves the rows untouched and logs a WARNING naming the foreign revisions (exit
0); when the core chain is *behind* — a newer core image against a database the
full image built — it refuses with a message naming them. `downgrade` and
`stamp` do not skip: they fail with alembic's own "Can't locate revision
identified by 'modules_0001_rbac'", and the schema is untouched.

The escape hatch, when you really do want the core image to own that database:
take a backup, then from the core image

```bash
python -m alembic -c backend/app/db/alembic.ini stamp --purge heads
```

`--purge` replaces the whole version table with this build's own heads, so the
modules row goes and the core row stays. The module tables themselves are never
dropped by switching down to core. They stay, unused, until the database goes
back to the full profile.

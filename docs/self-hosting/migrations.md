# Database Migrations

The platform uses **Alembic** for PostgreSQL schema management. All schema changes — new tables, columns, indexes, and constraints — are expressed as versioned migration scripts that can be applied forward or rolled back.

---

## Overview

Migration files live in `backend/app/db/migrations/versions/`. Each file represents one atomic schema change, identified by a unique revision ID. Alembic tracks which migrations have been applied in the `alembic_version` table in your database.

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
python -m alembic -c backend/app/db/alembic.ini upgrade head
```

`head` refers to the latest migration. This command applies all unapplied migrations in order.

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
python -m alembic -c backend/app/db/alembic.ini revision --autogenerate -m "add email_verified column to users"
```

Alembic inspects the difference between the current models and the database schema, then generates a migration file in `backend/app/db/migrations/versions/`.

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

Roll back the most recent migration:

```bash
python -m alembic -c backend/app/db/alembic.ini downgrade -1
```

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
python -m alembic -c backend/app/db/alembic.ini stamp head

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

Create a merge migration that unifies the two heads:

```bash
python -m alembic -c backend/app/db/alembic.ini merge -m "merge heads" ab1234567890 cd1234567890
```

This creates a new migration file with both revisions as its `down_revision`. The merge migration itself has no SQL operations — it exists only to reunify the graph. Apply it normally:

```bash
python -m alembic -c backend/app/db/alembic.ini upgrade head
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
  --cluster experimentation-cluster \
  --task-definition experimentation-migrations \
  --overrides '{"containerOverrides":[{"name":"api","command":["python","-m","alembic","-c","app/db/alembic.ini","upgrade","head"]}]}' \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxx],securityGroups=[sg-xxxx]}"
```

The CDK deployment pipeline runs this task automatically before routing traffic to the new deployment.

Verify that model imports are rooted at `backend.app`, never at `app`.

Arguments: $ARGUMENTS (optional — "fix" to apply corrections, otherwise check only)

Background:
An import rooted at `app` rather than `backend.app` resolves to a *different
module object* for the same file, so Python builds two classes from one
`class RawMetric`. SQLAlchemy then maps one and not the other:

- "Class is not mapped" at runtime
- two copies of every model in memory
- type checks that pass on one and fail on the other

`from .base import Base` inside `backend/app/models/` is **not** this defect and
must not be "fixed": a relative import there resolves to
`backend.app.models.base`, the same module object as the fully-qualified path.
The hazard is only the wrong *root package*.

Steps to execute:

1. Check. There is no script for this — it is one grep, and a hit is the defect:

   ```bash
   grep -rnE '^\s*(from|import) app\.' backend/ modules/ --include='*.py'
   ```

   No output means the convention holds, which is the state of `main` today.

2. If $ARGUMENTS is "fix", rewrite each hit's root package from `app.` to
   `backend.app.`, then re-run step 1 and confirm it prints nothing.

3. Confirm nothing else broke:

   ```bash
   make lint          # includes lint-imports, the core/modules boundary
   source venv/bin/activate && python -m pytest backend/tests/smoke -q
   ```

Standard import pattern (always use):
```python
from backend.app.models.metrics.metric import RawMetric, MetricType
```

Never use:
- A `app.`-rooted import: `from app.models.metrics.metric import RawMetric`
- Re-exports from `__init__.py` files

Example usage:
- /fix-imports → check
- /fix-imports fix → rewrite the offenders, then re-check

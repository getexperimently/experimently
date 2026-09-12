Run code quality checks on the backend.

Execute formatting, linting and type checking. Ruff replaced black, isort and
flake8: one tool, configured in `[tool.ruff]` in `pyproject.toml`, the same
version in the venv, pre-commit and the `lint` CI job.

Arguments: $ARGUMENTS (optional - "check" for dry-run, "fix" to apply changes, or specific tool name)

Available tools:
- ruff format: code formatting (the black replacement, 88 columns)
- ruff check: linting and import sorting (the flake8 + isort replacement)
- mypy: static type checking

Steps to execute:

If $ARGUMENTS is "check" or empty (dry-run):
1. Activate virtual environment
2. Run ruff format in check mode: ruff format backend/ --check --diff
3. Run ruff lint: ruff check backend/
4. Run mypy: mypy backend/app/
5. Report summary of issues found

If $ARGUMENTS is "fix":
1. Activate virtual environment
2. Apply formatting: ruff format backend/
3. Apply safe lint fixes (includes import order): ruff check backend/ --fix
4. Run mypy for type checking: mypy backend/app/
5. Report changes made and remaining issues

If $ARGUMENTS is a specific tool name (ruff|format|lint|mypy):
1. Run only that tool in fix mode
2. Report results

Quality standards:
- Consistent formatting via `ruff format`
- Imports sorted by ruff's `I` rules
- Type hints checked by mypy
- Lint rules: see the `select`/`ignore` lists in `[tool.ruff.lint]`; each
  relaxation there carries the reason it exists

The whole gate, including the frontend and the Dockerfiles, is `make lint`.

Example usage:
- /quality → check all quality metrics
- /quality check → same as above
- /quality fix → apply formatting and lint fixes
- /quality format → run only the formatter

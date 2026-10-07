"""
Conftest for realistic scenario tests.

Overrides the default python_files pattern so pytest collects scenario files
that don't follow the test_*.py naming convention (e.g., bayesian_analysis.py,
variance_reduction.py). They need no running platform, and the PR QA Gate's
Unit Tests job runs them with its zero-skip check (scripts/check_junit_skips.py).
"""

import pytest


def pytest_collect_file(parent, file_path):
    """Collect all .py files in this directory as test modules."""
    if (
        file_path.suffix == ".py"
        and file_path.name not in ("__init__.py", "conftest.py")
        and file_path.parent.name == "scenarios"
    ):
        return pytest.Module.from_parent(parent, path=file_path)

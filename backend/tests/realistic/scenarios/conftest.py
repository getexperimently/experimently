"""
Conftest for realistic scenario tests.

Overrides the default python_files pattern so pytest collects scenario files
that don't follow the test_*.py naming convention (e.g., ab_test_lifecycle.py,
bayesian_analysis.py).
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

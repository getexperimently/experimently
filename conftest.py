"""Repository-root conftest.

pytest loads it for every session whose rootdir is the repository root (the
``[tool.pytest.ini_options]`` in pyproject.toml): backend/tests,
modules/backend/tests, each backend/lambda/<function>, infrastructure/tests
and tests/sdk-contract. The two SDK suites have their own rootdir and carry
their own copy.

It carries one thing, and must stay importable with only pytest installed
(tests/sdk-contract runs that way): no test may reach real AWS credentials or
the real ``aws`` binary. See backend/tests/no_real_aws.py.
"""

import sys
from pathlib import Path

# ``--import-mode=importlib`` (infrastructure/tests) does not put the rootdir on
# sys.path, and a bare ``pytest`` (not ``python -m pytest``) does not either.
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest_plugins = ["backend.tests.no_real_aws"]

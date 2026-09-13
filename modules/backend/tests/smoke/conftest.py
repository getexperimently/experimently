"""Smoke test configuration (mirrors ``backend/tests/smoke/conftest.py``)."""


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: mark test as a smoke test")

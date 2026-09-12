"""Smoke test configuration."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: mark test as a smoke test")

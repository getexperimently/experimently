"""Throwaway tamper for #399; this branch is deleted after the check runs."""

import pytest


@pytest.mark.unit
@pytest.mark.regression
def test_tamper():
    assert True

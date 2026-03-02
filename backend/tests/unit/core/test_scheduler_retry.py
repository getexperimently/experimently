"""
Unit tests for scheduler retry decorator (P3-B TDD).

Tests cover:
- Function succeeds on first try → called exactly once
- Function fails once then succeeds → called twice
- Function fails max_retries+1 times → raises last exception
- Backoff delay doubles between retries (mock time.sleep)
- Retry with max_retries=0 → raises immediately on first failure
- Original function return value is preserved on success
- Correct exception is re-raised after exhausting retries
- Function metadata (name, docstring) preserved by @wraps
"""

import pytest
from unittest.mock import MagicMock, patch, call

from backend.app.core.scheduler_retry import with_retry


# ---------------------------------------------------------------------------
# Basic success / failure behaviour
# ---------------------------------------------------------------------------


class TestWithRetryBasicBehaviour:
    def test_succeeds_on_first_try_calls_once(self):
        mock_fn = MagicMock(return_value="ok")

        @with_retry(max_retries=3, delay_seconds=1)
        def my_task():
            return mock_fn()

        result = my_task()
        assert result == "ok"
        assert mock_fn.call_count == 1

    def test_fails_once_then_succeeds_calls_twice(self):
        call_count = {"n": 0}

        @with_retry(max_retries=3, delay_seconds=0)
        def my_task():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient error")
            return "success"

        with patch("backend.app.core.scheduler_retry.time.sleep"):
            result = my_task()

        assert result == "success"
        assert call_count["n"] == 2

    def test_fails_max_retries_plus_one_times_raises(self):
        """After max_retries+1 attempts, the last exception is re-raised."""
        call_count = {"n": 0}

        @with_retry(max_retries=2, delay_seconds=0)
        def my_task():
            call_count["n"] += 1
            raise ValueError(f"failure {call_count['n']}")

        with patch("backend.app.core.scheduler_retry.time.sleep"):
            with pytest.raises(ValueError, match="failure 3"):
                my_task()

        # max_retries=2 means 3 total attempts (1 initial + 2 retries)
        assert call_count["n"] == 3

    def test_max_retries_zero_raises_immediately_on_failure(self):
        """With max_retries=0, no retries occur and exception raised on first failure."""
        call_count = {"n": 0}

        @with_retry(max_retries=0, delay_seconds=0)
        def my_task():
            call_count["n"] += 1
            raise RuntimeError("immediate failure")

        with patch("backend.app.core.scheduler_retry.time.sleep"):
            with pytest.raises(RuntimeError, match="immediate failure"):
                my_task()

        assert call_count["n"] == 1

    def test_return_value_preserved_on_success(self):
        @with_retry(max_retries=3, delay_seconds=0)
        def compute():
            return {"result": 42, "extra": [1, 2, 3]}

        result = compute()
        assert result == {"result": 42, "extra": [1, 2, 3]}

    def test_correct_exception_reraised(self):
        """The exact exception from the last attempt is re-raised."""

        @with_retry(max_retries=1, delay_seconds=0)
        def my_task():
            raise TypeError("specific type error")

        with patch("backend.app.core.scheduler_retry.time.sleep"):
            with pytest.raises(TypeError, match="specific type error"):
                my_task()


# ---------------------------------------------------------------------------
# Backoff / sleep behaviour
# ---------------------------------------------------------------------------


class TestWithRetryBackoff:
    def test_sleep_called_between_retries(self):
        call_count = {"n": 0}

        @with_retry(max_retries=2, delay_seconds=30, backoff=2.0)
        def my_task():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise RuntimeError("fail")
            return "ok"

        with patch("backend.app.core.scheduler_retry.time.sleep") as mock_sleep:
            result = my_task()

        assert result == "ok"
        # sleep should have been called twice (after attempt 1 and attempt 2)
        assert mock_sleep.call_count == 2

    def test_backoff_doubles_delay(self):
        """Delay doubles with each retry: delay * backoff^attempt."""
        call_count = {"n": 0}

        @with_retry(max_retries=3, delay_seconds=10, backoff=2.0)
        def my_task():
            call_count["n"] += 1
            raise RuntimeError("always fail")

        with patch("backend.app.core.scheduler_retry.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                my_task()

        # Expected sleeps: 10*2^0=10, 10*2^1=20, 10*2^2=40
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls[0] == pytest.approx(10.0)
        assert sleep_calls[1] == pytest.approx(20.0)
        assert sleep_calls[2] == pytest.approx(40.0)

    def test_no_sleep_after_last_attempt(self):
        """sleep is NOT called after the final failed attempt."""

        @with_retry(max_retries=1, delay_seconds=60)
        def my_task():
            raise RuntimeError("fail")

        with patch("backend.app.core.scheduler_retry.time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError):
                my_task()

        # Only 1 retry (max_retries=1), so sleep called once (before retry attempt)
        assert mock_sleep.call_count == 1


# ---------------------------------------------------------------------------
# Decorator metadata preservation
# ---------------------------------------------------------------------------


class TestWithRetryMetadata:
    def test_function_name_preserved(self):
        @with_retry(max_retries=3, delay_seconds=1)
        def process_experiments():
            """Processes all pending experiments."""
            return True

        assert process_experiments.__name__ == "process_experiments"

    def test_function_docstring_preserved(self):
        @with_retry(max_retries=3, delay_seconds=1)
        def process_rollouts():
            """Processes all active rollout schedules."""
            return True

        assert "Processes all active rollout schedules" in (process_rollouts.__doc__ or "")

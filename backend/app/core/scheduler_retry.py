"""
Retry decorator for scheduler functions.

Provides a configurable retry mechanism with exponential backoff for use in
background scheduler tasks. Failures are logged at WARNING level; final
exhaustion is logged at ERROR level.
"""

import time
import logging
from functools import wraps
from typing import Callable

logger = logging.getLogger(__name__)


def with_retry(max_retries: int = 3, delay_seconds: int = 60, backoff: float = 2.0):
    """
    Decorator that retries a scheduler function on exception with exponential backoff.

    After max_retries exhausted, logs the failure at ERROR level and re-raises
    the last exception.

    Args:
        max_retries: Maximum number of additional attempts after the first failure.
                     Total attempts = max_retries + 1.
        delay_seconds: Initial delay in seconds before the first retry.
        backoff: Multiplicative factor applied to the delay on each subsequent retry.
                 Default 2.0 produces: delay, delay*2, delay*4, ...

    Usage:
        @with_retry(max_retries=3, delay_seconds=30)
        def run_experiment_scheduler(db):
            ...

    Raises:
        Exception: The last exception raised by the wrapped function after all
                   retry attempts have been exhausted.
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait = delay_seconds * (backoff ** attempt)
                        logger.warning(
                            "%s failed (attempt %d/%d), retrying in %.0fs: %s",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            wait,
                            e,
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            func.__name__,
                            max_retries + 1,
                            e,
                        )
            raise last_exception

        return wrapper
    return decorator

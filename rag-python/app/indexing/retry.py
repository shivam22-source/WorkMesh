"""Bounded exponential backoff and retry utility for external connector operations (AD-07 / Phase 5)."""

import logging
import random
import time
from typing import Any, Callable, Set, Tuple, Type

logger = logging.getLogger(__name__)

# Transient network and server errors that are safe to retry
TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

TRANSIENT_HTTP_STATUSES: Set[int] = {429, 502, 503, 504}


def is_transient_error(exc: Exception) -> bool:
    """Determine whether an exception represents a transient failure eligible for retry."""
    # Check direct transient exception types
    if isinstance(exc, TRANSIENT_EXCEPTIONS):
        return True

    # Check for HTTP status attributes (e.g. httpx.HTTPStatusError, requests.HTTPError)
    if hasattr(exc, "response") and exc.response is not None:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in TRANSIENT_HTTP_STATUSES:
            return True

    return False


def retry_with_backoff(
    fn: Callable[[], Any],
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 5.0,
    jitter: bool = True,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Any:
    """Execute a callable with bounded exponential backoff on transient errors.

    Raises non-transient exceptions immediately without retrying.
    Raises the final exception if max_attempts is exhausted.
    """
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as exc:
            if not is_transient_error(exc) or attempt >= max_attempts:
                if attempt >= max_attempts:
                    logger.warning(
                        "retry_exhausted attempts=%d max_attempts=%d err=%s",
                        attempt,
                        max_attempts,
                        exc,
                    )
                raise

            # Calculate backoff delay: base_delay * 2^(attempt - 1)
            backoff = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = random.uniform(0, backoff) if jitter else backoff

            logger.info(
                "retry_transient_error attempt=%d max_attempts=%d delay=%.2fs err=%s",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            sleep_fn(delay)
            attempt += 1

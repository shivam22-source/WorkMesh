"""Concurrency limiter implementing backpressure for intensive search and Q&A operations."""

import threading
from typing import Optional
from app.common.config import get_settings


class ConcurrencyLimitExceededError(Exception):
    """Raised when the search or ask concurrency limit is saturated."""

    def __init__(
        self,
        message: str = "Search concurrency limit reached. Please retry shortly.",
        retry_after: int = 1,
    ):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class ConcurrencyLimiter:
    """Thread-safe concurrency limiter with non-blocking acquisition."""

    def __init__(self, max_concurrent: Optional[int] = None):
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._active_count = 0

    @property
    def max_concurrent(self) -> int:
        if self._max_concurrent is not None:
            return self._max_concurrent
        return get_settings().search_concurrency_limit

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    def acquire(self) -> bool:
        """Attempt to acquire a concurrency slot without blocking.

        Returns True if acquired, False if the limit has been reached.
        """
        with self._lock:
            if self._active_count >= self.max_concurrent:
                return False
            self._active_count += 1
            return True

    def release(self) -> None:
        """Release an acquired concurrency slot."""
        with self._lock:
            if self._active_count > 0:
                self._active_count -= 1

    def reset_for_testing(self) -> None:
        """Reset internal counter for testing."""
        with self._lock:
            self._active_count = 0


# Global singleton limiter instance for /api/v1/search and /api/v1/ask
search_concurrency_limiter = ConcurrencyLimiter()

"""In-memory throttles: login lockout and per-user request rate limiting.

State is per process, which is fine for a single-instance demo. A multi-instance deployment
would move this to a shared store such as Redis.
"""
import math
import threading
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """Sliding-window limiter. Refused requests are not counted, so they cannot extend a block."""

    def __init__(self, limit: int, window: timedelta) -> None:
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque[datetime]] = {}
        self._guard = threading.Lock()

    def retry_after(self, key: str, now: datetime) -> int:
        """Return 0 and count the request if allowed, otherwise the seconds to wait."""
        with self._guard:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return max(1, math.ceil((hits[0] + self._window - now).total_seconds()))
            hits.append(now)
            return 0


class LoginThrottle:
    def __init__(self, max_failures: int, window: timedelta, lockout: timedelta) -> None:
        self._max = max_failures
        self._window = window
        self._lockout = lockout
        self._failures: dict[str, deque[datetime]] = {}
        self._locked_until: dict[str, datetime] = {}
        self._guard = threading.Lock()

    def seconds_locked(self, key: str, now: datetime) -> int:
        with self._guard:
            until = self._locked_until.get(key)
            if until is None or until <= now:
                self._locked_until.pop(key, None)
                return 0
            return math.ceil((until - now).total_seconds())

    def record_failure(self, key: str, now: datetime) -> None:
        with self._guard:
            failures = self._failures.setdefault(key, deque())
            failures.append(now)
            while failures and failures[0] <= now - self._window:
                failures.popleft()
            if len(failures) >= self._max:
                self._locked_until[key] = now + self._lockout
                failures.clear()

    def record_success(self, key: str) -> None:
        with self._guard:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

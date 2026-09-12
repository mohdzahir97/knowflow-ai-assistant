"""Per-identity rate limiting.

Without this, any authenticated account can drive unbounded model spend, and
an unauthenticated client can brute-force the login endpoint.

Storage
-------
In-process, using a sliding window per identity. That is correct for a
single-worker deployment and is honest about its limit: with multiple
workers each holds its own counters, so the effective limit multiplies by
worker count. Redis is the answer when this deploys behind more than one
worker - the interface here is deliberately narrow so swapping the backing
store touches only this file.

Identity
--------
Authenticated requests are limited by user id, so one user cannot exhaust
another's budget or hide behind a shared NAT address. Unauthenticated
requests fall back to client IP, which is all that is available.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple


@dataclass(frozen=True)
class RateLimitRule:
    """`limit` requests allowed per `window_seconds`."""

    limit: int
    window_seconds: int

    def describe(self) -> str:
        return f"{self.limit} requests per {self.window_seconds}s"


class SlidingWindowRateLimiter:
    """Counts request timestamps per key and evicts those outside the window.

    A sliding window rather than fixed buckets: fixed windows allow a burst
    of 2x the limit across a boundary, which for expensive LLM calls is a
    real cost, not a rounding error.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, rule: RateLimitRule) -> Tuple[bool, Optional[int]]:
        """Record a request. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - rule.window_seconds

        with self._lock:
            timestamps = self._hits[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= rule.limit:
                retry_after = max(1, int(timestamps[0] + rule.window_seconds - now) + 1)
                return False, retry_after

            timestamps.append(now)
            return True, None

    def reset(self, key: Optional[str] = None) -> None:
        """Clear counters. Used by tests; also useful operationally."""
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


_limiter = SlidingWindowRateLimiter()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _limiter

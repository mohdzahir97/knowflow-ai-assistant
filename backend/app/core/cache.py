"""A small bounded, thread-safe TTL cache.

Deliberately in-process and dependency-free. Redis would survive restarts
and be shared across workers, but it is another service to run and secure
for a benefit this application does not yet need - the thing worth caching
here is a pure function of its input (an embedding vector for a piece of
text), so a cold cache costs latency and never correctness.

Bounded on purpose: an unbounded cache keyed by user input is a memory leak
with extra steps.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional


class TTLCache:
    """LRU cache with per-entry expiry.

    Every operation holds the lock, which is fine because the critical
    section is a dictionary access - the expensive work (embedding a query)
    happens outside it.
    """

    def __init__(self, max_entries: int = 512, ttl_seconds: float = 900.0) -> None:
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[Any, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Any) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None

            expires_at, value = entry
            if expires_at < time.monotonic():
                # Expired entries are dropped on access rather than by a
                # sweeper thread; a cache this size does not warrant one.
                del self._entries[key]
                self.misses += 1
                return None

            self._entries.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl_seconds, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def get_or_set(self, key: Any, factory: Callable[[], Any]) -> Any:
        """Returns the cached value, computing it if absent.

        The factory runs outside the lock, so two callers racing on the same
        cold key may both compute it. That is accepted deliberately: holding
        the lock across a network call would serialise every unrelated
        lookup behind it, and the values are identical anyway.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._entries),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }

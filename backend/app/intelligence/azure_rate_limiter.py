"""
Process-wide rate limiter for Azure OpenAI.

Design: REACTIVE + minimum spacing, thread-safe across event loops.

Key insight: each execution thread runs its own asyncio event loop, so
asyncio.Lock cannot provide mutual exclusion across threads — it is
event-loop-specific.  We use threading.Lock instead so the singleton
works correctly whether called from the main loop, a planning thread,
or an execution thread.

Behaviour:
  • Normal path: enforces a small minimum gap (_MIN_INTERVAL_SECONDS)
    between consecutive calls to avoid burst flooding (replaces the old
    45 s pre-wait while still being kind to Azure quotas).
  • After a 429: extends the deadline to the Retry-After value returned
    by Azure, then resumes at the minimum interval cadence.
  • Concurrent callers queue naturally: each caller grabs a slot
    atomically inside the threading.Lock, then waits outside it.
"""
from __future__ import annotations
import asyncio
import threading
import time
import structlog

log = structlog.get_logger()

# Minimum gap between consecutive Azure calls.
# 0.5 s  →  max 120 RPM, enough headroom for simultaneous planning +
# execution without triggering quotas under normal load.
_MIN_INTERVAL_SECONDS: float = 0.5

# After a 429, how long to space calls once the retry-after window expires.
_BACKOFF_INTERVAL_SECONDS: float = 5.0


class AzureRateLimiter:
    """
    Thread-safe, reactive Azure OpenAI rate limiter.

    wait()               — call before every Azure API request
    record_retry_after() — call after receiving a 429
    current_wait()       — how many seconds until next slot (0 if free)
    reset()              — clear all backoff state
    """

    def __init__(
        self,
        min_interval: float = _MIN_INTERVAL_SECONDS,
        backoff_interval: float = _BACKOFF_INTERVAL_SECONDS,
    ):
        # threading.Lock works across all event loops (unlike asyncio.Lock).
        self._lock = threading.Lock()
        self._min_interval = min_interval
        self._backoff_interval = backoff_interval
        # Monotonic deadline: next call is allowed at or after this time.
        # Starts at 0 so the first call goes through immediately.
        self._next_allowed: float = 0.0

    async def wait(self) -> None:
        """Block until a slot is available, then atomically reserve the next one."""
        while True:
            with self._lock:
                now = time.monotonic()
                delay = self._next_allowed - now
                if delay <= 0:
                    # Slot is free — reserve next slot and return.
                    self._next_allowed = now + self._min_interval
                    return
            # Slot is taken — sleep outside the lock, then re-check.
            # Sleep slightly longer than needed to avoid a hot spin.
            await asyncio.sleep(max(0.05, delay))

    def current_wait(self) -> float:
        """Return seconds until the next slot is free (0 if available now)."""
        return max(0.0, self._next_allowed - time.monotonic())

    def record_retry_after(self, retry_after_seconds: float) -> None:
        """
        Push the deadline out by retry_after_seconds after a 429.
        Only moves forward, never back.
        """
        with self._lock:
            new_allowed = time.monotonic() + retry_after_seconds
            if new_allowed > self._next_allowed:
                self._next_allowed = new_allowed
                log.info(
                    "Azure rate limiter: 429 — backoff applied",
                    retry_after_seconds=round(retry_after_seconds, 1),
                    next_allowed_in_seconds=round(retry_after_seconds, 1),
                )

    def reset(self) -> None:
        """Clear all rate-limit state (e.g. at the start of a fresh run)."""
        with self._lock:
            self._next_allowed = 0.0


_limiter: AzureRateLimiter | None = None


def get_azure_limiter() -> AzureRateLimiter:
    """Return the process-wide Azure rate limiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = AzureRateLimiter()
    return _limiter

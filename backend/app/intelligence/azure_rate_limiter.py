"""
Process-wide rate limiter for Azure OpenAI.

Design: REACTIVE, not proactive.

We do NOT pre-wait 45s before every call — that makes step-by-step execution
take 15+ minutes for a 20-step plan. Instead:

  • Normal path: no wait at all (calls go through immediately)
  • After a 429: back off for exactly the retry-after the API returned (or
    an exponential fallback), then resume at a minimum _BACKOFF_INTERVAL
    between subsequent calls until the quota window resets

This means:
  - First 429 in a window: pause for retry-after seconds, then continue slowly
  - No 429s: full speed, no artificial throttle
  - Concurrent callers all share the same lock so they queue up rather than
    simultaneously hammering the API after a backoff expires
"""
from __future__ import annotations
import asyncio
import time
import structlog

log = structlog.get_logger()

# After a 429, minimum gap between calls while we're still in a backoff window.
# This prevents immediately burning the quota again as soon as the retry-after expires.
_BACKOFF_INTERVAL_SECONDS: float = 5.0


class AzureRateLimiter:
    """
    Reactive 429-aware rate limiter.

    wait()               — call before every Azure API request; only blocks after a 429
    record_retry_after() — call after receiving a 429 to set the global backoff deadline
    """

    def __init__(self, backoff_interval: float = _BACKOFF_INTERVAL_SECONDS):
        self._lock = asyncio.Lock()
        self._backoff_interval = backoff_interval
        # _next_allowed is 0 by default — no pre-wait until a 429 is seen
        self._next_allowed: float = 0.0

    async def wait(self) -> None:
        """Block until the current backoff window expires, then reserve the next slot."""
        async with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                log.info("Azure rate limiter: waiting after 429",
                         wait_seconds=round(delay, 1))
                await asyncio.sleep(delay)
                # After the backoff expires, space subsequent calls by backoff_interval
                # so we don't immediately flood the API again
                self._next_allowed = time.monotonic() + self._backoff_interval

    def current_wait(self) -> float:
        """Return how many seconds until the next call is allowed (0 if ready now)."""
        return max(0.0, self._next_allowed - time.monotonic())

    def record_retry_after(self, retry_after_seconds: float) -> None:
        """
        Extend the global backoff after receiving a 429.
        Only moves the deadline forward, never backward.
        """
        new_allowed = time.monotonic() + retry_after_seconds
        if new_allowed > self._next_allowed:
            self._next_allowed = new_allowed
            log.info("Azure rate limiter: 429 received — backoff set",
                     retry_after_seconds=retry_after_seconds,
                     next_allowed_in_seconds=round(retry_after_seconds, 1))

    def reset(self) -> None:
        """Clear all backoff state (e.g. at the start of a new run)."""
        self._next_allowed = 0.0


_limiter: AzureRateLimiter | None = None


def get_azure_limiter() -> AzureRateLimiter:
    """Return the process-wide Azure rate limiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = AzureRateLimiter()
    return _limiter

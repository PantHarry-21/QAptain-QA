"""
Process-wide rate limiter for Azure OpenAI.

All Azure API call sites import and use the same singleton so that a 429
from the MCP executor automatically slows down the QA reasoning engine
(and vice versa) — preventing the cascade of back-to-back 429s that happen
when independent callers each burn the quota at full speed.
"""
from __future__ import annotations
import asyncio
import time
import structlog

log = structlog.get_logger()

# Minimum seconds between any two Azure calls across the whole process.
# Azure gpt-5-mini deployments typically allow 1 call per 30-45s at low TPM tiers.
# Set to 45s: after a quota window expires (30s retry-after + 15s buffer).
# If your deployment has higher TPM, reduce this to 10-15s.
_MIN_INTERVAL_SECONDS: float = 45.0


class AzureRateLimiter:
    """
    Token-bucket style limiter with 429-aware backoff.

    wait()               — call before every Azure API request; blocks if needed
    record_retry_after() — call after receiving a 429 to extend the global backoff
    """

    def __init__(self, min_interval: float = _MIN_INTERVAL_SECONDS):
        self._lock = asyncio.Lock()
        self._min_interval = min_interval
        self._next_allowed: float = 0.0  # monotonic time after which calls are allowed

    async def wait(self) -> None:
        """Block until this slot is allowed, then reserve the next slot."""
        async with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                log.debug("Azure rate limiter: pre-call wait", wait_seconds=round(delay, 1))
                await asyncio.sleep(delay)
            # Reserve next slot _min_interval from now
            self._next_allowed = time.monotonic() + self._min_interval

    def record_retry_after(self, retry_after_seconds: float) -> None:
        """Extend the global backoff after a 429. Thread-safe (no lock needed — monotonic update)."""
        new_allowed = time.monotonic() + retry_after_seconds
        if new_allowed > self._next_allowed:
            self._next_allowed = new_allowed
            log.info("Azure rate limiter: 429 backoff extended",
                     retry_after_seconds=retry_after_seconds)


_limiter: AzureRateLimiter | None = None


def get_azure_limiter() -> AzureRateLimiter:
    """Return the process-wide Azure rate limiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = AzureRateLimiter()
    return _limiter

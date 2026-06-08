"""Token budget tracking and rate limit management for exploration."""
import asyncio
import structlog

log = structlog.get_logger()

AZURE_QUOTA_PER_MINUTE = 90000
SAFE_THRESHOLD = 0.8  # Stop exploration at 80% of limit


class TokenBudget:
    """Track token spending and enforce budget limits."""

    def __init__(self, soft_limit: int = 500000):
        self.soft_limit = soft_limit
        self.spent = 0
        self.calls = 0
        self.lock = asyncio.Lock()

    async def add(self, input_tokens: int, output_tokens: int) -> bool:
        """Record token usage. Return True if within budget, False if exceeded."""
        async with self.lock:
            self.spent += input_tokens + output_tokens
            self.calls += 1
            exceeded = self.spent >= (self.soft_limit * SAFE_THRESHOLD)
            if exceeded:
                log.warning("Token budget approaching limit",
                            spent=self.spent, limit=self.soft_limit,
                            calls=self.calls, threshold=SAFE_THRESHOLD)
            return not exceeded

    async def remaining(self) -> int:
        """Get remaining budget."""
        async with self.lock:
            return max(0, int(self.soft_limit * SAFE_THRESHOLD) - self.spent)

    async def summary(self) -> dict:
        """Get budget summary."""
        async with self.lock:
            return {
                "spent": self.spent,
                "limit": self.soft_limit,
                "remaining": max(0, int(self.soft_limit * SAFE_THRESHOLD) - self.spent),
                "api_calls": self.calls,
                "exceeded": self.spent >= (self.soft_limit * SAFE_THRESHOLD),
            }


class RateLimitManager:
    """Manage concurrent API calls while respecting rate limits."""

    def __init__(self, max_concurrent: int = 2):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.backoff_until: float = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Wait for rate limit clearance, then acquire semaphore slot."""
        async with self.lock:
            now = asyncio.get_event_loop().time()
            if now < self.backoff_until:
                wait = self.backoff_until - now
                log.warning("Rate limit backoff", wait_seconds=wait)
                await asyncio.sleep(wait)

        return self.semaphore.acquire()

    async def record_backoff(self, wait_seconds: int):
        """Record that we hit a rate limit and need to back off."""
        async with self.lock:
            now = asyncio.get_event_loop().time()
            self.backoff_until = max(self.backoff_until, now + wait_seconds)
            log.warning("Recorded rate limit backoff", wait_seconds=wait_seconds,
                       backoff_until=self.backoff_until)

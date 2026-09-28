"""
Token-bucket / sliding-window rate limiter backed by Redis for
cross-process state.

Supports two limiters out of the box:
  - NewsAPI: daily request cap (free tier ~100/day)
  - Groq: configurable requests-per-minute (sliding window)

Usage:
    limiter = get_rate_limiter()
    limiter.acquire("newsapi")   # blocks until a token is available
    limiter.acquire("groq")

Configuration (env vars):
  - NEWSAPI_DAILY_LIMIT  (default 95  -- ~5% safety margin under 100)
  - GROQ_RPM_LIMIT       (default 28  -- 2 req/min margin under 30)
  - REDIS_URL            (default redis://localhost:6379/0)

Fail-open: if Redis is unreachable the limiter logs a warning and allows
the call rather than blocking the whole pipeline.
"""
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

NEWSAPI = "newsapi"
GROQ = "groq"

_DEFAULT_NEWSAPI_DAILY = 95
_DEFAULT_GROQ_RPM = 28
_GROQ_WINDOW_SECONDS = 60

# ── Atomic claim scripts ─────────────────────────────────────────────
# Both run server-side so the check-and-claim is a single atomic step; the
# previous Python-side check-then-act let two workers both pass the limit
# under concurrency.

# GROQ: sliding-window log in a sorted set. Trims expired entries, and if
# under the limit adds `member` scored at `now`. Returns {claimed, retry}.
_GROQ_CLAIM_LUA = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
local count = redis.call('ZCARD', KEYS[1])
if count < tonumber(ARGV[3]) then
  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
  redis.call('EXPIRE', KEYS[1], ARGV[2])
  return {1, 0}
end
local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry = tonumber(ARGV[2])
if oldest[2] then
  retry = math.ceil(tonumber(ARGV[2]) - (tonumber(ARGV[1]) - tonumber(oldest[2])))
  if retry < 1 then retry = 1 end
end
return {0, retry}
"""

# NEWSAPI: daily counter. Increments, sets the midnight TTL on first use, and
# rolls back the increment if it would exceed the cap. Returns {claimed, retry}.
_NEWSAPI_CLAIM_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
if current <= tonumber(ARGV[1]) then
  return {1, 0}
end
redis.call('DECR', KEYS[1])
return {0, tonumber(ARGV[2])}
"""


class RateLimitExceeded(Exception):
    """Raised by acquire() when no token becomes available before timeout."""

    def __init__(self, service: str, retry_after_seconds: int) -> None:
        self.service = service
        self.retry_after_seconds = int(retry_after_seconds)
        super().__init__(
            f"rate limit exceeded for {service}; "
            f"retry after {self.retry_after_seconds}s"
        )


def _seconds_until_midnight_utc() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # next midnight
    secs = 86400 - (now - tomorrow).seconds
    return max(1, int(secs))


class RateLimiter:
    """Redis-backed limiter. One instance is shared via get_rate_limiter()."""

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._redis_url = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._client = None  # lazily connected
        self._groq_claim = None     # registered Lua script
        self._newsapi_claim = None  # registered Lua script
        self.newsapi_daily_limit = int(
            os.getenv("NEWSAPI_DAILY_LIMIT", _DEFAULT_NEWSAPI_DAILY)
        )
        self.groq_rpm_limit = int(os.getenv("GROQ_RPM_LIMIT", _DEFAULT_GROQ_RPM))

    # ── Redis plumbing ───────────────────────────────────────────────
    def _redis(self):
        if self._client is not None:
            return self._client
        try:
            import redis

            client = redis.from_url(
                self._redis_url, socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()
            self._client = client
            self._groq_claim = client.register_script(_GROQ_CLAIM_LUA)
            self._newsapi_claim = client.register_script(_NEWSAPI_CLAIM_LUA)
        except Exception as e:
            logger.warning("ratelimit_redis_unavailable", error=str(e))
            self._client = None
        return self._client

    def _newsapi_key(self) -> str:
        return f"ratelimit:newsapi:{datetime.now(timezone.utc):%Y%m%d}"

    @staticmethod
    def _groq_key() -> str:
        return "ratelimit:groq"

    # ── Claim logic ──────────────────────────────────────────────────
    def _try_claim(self, service: str) -> Tuple[bool, int]:
        """
        Attempt to claim one token. Returns (claimed, retry_after_seconds).
        Assumes Redis is available (caller checks).
        """
        client = self._redis()
        if client is None:
            return True, 0  # fail-open

        if service == NEWSAPI:
            claimed, retry = self._newsapi_claim(
                keys=[self._newsapi_key()],
                args=[self.newsapi_daily_limit, _seconds_until_midnight_utc()],
            )
            return bool(claimed), int(retry)

        # GROQ: sliding-window log in a sorted set keyed by timestamp.
        now = time.time()
        claimed, retry = self._groq_claim(
            keys=[self._groq_key()],
            args=[now, _GROQ_WINDOW_SECONDS, self.groq_rpm_limit,
                  f"{now}:{uuid.uuid4()}"],
        )
        return bool(claimed), int(retry)

    # ── Public API ───────────────────────────────────────────────────
    def acquire(self, service: str, timeout: int = 60) -> None:
        """
        Block (with exponential backoff, capped at 5s per sleep and at
        `timeout` total) until a token is claimed. Raises RateLimitExceeded
        if the timeout elapses first. Fails open if Redis is down.
        """
        if self._redis() is None:
            logger.warning("ratelimit_fail_open", service=service)
            return

        deadline = time.monotonic() + timeout
        delay = 0.1
        while True:
            claimed, retry_after = self._try_claim(service)
            if claimed:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(
                    "ratelimit_exceeded", service=service,
                    retry_after_seconds=retry_after,
                )
                raise RateLimitExceeded(service, retry_after)
            time.sleep(min(delay, remaining))
            delay = min(delay * 2, 5.0)

    def get_remaining(self, service: str) -> int:
        """Tokens left in the current window (0 if Redis is down)."""
        client = self._redis()
        if client is None:
            return 0
        if service == NEWSAPI:
            used = int(client.get(self._newsapi_key()) or 0)
            return max(0, self.newsapi_daily_limit - used)
        key = self._groq_key()
        client.zremrangebyscore(key, 0, time.time() - _GROQ_WINDOW_SECONDS)
        return max(0, self.groq_rpm_limit - int(client.zcard(key)))

    def reset(self, service: str) -> None:
        """Clear a service's Redis keys. For tests only."""
        client = self._redis()
        if client is None:
            return
        if service == NEWSAPI:
            client.delete(self._newsapi_key())
        else:
            client.delete(self._groq_key())


_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide RateLimiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter

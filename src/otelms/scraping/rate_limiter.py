"""
Rate limiter con token bucket (Redis-backed) para scraping distribuido.
Incluye fallback rápido en memoria cuando Redis no está disponible.
"""
import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import redis.asyncio as redis

from otelms.config.settings import settings
from otelms.scraping.exceptions import RateLimitError
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class AdaptiveRateLimiter:
    """
    Rate limiter adaptativo que ajusta automáticamente el RPM basado en:
    - Éxitos: aumenta gradualmente el RPM
    - Errores 429: disminuye agresivamente el RPM
    Mantiene límites mínimos y máximos configurables.
    """

    def __init__(
        self,
        base_rpm: int = 30,
        burst: int = 5,
        min_rpm: int = 5,
        max_rpm: int = 60,
        success_threshold: int = 3,
        error_multiplier: float = 0.5,
    ):
        self.base_rpm = base_rpm
        self.burst = burst
        self.min_rpm = min_rpm
        self.max_rpm = max_rpm
        self.success_threshold = success_threshold
        self.error_multiplier = error_multiplier

        self.current_rpm = base_rpm
        self._success_count = 0

    def record_success(self) -> None:
        """Registra un request exitoso y potencialmente aumenta RPM."""
        self._success_count += 1
        if self._success_count >= self.success_threshold:
            self._success_count = 0
            self.current_rpm = min(self.current_rpm + 1, self.max_rpm)
            logger.debug("Adaptive rate limit increased", current_rpm=self.current_rpm)

    def record_429(self) -> None:
        """Registra un error 429 y reduce agresivamente el RPM."""
        self._success_count = 0
        self.current_rpm = max(int(self.current_rpm * self.error_multiplier), self.min_rpm)
        logger.warning("Adaptive rate limit decreased due to 429", current_rpm=self.current_rpm)

    def record_error(self) -> None:
        """Registra un error genérico (no 429) - reduce moderadamente."""
        self._success_count = 0
        self.current_rpm = max(int(self.current_rpm * 0.8), self.min_rpm)
        logger.debug("Adaptive rate limit decreased due to error", current_rpm=self.current_rpm)

    def get_wait_time(self) -> float:
        """Obtiene tiempo de espera entre requests basado en RPM actual."""
        return 60.0 / self.current_rpm

    def reset(self) -> None:
        """Resetea al RPM base."""
        self.current_rpm = self.base_rpm
        self._success_count = 0


class MemoryTokenBucket:
    """Token bucket en memoria (fallback sin Redis)."""

    def __init__(self, rate: int, burst: int):
        self.rate = rate
        self.burst = burst
        self.refill_rate = rate / 60.0
        self.tokens = float(burst)
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def take(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        start_time = time.monotonic()
        while True:
            async with self._lock:
                now = time.time()
                elapsed = now - self.last_refill
                self.tokens = min(self.burst, self.tokens + elapsed * self.refill_rate)
                self.last_refill = now
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                current = self.tokens
            tokens_needed = tokens - current
            wait_time = tokens_needed / self.refill_rate if self.refill_rate > 0 else 1.0
            if time.monotonic() - start_time + wait_time > timeout:
                raise RateLimitError(
                    "Rate limit exceeded (memory bucket)",
                    retry_after=int(wait_time) + 1,
                )
            await asyncio.sleep(min(wait_time, 0.1))

    async def get_available(self) -> float:
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.burst, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            return self.tokens

    async def reset(self) -> None:
        async with self._lock:
            self.tokens = float(self.burst)
            self.last_refill = time.time()


class TokenBucket:
    """
    Token Bucket algorithm para rate limiting.
    Thread-safe y distribuido usando Redis.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        key: str,
        rate: int,           # tokens per minute
        burst: int,          # max bucket size
    ):
        self.redis = redis_client
        self.key = f"ratelimit:{key}"
        self.rate = rate
        self.burst = burst
        self.refill_rate = rate / 60.0  # tokens per second

    async def take(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """
        Intenta tomar tokens del bucket.
        Bloquea hasta que estén disponibles o timeout.
        """
        start_time = time.monotonic()

        while True:
            # Lua script para operación atómica
            lua_script = """
            local key = KEYS[1]
            local rate = tonumber(ARGV[1])
            local burst = tonumber(ARGV[2])
            local tokens = tonumber(ARGV[3])
            local now = tonumber(ARGV[4])
            local refill_rate = rate / 60.0

            local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
            local current_tokens = tonumber(bucket[1])
            local last_refill = tonumber(bucket[2])

            if current_tokens == nil then
                current_tokens = burst
                last_refill = now
            else
                local elapsed = now - last_refill
                current_tokens = math.min(burst, current_tokens + elapsed * refill_rate)
                last_refill = now
            end

            if current_tokens >= tokens then
                current_tokens = current_tokens - tokens
                redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill', last_refill)
                redis.call('EXPIRE', key, 3600)
                return {1, current_tokens}
            else
                redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill', last_refill)
                redis.call('EXPIRE', key, 3600)
                return {0, current_tokens}
            end
            """

            now = time.time()
            result = await self.redis.eval(
                lua_script,
                1,
                self.key,
                self.rate,
                self.burst,
                tokens,
                now,
            )

            success = result[0] == 1
            current_tokens = result[1]

            if success:
                return True

            # Calcular tiempo de espera
            tokens_needed = tokens - current_tokens
            wait_time = tokens_needed / self.refill_rate

            if time.monotonic() - start_time + wait_time > timeout:
                raise RateLimitError(
                    f"Rate limit exceeded for {self.key}",
                    retry_after=int(wait_time) + 1,
                )

            # Esperar un poco antes de reintentar
            await asyncio.sleep(min(wait_time, 0.5))

    async def get_available(self) -> float:
        """Obtiene tokens disponibles actualmente."""
        lua_script = """
        local key = KEYS[1]
        local rate = tonumber(ARGV[1])
        local burst = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local refill_rate = rate / 60.0

        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local current_tokens = tonumber(bucket[1])
        local last_refill = tonumber(bucket[2])

        if current_tokens == nil then
            return burst
        end

        local elapsed = now - last_refill
        return math.min(burst, current_tokens + elapsed * refill_rate)
        """

        now = time.time()
        # redis.eval tipa Any; el script Lua devuelve un number (tokens).
        return cast(float, await self.redis.eval(
            lua_script, 1, self.key, self.rate, self.burst, now
        ))

    async def reset(self) -> None:
        """Resetea el bucket."""
        await self.redis.delete(self.key)


class RateLimiter:
    """
    Gestor de rate limiting por hotel y global.
    Fallback inmediato a memoria si Redis no responde (circuit breaker corto).
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self._client: redis.Redis | None = None
        self._buckets: dict[str, TokenBucket | MemoryTokenBucket] = {}
        self._redis_available: bool | None = None
        self._redis_checked_at: float = 0.0
        self._redis_retry_after_s: float = 30.0

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=settings.redis_socket_connect_timeout,
                socket_timeout=settings.redis_socket_timeout,
            )
        return self._client

    async def _ensure_redis_available(self) -> bool:
        now = time.monotonic()
        if self._redis_available is True:
            return True
        if self._redis_available is False and (now - self._redis_checked_at) < self._redis_retry_after_s:
            return False
        try:
            await asyncio.wait_for(self.client.ping(), timeout=max(0.2, float(settings.redis_socket_connect_timeout)))
            self._redis_available = True
            self._redis_checked_at = now
            return True
        except Exception as e:
            self._redis_available = False
            self._redis_checked_at = now
            logger.warning("Redis unavailable for rate limiting, using memory fallback", error=str(e))
            return False

    def get_bucket(self, hotel_id: str | None = None) -> TokenBucket | MemoryTokenBucket:
        """Obtiene o crea un bucket para el hotel (o global)."""
        key = f"hotel:{hotel_id}" if hotel_id else "global"
        if key not in self._buckets:
            # Crear bucket en memoria por defecto si Redis ya marcado caído; se migrará si vuelve
            if self._redis_available is False:
                self._buckets[key] = MemoryTokenBucket(
                    rate=settings.scraper_rate_limit_requests_per_minute,
                    burst=settings.scraper_rate_limit_burst,
                )
            else:
                self._buckets[key] = TokenBucket(
                    self.client,
                    key,
                    rate=settings.scraper_rate_limit_requests_per_minute,
                    burst=settings.scraper_rate_limit_burst,
                )
        return self._buckets[key]

    @asynccontextmanager
    async def limit(self, hotel_id: str | None = None, tokens: int = 1) -> AsyncIterator[None]:
        """Context manager que adquiere tokens antes de entrar."""
        bucket = self.get_bucket(hotel_id)
        await bucket.take(tokens)
        try:
            yield
        finally:
            pass  # Tokens ya consumidos

    async def wait_if_needed(self, hotel_id: str | None = None, tokens: int = 1) -> None:
        """Espera si es necesario antes de proceder."""
        # Check redis availability quickly and switch bucket impl if needed
        redis_ok = await self._ensure_redis_available()
        key = f"hotel:{hotel_id}" if hotel_id else "global"
        bucket = self._buckets.get(key)
        if redis_ok and isinstance(bucket, MemoryTokenBucket):
            bucket = TokenBucket(
                self.client,
                key,
                rate=settings.scraper_rate_limit_requests_per_minute,
                burst=settings.scraper_rate_limit_burst,
            )
            self._buckets[key] = bucket
        elif not redis_ok and isinstance(bucket, TokenBucket):
            bucket = MemoryTokenBucket(
                rate=settings.scraper_rate_limit_requests_per_minute,
                burst=settings.scraper_rate_limit_burst,
            )
            self._buckets[key] = bucket
        elif bucket is None:
            bucket = self.get_bucket(hotel_id)
            # re-evaluate type once
            if redis_ok and isinstance(bucket, MemoryTokenBucket):
                bucket = TokenBucket(self.client, key, rate=settings.scraper_rate_limit_requests_per_minute, burst=settings.scraper_rate_limit_burst)
                self._buckets[key] = bucket
            elif not redis_ok and isinstance(bucket, TokenBucket):
                bucket = MemoryTokenBucket(rate=settings.scraper_rate_limit_requests_per_minute, burst=settings.scraper_rate_limit_burst)
                self._buckets[key] = bucket
        try:
            await bucket.take(tokens)
        except Exception:
            # Si Redis falló en medio de la operación, degradar a memoria y permitir
            if not isinstance(bucket, MemoryTokenBucket):
                self._redis_available = False
                self._redis_checked_at = time.monotonic()
                mem = MemoryTokenBucket(rate=settings.scraper_rate_limit_requests_per_minute, burst=settings.scraper_rate_limit_burst)
                self._buckets[key] = mem
                await mem.take(tokens)
            else:
                raise

    async def get_status(self, hotel_id: str | None = None) -> dict:
        """Obtiene estado actual del rate limiter."""
        bucket = self.get_bucket(hotel_id)
        available = await bucket.get_available()
        return {
            "key": "global" if hotel_id is None else f"hotel:{hotel_id}",
            "available_tokens": round(available, 2),
            "max_tokens": settings.scraper_rate_limit_burst,
            "rate_per_minute": settings.scraper_rate_limit_requests_per_minute,
            "backend": "memory" if isinstance(bucket, MemoryTokenBucket) else "redis",
        }

    async def close(self) -> None:
        if self._client:
            await self._client.close()


# Instancia global
rate_limiter = RateLimiter()


async def get_rate_limiter() -> RateLimiter:
    """Dependency para FastAPI."""
    return rate_limiter


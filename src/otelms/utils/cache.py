"""
Cache wrapper con soporte para Redis y diskcache fallback.
"""
import asyncio
import fnmatch
import pickle
import time
from collections.abc import Callable
from typing import Any, cast

import diskcache
import redis.asyncio as redis

from otelms.config.settings import settings
from otelms.utils.logging import get_logger

logger = get_logger(__name__)


class CacheBackend:
    """Backend de cache abstracto."""

    async def get(self, key: str) -> Any | None:
        raise NotImplementedError

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        raise NotImplementedError

    async def delete(self, key: str) -> bool:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    async def clear_pattern(self, pattern: str) -> int:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class RedisCache(CacheBackend):
    """Cache con Redis."""

    def __init__(self, url: str, max_connections: int = 20):
        connect_timeout = getattr(settings, "redis_socket_connect_timeout", 0.5)
        self._pool = redis.ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=False,  # Usamos pickle para serialización
            socket_connect_timeout=connect_timeout,
            socket_timeout=connect_timeout,
        )
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis(connection_pool=self._pool)
        return self._client

    async def get(self, key: str) -> Any | None:
        try:
            data = await self.client.get(key)
            if data:
                # pickle es el único serializador stdlib que round-tripa
                # objetos arbitrarios (datetime, Decimal, set) que guarda el
                # sync service; json los obligaría a str. El trust boundary
                # es nuestro propio Redis (mismo stack, misma red), no una
                # entrada externa, así que el riesgo de deserialización
                # arbitraria aquí es aceptable. Si en el futuro abramos el
                # cache a datos de terceros, cambiar a msgpack/json.
                # decode_responses=False garantiza que data es bytes.
                return pickle.loads(cast(bytes, data))
        except Exception as e:
            logger.warning("Redis get error", key=key, error=str(e))
        return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            data = pickle.dumps(value)
            if ttl:
                return cast(bool, await self.client.setex(key, ttl, data))
            return cast(bool, await self.client.set(key, data))
        except Exception as e:
            logger.warning("Redis set error", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        try:
            return await self.client.delete(key) > 0
        except Exception as e:
            logger.warning("Redis delete error", key=key, error=str(e))
            return False

    async def exists(self, key: str) -> bool:
        try:
            return await self.client.exists(key) > 0
        except Exception:
            return False

    async def clear_pattern(self, pattern: str) -> int:
        try:
            count = 0
            async for key in self.client.scan_iter(match=pattern):
                await self.client.delete(key)
                count += 1
            return count
        except Exception as e:
            logger.warning("Redis clear_pattern error", pattern=pattern, error=str(e))
            return 0

    async def close(self) -> None:
        if self._client:
            await self._client.close()
        await self._pool.disconnect()


class DiskCacheBackend(CacheBackend):
    """Cache con diskcache (fallback local)."""

    def __init__(self, directory: str = "cache", max_size_mb: int = 100):
        self._cache = diskcache.Cache(
            directory,
            size_limit=max_size_mb * 1024 * 1024,
        )

    async def get(self, key: str) -> Any | None:
        try:
            return self._cache.get(key)
        except Exception as e:
            logger.warning("DiskCache get error", key=key, error=str(e))
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            if ttl:
                self._cache.set(key, value, expire=ttl)
            else:
                self._cache.set(key, value)
            return True
        except Exception as e:
            logger.warning("DiskCache set error", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        try:
            return self._cache.pop(key, None) is not None
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        try:
            return key in self._cache
        except Exception:
            return False

    async def clear_pattern(self, pattern: str) -> int:
        try:
            # diskcache no soporta pattern matching nativamente
            # Iterar todas las keys (puede ser lento para caches grandes)
            count = 0
            for key in list(self._cache.iterkeys()):
                if fnmatch.fnmatch(key, pattern):
                    self._cache.delete(key)
                    count += 1
            return count
        except Exception as e:
            logger.warning("DiskCache clear_pattern error", pattern=pattern, error=str(e))
            return 0

    async def close(self) -> None:
        self._cache.close()


class MemoryCacheBackend(CacheBackend):
    """Cache en memoria acotado con TTL para dev/test sin Redis."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max_entries
        self._store: dict[str, tuple[Any, float]] = {}

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now >= exp]
        for k in expired:
            self._store.pop(k, None)

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        val, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        # Mover al final para evicción LRU simple
        self._store.pop(key, None)
        self._store[key] = (val, expires_at)
        return val

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if self._max_entries <= 0:
            return False
        self._purge_expired()
        if len(self._store) >= self._max_entries and key not in self._store:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)
        expires_at = (time.monotonic() + ttl) if ttl is not None else float("inf")
        self._store.pop(key, None)
        self._store[key] = (value, expires_at)
        return True

    async def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return (await self.get(key)) is not None

    async def clear_pattern(self, pattern: str) -> int:
        keys = [k for k in list(self._store.keys()) if fnmatch.fnmatch(k, pattern)]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)


class CacheManager:
    """Gestor de cache con fallback automático."""

    def __init__(self) -> None:
        self._backend: CacheBackend | None = None
        self._use_redis = False

    @property
    def use_redis(self) -> bool:
        """Indica si el backend activo es Redis."""
        return self._use_redis

    async def initialize(self) -> None:
        """Inicializa el backend preferido (Redis) con fallback inmediato a memoria."""
        if not settings.cache_enabled:
            logger.info("Cache deshabilitado por configuración")
            self._backend = MemoryCacheBackend(max_entries=0)
            self._use_redis = False
            return

        # Intentar Redis primero con un solo ping rápido (sin health_check con set/get/delete)
        redis_backend: RedisCache | None = None
        try:
            redis_backend = RedisCache(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
            )
            connect_timeout = float(getattr(settings, "redis_socket_connect_timeout", 0.5) or 0.5)
            await asyncio.wait_for(redis_backend.client.ping(), timeout=connect_timeout)
            self._backend = redis_backend
            self._use_redis = True
            logger.info("Cache inicializado con Redis")
        except Exception as e:
            if redis_backend is not None:
                try:
                    await redis_backend.close()
                except Exception:
                    pass
            logger.warning("Redis no disponible, usando cache en memoria como fallback", error=str(e))
            self._backend = MemoryCacheBackend()
            self._use_redis = False

    async def reconnect_redis(self) -> bool:
        """Reintenta conectar a Redis y cambia el backend activo si tiene éxito."""
        if not settings.cache_enabled:
            return False

        redis_backend: RedisCache | None = None
        try:
            redis_backend = RedisCache(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
            )
            connect_timeout = float(getattr(settings, "redis_socket_connect_timeout", 0.5) or 0.5)
            await asyncio.wait_for(redis_backend.client.ping(), timeout=connect_timeout)
            old_backend = self._backend
            self._backend = redis_backend
            self._use_redis = True
            if old_backend is not None and old_backend is not redis_backend:
                try:
                    await old_backend.close()
                except Exception:
                    pass
            logger.info("Cache reconectado a Redis")
            return True
        except Exception as e:
            if redis_backend is not None:
                try:
                    await redis_backend.close()
                except Exception:
                    pass
            logger.warning("Reconexión a Redis fallida, manteniendo fallback", error=str(e))
            return False

    @property
    def backend(self) -> CacheBackend:
        if self._backend is None:
            raise RuntimeError("Cache no inicializado. Llama a initialize() primero.")
        return self._backend

    async def get(self, key: str) -> Any | None:
        return await self.backend.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        if ttl is None:
            ttl = settings.memory_cache_ttl_seconds if not self._use_redis else settings.cache_ttl_seconds
        return await self.backend.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        return await self.backend.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.backend.exists(key)

    async def clear_pattern(self, pattern: str) -> int:
        return await self.backend.clear_pattern(pattern)

    async def get_or_set(
        self, key: str, factory: Callable[[], Any] | Any, ttl: int | None = None,
    ) -> Any:
        """Obtiene del cache o ejecuta factory y guarda resultado."""
        value = await self.get(key)
        if value is not None:
            return value
        value = await factory() if callable(factory) else factory
        await self.set(key, value, ttl)
        return value

    async def close(self) -> None:
        if self._backend:
            await self._backend.close()


# Instancia global
cache = CacheManager()


async def get_cache() -> CacheManager:
    """Dependency para FastAPI."""
    return cache

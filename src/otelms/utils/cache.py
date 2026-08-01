"""
Cache wrapper con soporte para Redis y diskcache fallback.
"""
import json
import pickle
from contextlib import asynccontextmanager
from typing import Any, Optional

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
        self._pool = redis.ConnectionPool.from_url(
            url,
            max_connections=max_connections,
            decode_responses=False,  # Usamos pickle para serialización
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
                return pickle.loads(data)
        except Exception as e:
            logger.warning("Redis get error", key=key, error=str(e))
        return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            data = pickle.dumps(value)
            if ttl:
                return await self.client.setex(key, ttl, data)
            return await self.client.set(key, data)
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
            import fnmatch
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


class CacheManager:
    """Gestor de cache con fallback automático."""

    def __init__(self):
        self._backend: CacheBackend | None = None
        self._use_redis = False

    async def initialize(self) -> None:
        """Inicializa el backend preferido (Redis) con fallback a diskcache."""
        if not settings.cache_enabled:
            logger.info("Cache deshabilitado por configuración")
            self._backend = DiskCacheBackend()  # Dummy que no hace nada
            return

        # Intentar Redis primero
        try:
            self._backend = RedisCache(
                settings.redis_url,
                max_connections=settings.redis_max_connections,
            )
            # Test connection
            await self._backend.set("_health_check", "ok", ttl=1)
            await self._backend.get("_health_check")
            await self._backend.delete("_health_check")
            self._use_redis = True
            logger.info("Cache inicializado con Redis")
        except Exception as e:
            logger.warning("Redis no disponible, usando diskcache como fallback", error=str(e))
            self._backend = DiskCacheBackend(max_size_mb=settings.cache_max_size_mb)
            self._use_redis = False

    @property
    def backend(self) -> CacheBackend:
        if self._backend is None:
            raise RuntimeError("Cache no inicializado. Llama a initialize() primero.")
        return self._backend

    async def get(self, key: str) -> Any | None:
        return await self.backend.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        ttl = ttl or settings.cache_ttl_seconds
        return await self.backend.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        return await self.backend.delete(key)

    async def exists(self, key: str) -> bool:
        return await self.backend.exists(key)

    async def clear_pattern(self, pattern: str) -> int:
        return await self.backend.clear_pattern(pattern)

    async def get_or_set(self, key: str, factory, ttl: int | None = None) -> Any:
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
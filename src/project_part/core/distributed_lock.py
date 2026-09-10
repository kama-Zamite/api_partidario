import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

_RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class DistributedLock:
    def __init__(self, redis, key: str, ttl_seconds: int = 300):
        self.redis = redis
        self.key = key
        self.ttl = ttl_seconds
        self.token: Optional[str] = None

    async def acquire(self) -> bool:
        """Tenta obter o lock. True = esta instância deve correr o job."""
        self.token = str(uuid.uuid4())
        # SET key token NX EX ttl
        ok = await self.redis.set(self.key, self.token, nx=True, ex=self.ttl)
        if ok:
            logger.info('Lock adquirido: %s', self.key)
            return True
        logger.info('Lock ocupado, a saltar job: %s', self.key)
        return False

    async def release(self) -> None:
        """Liberta só se ainda formos donos do lock."""
        if not self.token:
            return
        try:
            await self.redis.eval(_RELEASE_LUA, 1, self.key, self.token)
            logger.info('Lock libertado: %s', self.key)
        except Exception as e:
            logger.warning('Falha ao libertar lock %s: %s', self.key, e)
        finally:
            self.token = None


async def with_distributed_lock(redis, key: str, ttl_seconds: int, coro_factory):
    """
    Executa coro_factory() só se conseguir o lock.
    coro_factory deve ser async callable sem args: async def job(): ...
    """
    lock = DistributedLock(redis, key=key, ttl_seconds=ttl_seconds)
    if not await lock.acquire():
        return False
    try:
        await coro_factory()
        return True
    finally:
        await lock.release()
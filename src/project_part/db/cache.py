import redis.asyncio as aioredis

from project_part.core.setting import settings

redis_pool = aioredis.ConnectionPool.from_url(
    settings.DATABASE_REDIS_URL,
    encoding='utf-8',
    decode_responses=True,
    max_connections=50,
    socket_timeout=5.0,
    socket_connect_timeout=5.0,
    retry_on_timeout=True,
)

redis_client = aioredis.Redis(connection_pool=redis_pool)


async def get_redis():
    yield redis_client

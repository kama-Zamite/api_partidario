import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from project_part.core.setting import settings
from project_part.db.cache import redis_client
from project_part.db.session import engine

logger = logging.getLogger('uvicorn.error')

health_router = APIRouter(prefix='/health', tags=['Infraestrutura'])


@health_router.get('', status_code=status.HTTP_200_OK)
async def health_check(response: Response):
    """Endpoint de Health Check para monitoramento da infraestrutura.
    Verifica a saúde do banco de dados Postgres e do cache Redis.
        - Postgres: Verifica se a conexão é bem-sucedida e se uma consulta simples
            retorna resultados.
        - Redis: Verifica se o cache está respondendo ao comando PING.
    Retorna um status geral de saúde:
        - "healthy": Ambos Postgres e Redis estão operacionais.
        - "degraded": Postgres está operacional, mas Redis está offline (modo fallback).
        - "unhealthy": Postgres está offline, o que é crítico para a aplicação.
    Em ambientes de produção, detalhes específicos sobre falhas não são expostos para evitar
    potenciais vetores de ataque, retornando apenas o status geral. Em ambientes de desenvolvimento, informações adicionais sobre a causa da falha são incluídas
    na resposta para facilitar a depuração. Logs detalhados são gerados para cada falha detectada, com níveis de severidade apropriados (CRITICAL para falhas de banco de dados e WARNING para falhas de cache), garantindo que os administradores possam monitorar e responder rapidamente a problemas de infraestrutura. Este endpoint é projetado para ser leve e eficiente, permitindo que seja chamado frequentemente por sistemas de monitoramento sem causar impacto significativo no desempenho da aplicação.

    """
    is_production = settings.ENV.lower() == 'production'
    postgres_ok, redis_ok = True, True

    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
    except Exception as e:
        postgres_ok = False
        logger.critical('[CRÍTICO] Banco de dados Postgres offline no Healthcheck: %s', str(e))

    try:
        await redis_client.ping()
    except Exception as e:
        redis_ok = False
        logger.warning('[AVISO] Redis offline no Healthcheck. Sistema em modo Fallback: %s', str(e))

    if not postgres_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        if is_production:
            return {'status': 'unhealthy'}
        return {'status': 'unhealthy', 'reason': 'database_down'}

    if not redis_ok:
        return {'status': 'degraded'}

    return {'status': 'healthy'}

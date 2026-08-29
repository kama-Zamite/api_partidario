import pytest
from fastapi import status

from project_part.core import health


class _Response:
    status_code = 200


@pytest.mark.anyio
async def test_health_retorna_healthy_quando_dependencias_estao_disponiveis(
    monkeypatch,
):
    class Engine:
        def connect(self):  # noqa: PLR6301
            class Context:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def execute(self, statement):  # noqa: PLR6301
                    return None

            return Context()

    class Redis:
        async def ping(self):  # noqa: PLR6301
            return True

    monkeypatch.setattr(health, 'engine', Engine())
    monkeypatch.setattr(health, 'redis_client', Redis())

    resposta = await health.health_check(_Response())
    assert resposta == {'status': 'healthy'}


@pytest.mark.anyio
async def test_health_retorna_degraded_quando_redis_falha(monkeypatch):
    class Engine:
        def connect(self):  # noqa: PLR6301
            class Context:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

                async def execute(self, statement):  # noqa: PLR6301
                    return None

            return Context()

    class Redis:
        async def ping(self):  # noqa: PLR6301
            raise ConnectionError('redis indisponível')

    monkeypatch.setattr(health, 'engine', Engine())
    monkeypatch.setattr(health, 'redis_client', Redis())

    assert await health.health_check(_Response()) == {'status': 'degraded'}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('environment', 'expected'),
    [
        ('dev', {'status': 'unhealthy', 'reason': 'database_down'}),
        ('production', {'status': 'unhealthy'}),
    ],
)
async def test_health_retorna_503_quando_banco_falha(
    monkeypatch, environment, expected
):
    class Engine:
        def connect(self):  # noqa: PLR6301
            class Context:
                async def __aenter__(self):
                    raise ConnectionError('banco indisponível')

                async def __aexit__(self, *args):
                    pass

            return Context()

    class Redis:
        async def ping(self):  # noqa: PLR6301
            return True

    resposta_http = _Response()
    monkeypatch.setattr(health, 'engine', Engine())
    monkeypatch.setattr(health, 'redis_client', Redis())
    monkeypatch.setattr(health.settings, 'ENV', environment)

    assert await health.health_check(resposta_http) == expected
    assert resposta_http.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from project_part.api.notification_router.schemas import (
    NotificationPreferencesUpdate,
)
from project_part.main import app
from project_part.api.notification_router.notification_router import (
    atualizar_preferencias_notificacao,
    obter_preferencias_notificacao,
)


def test_rotas_notifications_tem_leitura_e_atualizacao():
    rotas = {
        (m, r.path): r
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/notifications/')
    }
    assert {key: route.status_code or 200 for key, route in rotas.items()} == {
        ('GET', '/notifications/preferencias'): 200,
        ('PATCH', '/notifications/preferencias'): 200,
    }
    assert all(route.dependant.dependencies for route in rotas.values())


def test_preferencias_aceitam_valores_booleanos_ou_ausentes():
    preferencias = NotificationPreferencesUpdate(eventos_mobilizacoes=True)
    assert preferencias.eventos_mobilizacoes is True
    assert preferencias.noticias_partido is None

    with pytest.raises(ValidationError):
        NotificationPreferencesUpdate(noticias_partido='nao-booleano')


@pytest.mark.anyio
async def test_obter_preferencias_retorna_todos_os_toggles():
    usuario = SimpleNamespace(
        id='user-1',
        notificacoes_gerais=True,
        comunicados_oficiais=False,
        eventos_mobilizacoes=True,
        contribuicoes_quota=False,
        noticias_partido=True,
    )

    assert await obter_preferencias_notificacao(usuario) == {
        'notificacoes_gerais': True,
        'comunicados_oficiais': False,
        'eventos_mobilizacoes': True,
        'contribuicoes_quota': False,
        'noticias_partido': True,
    }


@pytest.mark.anyio
async def test_atualizar_preferencias_persiste_apenas_campos_informados():
    usuario = SimpleNamespace(id='user-1', noticias_partido=False)
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    resposta = await atualizar_preferencias_notificacao(
        NotificationPreferencesUpdate(noticias_partido=True), session, usuario
    )

    assert resposta['detail']
    assert usuario.noticias_partido is True
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(usuario)


@pytest.mark.anyio
async def test_atualizar_preferencias_reverte_transacao_em_erro():
    usuario = SimpleNamespace(id='user-1')
    session = SimpleNamespace(
        commit=AsyncMock(side_effect=RuntimeError('falha')),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )

    with pytest.raises(HTTPException) as erro:
        await atualizar_preferencias_notificacao(
            NotificationPreferencesUpdate(), session, usuario
        )

    assert erro.value.status_code == 500
    session.rollback.assert_awaited_once()

from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.routing import APIRoute
import pytest

from project_part.api.finance.finance_router import validar_pagamento_quota
from project_part.main import app


def test_rota_finance_de_validacao_de_quota_esta_protegida():
    rota = next(
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == '/finance/quotas/validar/{user_id}'
    )

    assert rota.methods == {'POST'}
    assert (rota.status_code or HTTPStatus.OK) == HTTPStatus.OK
    assert rota.dependant.dependencies


@pytest.mark.anyio
async def test_validar_quota_retorna_erro_quando_militante_nao_existe():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))

    resposta = await validar_pagamento_quota(
        '00000000-0000-0000-0000-000000000001', session
    )

    assert resposta == {'detail': 'Militante não encontrado.'}


@pytest.mark.anyio
async def test_validar_quota_dispara_notificacao_e_confirma_pagamento(
    monkeypatch,
):
    from project_part.api.finance import finance_router

    usuario = SimpleNamespace(id='user-1')
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=usuario), commit=AsyncMock()
    )
    notificar = AsyncMock()
    monkeypatch.setattr(
        finance_router, 'disparar_notificacao_usuario', notificar
    )

    resposta = await validar_pagamento_quota(
        '00000000-0000-0000-0000-000000000001', session
    )

    assert resposta['detail'].startswith('Quota validada')
    notificar.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_validar_quota_reverte_transacao_quando_commit_falha(
    monkeypatch,
):
    from project_part.api.finance import finance_router

    usuario = SimpleNamespace(id='user-1')
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=usuario),
        commit=AsyncMock(side_effect=RuntimeError('falha')),
        rollback=AsyncMock(),
    )
    monkeypatch.setattr(
        finance_router, 'disparar_notificacao_usuario', AsyncMock()
    )

    resposta = await validar_pagamento_quota(
        '00000000-0000-0000-0000-000000000001', session
    )

    assert resposta == {'detail': 'Erro ao validar quota.'}
    session.rollback.assert_awaited_once()

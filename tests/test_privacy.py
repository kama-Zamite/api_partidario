import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from project_part.api.privacy.schemas import (
    CookiesPersonalizacao,
    PartilharDados,
)
from project_part.main import app
from project_part.api.privacy.privacy_router import (
    atualizar_privacidade,
    descarregar_dados_utilizador,
    partilhar_dados,
)


def test_rotas_privacy_tem_fluxos_protegidos():
    rotas = {
        (m, r.path): r
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/privacy/')
    }
    assert {key: route.status_code or 200 for key, route in rotas.items()} == {
        ('POST', '/privacy/solicitar-dados'): 200,
        ('PATCH', '/privacy/partilhar-dados'): 200,
        ('PATCH', '/privacy/cookies-personalizado'): 200,
    }
    assert all(route.dependant.dependencies for route in rotas.values())


def test_schemas_de_privacidade_aceitam_booleanos():
    assert PartilharDados(partilha_dados=True).partilha_dados is True
    assert (
        CookiesPersonalizacao(
            cookies_personalizacao=False
        ).cookies_personalizacao
        is False
    )

    for schema, campo in (
        (PartilharDados, 'partilha_dados'),
        (CookiesPersonalizacao, 'cookies_personalizacao'),
    ):
        with pytest.raises(ValidationError):
            schema(**{campo: 'valor-invalido'})


@pytest.mark.anyio
async def test_partilha_de_dados_persiste_preferencia():
    usuario = SimpleNamespace(
        id='user-1', email='user@example.com', partilha_dados=False
    )
    session = SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock())

    resposta = await partilhar_dados(
        PartilharDados(partilha_dados=True), session, usuario
    )

    assert resposta['configuracoes'] == {'partilha_dados': True}
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(usuario)


@pytest.mark.anyio
async def test_privacidade_reverte_em_erro_de_persistencia():
    usuario = SimpleNamespace(
        id='user-1', email='user@example.com', cookies_personalizacao=False
    )
    session = SimpleNamespace(
        commit=AsyncMock(side_effect=RuntimeError('falha')),
        refresh=AsyncMock(),
        rollback=AsyncMock(),
    )

    with pytest.raises(HTTPException) as erro:
        await atualizar_privacidade(
            CookiesPersonalizacao(cookies_personalizacao=True),
            session,
            usuario,
        )

    assert erro.value.status_code == 500
    session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_exportacao_de_dados_retorna_404_quando_usuario_nao_existe():
    usuario = SimpleNamespace(id='user-1', email='user@example.com')
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as erro:
        await descarregar_dados_utilizador(None, session, usuario)

    assert erro.value.status_code == 404


@pytest.mark.anyio
async def test_exportacao_de_dados_retorna_json_para_usuario_encontrado():
    usuario = SimpleNamespace(id='user-1', email='user@example.com')
    resultado = SimpleNamespace(
        nome_completo='Maria Silva',
        email='user@example.com',
        nif='123456789AB123',
        militante_numero=None,
        genero='MULHER',
        data_nascimento=None,
        telefone='+244923000000',
        criado_em=None,
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=resultado))

    resposta = await descarregar_dados_utilizador(None, session, usuario)
    corpo = b''.join([chunk async for chunk in resposta.body_iterator])

    assert resposta.media_type == 'application/json'
    assert b'Maria Silva' in corpo

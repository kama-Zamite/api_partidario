import pytest
from fastapi.routing import APIRoute
from fastapi import HTTPException
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import AsyncMock

from project_part.api.Auth_2fa.schemas import Code2FA
from project_part.api.Auth_2fa.router_2fa import (
    disable_2fa,
    setup_2fa,
    verificar_segundo_fator,
    verify_and_enable_2fa,
)
from project_part.main import app


def test_rotas_2fa_tem_fluxos_de_configuracao_e_protecao():
    rotas = {
        (method, route.path): route
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if route.path.startswith('/auth/2fa')
    }

    assert set(rotas) == {
        ('POST', '/auth/2fa/setup'),
        ('POST', '/auth/2fa/verify-and-enable'),
        ('POST', '/auth/2fa/disable'),
    }
    assert all(route.dependant.dependencies for route in rotas.values())


@pytest.mark.parametrize('codigo', ['12345', '1234567', ''])
def test_codigo_2fa_invalido_e_rejeitado(codigo):
    with pytest.raises(ValidationError):
        Code2FA(codigo=codigo)


@pytest.mark.anyio
async def test_setup_2fa_rejeita_usuario_ja_ativado():
    usuario = SimpleNamespace(two_factor_enabled=True)

    with pytest.raises(HTTPException) as erro:
        await setup_2fa(usuario, SimpleNamespace())

    assert erro.value.status_code == 400


@pytest.mark.anyio
async def test_setup_2fa_cria_segredo_e_uri(monkeypatch):
    from project_part.api.Auth_2fa import router_2fa

    usuario = SimpleNamespace(
        two_factor_enabled=False, email='user@example.com'
    )
    session = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(
        router_2fa.pyotp, 'random_base32', lambda: 'ABCDEFGHIJKLMNOP'
    )

    resposta = await setup_2fa(usuario, session)

    assert usuario.two_factor_secret == 'ABCDEFGHIJKLMNOP'
    assert resposta['provisioning_uri'].startswith('otpauth://totp/')
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_ativacao_2fa_rejeita_segredo_ausente():
    usuario = SimpleNamespace(two_factor_enabled=False, two_factor_secret=None)

    with pytest.raises(HTTPException) as erro:
        await verify_and_enable_2fa(
            Code2FA(codigo='123456'), usuario, SimpleNamespace()
        )

    assert erro.value.status_code == 400


@pytest.mark.anyio
async def test_desativacao_2fa_rejeita_codigo_expirado(monkeypatch):
    from project_part.api.Auth_2fa import router_2fa

    class Totp:
        def verify(self, codigo, valid_window):
            return False

    monkeypatch.setattr(router_2fa.pyotp, 'TOTP', lambda secret: Totp())
    usuario = SimpleNamespace(
        two_factor_enabled=True, two_factor_secret='segredo'
    )

    with pytest.raises(HTTPException) as erro:
        await disable_2fa(Code2FA(codigo='123456'), usuario, SimpleNamespace())

    assert erro.value.status_code == 400


@pytest.mark.anyio
async def test_codigo_backup_usado_nao_pode_ser_reutilizado(monkeypatch):
    from project_part.api.Auth_2fa import router_2fa

    codigo = SimpleNamespace(code_hash='hash', used=False)
    resultado = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [codigo])
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=resultado), commit=AsyncMock()
    )
    monkeypatch.setattr(
        router_2fa, 'verify_password', lambda recebido, salvo: True
    )

    assert await verificar_segundo_fator('user-1', '12345678', session) is True
    assert codigo.used is True
    session.commit.assert_awaited_once()

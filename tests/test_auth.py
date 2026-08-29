import uuid

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from project_part.api.auth.schemas import (
    Code2FA,
    Login2FARequest,
    PedidoRecuperacao,
    RedefinirSenhaSchema,
)
from project_part.main import app


def test_rotas_auth_expoem_todos_os_fluxos_e_status_esperados():
    esperadas = {
        ('POST', '/auth/login'): 200,
        ('POST', '/auth/login/2fa-verify'): 200,
        ('POST', '/auth/recuperar-senha'): 200,
        ('POST', '/auth/redefinir-senha'): 200,
        ('POST', '/auth/refresh'): 204,
        ('GET', '/auth/debug/cookies'): 200,
        ('POST', '/auth/logout'): 204,
        ('POST', '/auth/permissoes/create'): 201,
        ('GET', '/auth/permissoes/list'): 200,
        ('POST', '/auth/role/create'): 201,
        ('GET', '/auth/role/list'): 200,
        ('PUT', '/auth/permissoes/upgrade/{id_permissao}'): 200,
        ('DELETE', '/auth/permissoes/delete/{id_permissao}'): 200,
        ('PUT', '/auth/role/upgrade/{id_role}'): 200,
        ('DELETE', '/auth/role/delete/{id_role}'): 200,
    }
    atuais = {
        (method, route.path): route.status_code or 200
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if route.path.startswith('/auth/')
        and not route.path.startswith('/auth/2fa')
    }

    assert atuais == esperadas


@pytest.mark.parametrize('email', ['', 'nao-e-email', 'usuario@'])
def test_recuperacao_rejeita_email_invalido(email):
    with pytest.raises(ValidationError):
        PedidoRecuperacao(email=email)


@pytest.mark.parametrize(
    'password',
    ['curta1!', 'semmaiuscula1!', 'SEM_MINUSCULA1!', 'SemEspecial1'],
)
def test_redefinicao_rejeita_senha_sem_complexidade(password):
    with pytest.raises(ValidationError):
        RedefinirSenhaSchema(
            token='token-seguro',
            password=password,
            confirmar_password=password,
        )


def test_redefinicao_rejeita_confirmacao_diferente():
    with pytest.raises(ValidationError):
        RedefinirSenhaSchema(
            token='token-seguro',
            password='SenhaSegura1!',
            confirmar_password='OutraSenha1!',
        )


def test_codigos_2fa_e_login_2fa_exigem_tamanho_valido():
    assert Code2FA(codigo='123456').codigo == '123456'
    assert (
        Login2FARequest(user_id=uuid.uuid4(), codigo='123456').codigo
        == '123456'
    )

    with pytest.raises(ValidationError):
        Code2FA(codigo='12345')
    with pytest.raises(ValidationError):
        Login2FARequest(user_id=uuid.uuid4(), codigo='12345')

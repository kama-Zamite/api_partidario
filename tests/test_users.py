from datetime import date

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from project_part.api.users.schemas import CreateUser
from project_part.main import app


def test_todas_as_rotas_user_tem_contrato_de_sucesso():
    esperadas = {
        ('POST', '/user/create'): 201,
        ('PATCH', '/user/perfil/password'): 204,
        ('PUT', '/user/perfil/upgrade'): 200,
        ('GET', '/user/perfil'): 200,
        ('PATCH', '/user/upload-foto'): 200,
        ('GET', '/user/listar'): 200,
        ('GET', '/user/dashboard/militantes-provincia'): 200,
        ('POST', '/user/solicitar/militancia'): 201,
        ('POST', '/user/card/solicitar'): 201,
        ('GET', '/user/card'): 200,
        ('GET', '/user/notificacoes'): 200,
        ('GET', '/user/notificacoes/nao-lidas'): 200,
        ('GET', '/user/notificacoes/dashboard'): 200,
        ('GET', '/user/notificacoes/lidas'): 200,
        ('PATCH', '/user/notificacoes/{id_notificacao}/ler'): 200,
        ('GET', '/user/{user_id}'): 200,
        ('DELETE', '/user/delete/'): 200,
    }
    atuais = {
        (m, r.path): r.status_code or 200
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/user/')
    }
    assert atuais == esperadas


def _dados_usuario(**alteracoes):
    dados = {
        'nome_completo': 'Maria Silva',
        'email': 'maria@example.com',
        'password': 'SenhaSegura1!',
        'confirmar_password': 'SenhaSegura1!',
        'data_nascimento': date(1990, 1, 1),
        'nif': '123456789AB123',
        'militante_numero': None,
        'telefone': '923000000',
        'nome_provincia': 'Luanda',
        'nome_municipio': 'Viana',
    }
    dados.update(alteracoes)
    return dados


def test_cadastro_normaliza_telefone_e_aceita_dados_validos():
    usuario = CreateUser(**_dados_usuario())
    assert usuario.telefone == '+244923000000'


@pytest.mark.parametrize(
    'alteracoes',
    [
        {'email': 'email-invalido'},
        {'nome_completo': 'Maria'},
        {'telefone': '111111111'},
        {'nif': '123'},
        {'password': 'semcomplexidade'},
        {'confirmar_password': 'OutraSenha1!'},
    ],
)
def test_cadastro_rejeita_campos_invalidos(alteracoes):
    with pytest.raises(ValidationError):
        CreateUser(**_dados_usuario(**alteracoes))

from http import HTTPStatus

from fastapi.routing import APIRoute

from project_part.main import app


def test_rota_raiz_tem_contrato_publico():
    rota = next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == '/'
    )

    assert rota.methods == {'GET'}
    assert (rota.status_code or HTTPStatus.OK) == HTTPStatus.OK


def test_rota_raiz_responde_com_sucesso(clientTest):
    response = clientTest.get(
        'http://127.0.0.1/', headers={'Host': '127.0.0.1:8000'}
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'msg': 'rota criada com sucesso!'}

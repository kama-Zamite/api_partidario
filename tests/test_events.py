from fastapi.routing import APIRoute

from project_part.main import app


def test_todas_as_rotas_event_e_status_de_sucesso():
    esperadas = {
        ('POST', '/event/create'): 201,
        ('GET', '/event/current_user/list/'): 200,
        ('GET', '/event/list'): 200,
        ('GET', '/event/get/{id_event}'): 200,
        ('PUT', '/event/upgrade/{id_event}'): 200,
        ('DELETE', '/event/delete/{id_event}'): 200,
    }
    atuais = {
        (m, r.path): r.status_code or 200
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/event/')
    }
    assert atuais == esperadas


def test_endpoints_de_evento_com_usuario_exigem_dependencias_de_seguranca():
    protegidas = (
        '/event/create',
        '/event/current_user/list/',
        '/event/upgrade/{id_event}',
        '/event/delete/{id_event}',
    )
    rotas = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path in protegidas
    ]
    assert len(rotas) == len(protegidas)
    assert all(route.dependant.dependencies for route in rotas)

from fastapi.routing import APIRoute

from project_part.main import app


def test_todas_as_rotas_provincia_e_municipio_estao_protegidas():
    esperadas = {
        ('POST', '/provincia/create'): 201,
        ('POST', '/provincia/municipio/create'): 201,
        ('GET', '/provincia/list'): 200,
        ('PUT', '/provincia/upgrade/{id_provincia}'): 200,
        ('DELETE', '/provincia/delete/{id_provincia}'): 200,
        ('PUT', '/provincia/municipio/upgrade/{id_municipio}'): 200,
        ('DELETE', '/provincia/municipio/delete/{id_municipio}'): 200,
        ('GET', '/provincia/list/{id_provincia}'): 200,
    }
    rotas = {
        (m, r.path): r
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/provincia/')
    }
    assert {
        key: route.status_code or 200 for key, route in rotas.items()
    } == esperadas
    assert all(route.dependant.dependencies for route in rotas.values())

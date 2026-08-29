from fastapi.routing import APIRoute

from project_part.main import app


def test_todas_as_rotas_news_e_status_de_sucesso():
    esperadas = {
        ('POST', '/news/categories/create'): 201,
        ('POST', '/news/create'): 201,
        ('GET', '/news/list'): 200,
        ('GET', '/news/{id_news}'): 200,
        ('PATCH', '/news/{id_news}/status'): 200,
        ('PATCH', '/news/{id_news}/categoria'): 200,
        ('PUT', '/news/{id_news}'): 200,
        ('DELETE', '/news/{id_news}'): 200,
        ('PUT', '/news/categories/upgrade/{id_categoria}'): 200,
        ('DELETE', '/news/categories/deletar/{id_categoria}'): 200,
        ('GET', '/news/categories/{id_categoria}'): 200,
        ('PUT', '/news/upgrade/{id_news}'): 200,
    }
    atuais = {
        (m, r.path): r.status_code or 200
        for r in app.routes
        if isinstance(r, APIRoute)
        for m in r.methods
        if r.path.startswith('/news/')
    }
    assert atuais == esperadas


def test_operacoes_de_escrita_de_noticias_exigem_dependencias():
    escritas = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path.startswith('/news/')
        and r.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}
    ]
    assert escritas
    assert all(route.dependant.dependencies for route in escritas)

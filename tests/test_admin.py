from fastapi.routing import APIRoute

from project_part.main import app


def test_todas_as_rotas_admin_e_status_de_sucesso():
    esperadas = {
        ('POST', '/admin/set-scope'): 201,
        ('GET', '/admin/scope/list'): 200,
        ('GET', '/admin/audoitLog'): 200,
        ('GET', '/admin/notificacoes'): 200,
        ('GET', '/admin/notificacoes/lidas'): 200,
        ('PATCH', '/admin/notificacoes/{id_notificacao}/ler'): 200,
        ('GET', '/admin/scope/{scope_id}'): 200,
        ('DELETE', '/admin/scope/{scope_id}'): 200,
        ('PUT', '/admin/role/militante-upgrade/{id_militante}'): 200,
        ('POST', '/admin/card/militante/{id_militante}/aprovado'): 200,
        ('POST', '/admin/card/militante/{id_militante}/rejeitar'): 200,
    }
    atuais = {
        (method, r.path): r.status_code or 200
        for r in app.routes
        if isinstance(r, APIRoute)
        for method in r.methods
        if r.path.startswith('/admin/')
    }
    assert atuais == esperadas
    assert all(
        r.dependant.dependencies
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith('/admin/')
    )

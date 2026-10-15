import logging
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


logger = logging.getLogger(__name__)
 
def _extract_hostname(raw_host: str) -> str:
    """'API.Exemplo.AO:443' -> 'api.exemplo.ao' | '[::1]:8000' -> '[::1]'"""
    raw_host = raw_host.strip().lower()
    if raw_host.startswith('['):
        return raw_host.split(']')[0] + ']'
    return raw_host.split(':')[0]
 
 
class AllowedHostMiddleware:
    """
    Aceita SOMENTE hosts da lista (allowlist). Qualquer outro, incluindo o
    *.onrender.com, recebe 403. É mais robusto que bloquear "onrender.com"
    por substring, porque não depende de adivinhar todos os domínios ruins.
    """
 
    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: list[str],
        exempt_paths: tuple[str, ...] = ('/health',),
    ) -> None:
        self.app = app
        self.allowed = {h.strip().lower() for h in allowed_hosts}
        self.exempt_paths = exempt_paths
 
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return
 
        # Healthcheck da plataforma precisa responder em qualquer host
        if scope['type'] == 'http' and scope.get('path') in self.exempt_paths:
            await self.app(scope, receive, send)
            return
 
        headers = dict(scope.get('headers', []))
        host = _extract_hostname(headers.get(b'host', b'').decode('latin-1'))
 
        if host in self.allowed:
            await self.app(scope, receive, send)
            return
 
        # Não loga o host cru (controlado pelo atacante): usa repr para
        # neutralizar quebras de linha (log injection).
        logger.warning(
            'Host não permitido bloqueado. Rota: %s | Host: %r',
            scope.get('path'),
            host[:100],
        )
 
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
 
        response = JSONResponse(
            status_code=403,
            content={'detail': 'Acesso não permitido por este domínio.'},
        )
        await response(scope, receive, send)
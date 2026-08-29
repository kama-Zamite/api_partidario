import logging
import re
from http import HTTPStatus

from fastapi.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("project_part.security.hosts")


class PureASGITrustedHostMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        # Compila os padrões de domínios permitidos (suporta curingas como *.meu-site.com)
        self.allowed_hosts = allowed_hosts
        self.host_patterns = [self._compile_pattern(host) for host in allowed_hosts]

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        """Converte padrões como *.meu-site.com em expressões regulares."""
        if pattern == "*":
            return re.compile(r"^.*$")

        # Escapa caracteres especiais do regex, exceto o curinga '*'
        escaped = re.escape(pattern).replace(r"\*", ".*")
        return re.compile(f"^{escaped}$", re.IGNORECASE)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Captura o cabeçalho 'Host' enviado pelo cliente/proxy
        headers = dict(scope.get("headers", []))
        host_bytes = headers.get(b"host", b"")

        # Se não houver cabeçalho host, decodifica como string vazia
        host = host_bytes.decode("latin-1").split(":")[0] if host_bytes else ""

        # Valida se o Host atual bate com pelo menos um dos padrões permitidos
        is_valid = any(pattern.match(host) for pattern in self.host_patterns)

        if not is_valid:
            logger.error(
                "ATAQUE DE HOST DETECTADO - Host Rejeitado: '%s' | Permitidos: %s",
                host,
                self.allowed_hosts
            )
            # Retorna um erro limpo 400 Bad Request direto em nível ASGI
            response = PlainTextResponse("Invalid host header", status_code=HTTPStatus.BAD_REQUEST)
            await response(scope, receive, send)
            return

        # Se for válido, segue para o próximo middleware da esteira
        await self.app(scope, receive, send)

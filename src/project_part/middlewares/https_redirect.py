import logging
import re

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Expressão regular simples para detectar se o host é um IP (ex: 12.34.56.78 ou localhost)
IP_PATTERN = re.compile(r'^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|localhost)(:\d+)?$')


class ProductionSecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get('headers', []))

        # 1. Corrige o esquema para HTTPS se o proxy reverso avisar que veio de lá
        if b'x-forwarded-proto' in headers and headers[b'x-forwarded-proto'] == b'https':
            scope['scheme'] = 'https'

        # Captura o host para validar se é IP ou domínio
        host_bytes = headers.get(b'host', b'')
        host_str = host_bytes.decode('utf-8', errors='ignore')

        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                response_headers = list(message.get('headers', []))

                # 2. Injeta o HSTS APENAS se NÃO for um endereço IP
                if not IP_PATTERN.match(host_str):
                    hsts_value = b'max-age=31536000; includeSubDomains; preload'
                    response_headers.append((b'strict-transport-security', hsts_value))

                # 3. Proteções extras de segurança (XSS e Sniffing) - Sempre ativas
                response_headers.append((b'x-content-type-options', b'nosniff'))
                response_headers.append((b'x-frame-options', b'DENY'))

                message['headers'] = response_headers

            await send(message)

        await self.app(scope, receive, send_wrapper)

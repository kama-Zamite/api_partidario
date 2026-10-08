# import ipaddress
# import logging
# import os
# import re

# from starlette.types import ASGIApp, Receive, Scope, Send

# logger = logging.getLogger(__name__)

# # Hosts que são IP ou localhost (IPv4 e IPv6, com ou sem porta)
# IP_PATTERN = re.compile(
#     r'^(\d{1,3}(\.\d{1,3}){3}|localhost|\[[0-9a-fA-F:]+\])(:\d+)?$'
# )

# DEFAULT_TRUSTED_PROXIES = '127.0.0.1,::1'

# SECURITY_HEADERS = {
#     b'x-content-type-options': b'nosniff',
#     b'x-frame-options': b'DENY',
#     b'referrer-policy': b'strict-origin-when-cross-origin',
#     b'permissions-policy': (
#         b'camera=(), microphone=(), geolocation=(), payment=(), usb=()'
#     ),
# }

# HSTS_VALUE = b'max-age=31536000; includeSubDomains; preload'


# def _parse_trusted(value: str):
#     networks = []
#     for item in value.split(','):
#         item = item.strip()
#         if item:
#             networks.append(ipaddress.ip_network(item, strict=False))
#     return networks


# class ProductionSecurityMiddleware:
#     def __init__(self, app: ASGIApp, trusted_proxies: str | None = None) -> None:
#         self.app = app
#         self.trusted = _parse_trusted(
#             trusted_proxies
#             or os.getenv('TRUSTED_PROXIES', DEFAULT_TRUSTED_PROXIES)
#         )

#     def _is_trusted(self, scope: Scope) -> bool:
#         client = scope.get('client')
#         if not client:
#             return False
#         try:
#             ip = ipaddress.ip_address(client[0])
#         except ValueError:
#             return False
#         return any(ip in net for net in self.trusted)

#     async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
#         if scope['type'] != 'http':
#             await self.app(scope, receive, send)
#             return

#         headers = dict(scope.get('headers', []))

#         # 1. Só aceita X-Forwarded-Proto se a ligação TCP vier de um proxy confiável
#         forwarded = headers.get(b'x-forwarded-proto')
#         if forwarded is not None:
#             if self._is_trusted(scope):
#                 if forwarded.split(b',')[0].strip().lower() == b'https':
#                     scope['scheme'] = 'https'
#             elif scope.get('scheme') != 'https':
#                 # Só avisa se o esquema ainda não for https (evita ruído quando
#                 # o uvicorn com --proxy-headers já corrigiu o esquema)
#                 logger.warning(
#                     'X-Forwarded-Proto ignorado: origem não confiável (%s)',
#                     scope.get('client'),
#                 )

#         host_str = headers.get(b'host', b'').decode('utf-8', errors='ignore')
#         is_https = scope.get('scheme') == 'https'
#         send_hsts = is_https and not IP_PATTERN.match(host_str)

#         async def send_wrapper(message):
#             if message['type'] == 'http.response.start':
#                 to_set = dict(SECURITY_HEADERS)
#                 if send_hsts:
#                     to_set[b'strict-transport-security'] = HSTS_VALUE

#                 # Remove duplicados que a app já tenha definido e aplica os nossos
#                 response_headers = [
#                     (k, v) for k, v in message.get('headers', [])
#                     if k.lower() not in to_set
#                 ]
#                 response_headers.extend(to_set.items())
#                 message['headers'] = response_headers

#             await send(message)

#         await self.app(scope, receive, send_wrapper)















# Funcional, mas tem bugs

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

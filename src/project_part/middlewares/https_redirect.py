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

import re
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HSTS_VALUE = 'max-age=31536000; includeSubDomains'  # sem preload até estares seguro
IP_HOST = re.compile(r'^(\d{1,3}(\.\d{1,3}){3}|\[[0-9a-fA-F:]+\]|localhost)(:\d+)?$')


class ProductionSecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        # scope['scheme'] já vem validado pelo Uvicorn (--forwarded-allow-ips)
        is_https = scope.get('scheme') == 'https'
        host = dict(scope.get('headers', [])).get(b'host', b'').decode('latin-1')
        send_hsts = is_https and not IP_HOST.match(host)

        async def send_wrapper(message: Message) -> None:
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                if send_hsts:
                    headers.setdefault('strict-transport-security', HSTS_VALUE)
                headers.setdefault('x-content-type-options', 'nosniff')
                headers.setdefault('x-frame-options', 'DENY')
            await send(message)

        await self.app(scope, receive, send_wrapper)


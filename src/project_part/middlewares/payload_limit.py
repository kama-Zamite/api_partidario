import logging
from http import HTTPStatus

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("project_part.security.payload")


class ContentLengthLimitMiddleware:
    def __init__(self, app: ASGIApp, max_content_length: int = 10 * 1024 * 1024) -> None:
        self.app = app
        self.max_content_length = max_content_length  # Define o limite em bytes (Padrão: 10MB)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Validação rápida pelo cabeçalho 'Content-Length'
        headers = dict(scope.get("headers", []))
        content_length_bytes = headers.get(b"content-length")

        if content_length_bytes:
            try:
                content_length = int(content_length_bytes)
                if content_length > self.max_content_length:
                    logger.warning(
                        "PAYLOAD REJEITADO - Cabeçalho Content-Length excedeu o limite: %d bytes (Máx: %d)",
                        content_length, self.max_content_length
                    )
                    response = JSONResponse(
                        status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Payload muito grande. O limite máximo permitido foi excedido."}
                    )
                    await response(scope, receive, send)
                    return
            except ValueError:
                # Cabeçalho Content-Length inválido ou corrompido
                response = JSONResponse(
                    status_code=HTTPStatus.BAD_REQUEST,
                    content={"detail": "Cabeçalho Content-Length inválido."}
                )
                await response(scope, receive, send)
                return

        # 2. Defesa contra 'Chunked Transfer Encoding' (onde o cabeçalho Content-Length não é enviado)
        # O atacante envia o payload em pedaços infinitos para tentar enganar a API.
        body_length = 0

        async def receive_wrapper():
            nonlocal body_length
            message = await receive()

            if message["type"] == "http.request":
                body = message.get("body", b"")
                body_length += len(body)

                if body_length > self.max_content_length:
                    logger.warning(
                        "PAYLOAD REJEITADO - Chunked encoding excedeu o limite em execução: %d bytes (Máx: %d)",
                        body_length, self.max_content_length
                    )
                    # Dispara uma exceção para interromper imediatamente a leitura do fluxo de rede
                    raise RuntimeError("Payload tamanho limite excedido")

            return message

        try:
            # Continua a pipeline usando o wrapper que monitora os pedaços recebidos
            await self.app(scope, receive_wrapper, send)
        except RuntimeError as exc:
            if str(exc) == "Payload tamanho limite excedido":
                # Responde para o cliente que o tamanho estourou
                response = JSONResponse(
                    status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    content={"detail": "Payload muito grande. O limite máximo permitido foi excedido."}
                )
                await response(scope, receive, send)
            else:
                raise exc

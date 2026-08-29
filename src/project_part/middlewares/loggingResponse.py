import logging
import time

from starlette.types import ASGIApp, Receive, Scope, Send

# Configura o logger para este módulo
logger = logging.getLogger("project_part.api.access")


class LoggingRequestMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Só intercepta requisições HTTP (ignora lambdas de ciclo de vida ou websockets)
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Captura os dados básicos da requisição que está entrando
        method = scope.get("method", "")
        path = scope.get("path", "")
        start_time = time.perf_counter()

        async def send_wrapper(message):
            # Intercepta o momento exato em que a resposta começa a ser enviada pelo FastAPI
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                process_time = time.perf_counter() - start_time
                process_time_str = f"{process_time:.4f}s"

                # PAPEL 1: Injeta o tempo de processamento no cabeçalho HTTP da resposta
                headers = list(message.get("headers", []))
                headers.append((b"x-process-time", process_time_str.encode()))
                message["headers"] = headers


                # 🚀 EXTRAÇÃO DO UTILIZADOR PARA VERIFICAR O CONSENTIMENTO
                # O FastAPI popula o 'state' após passar pelas rotas/dependências
                user = scope.get("state", {}).get("user", None)
                partilha_autorizada = getattr(user, "partilha_dados", False) if user else False


                # 2. ANONIMIZAÇÃO DINÂMICA DO CAMINHO (Path)
                # Se o utilizador recusou a partilha, ocultamos IDs sensíveis que possam estar na URL
                path_seguro = path
                if not partilha_autorizada:
                    # Substitui UUIDs ou números de militante explícitos na URL para proteger a privacidade
                    # Exemplo: /privacy/meus_dados_unita_0c1a40d5... vira /privacy/meus_dados_unita_[OCULTO]
                    import re
                    path_seguro = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '[ID_OCULTO]', path)

                # Contexto de auditoria baseado na escolha do utilizador
                if partilha_autorizada and user:
                    contexto_user = f" | User: {user.email}"
                else:
                    contexto_user = " | User: [ANÓNIMO]"

                # Formata o log estruturado com as restrições aplicadas
                log_message = (
                    f"Método: {method} | Rota: {path_seguro} | "
                    f"Status: {status_code} | Tempo: {process_time_str}{contexto_user}"
                )

                # Nível de severidade dinâmico baseado no status HTTP
                if status_code >= 500:
                    logger.error("FALHA INTERNA - %s", log_message)
                elif status_code >= 400:
                    logger.warning("REQUISIÇÃO INVÁLIDA - %s", log_message)
                else:
                    logger.info("SUCESSO - %s", log_message)

            await send(message)

        # Continua a execução da pipeline do FastAPI
        await self.app(scope, receive, send_wrapper)

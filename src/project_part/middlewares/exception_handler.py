import logging
from http import HTTPStatus

from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class GlobalExceptionHandlerMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        try:
            # Tenta executar a requisição normalmente
            await self.app(scope, receive, send)
        except Exception as exc:
            # Passamos scope e receive ajustados para a função de tratamento
            await self.handle_exception(exc, scope, receive, send)

    # 1. Adicionado scope e receive nos argumentos do método
    async def handle_exception(self, exc: Exception, scope: Scope, receive: Receive, send: Send) -> None:
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        response_body = {'detail': 'Ocorreu um erro interno no servidor. Tente novamente mais tarde.'}

        # EXTRAÇÃO DO UTILIZADOR: O FastAPI/Starlette guarda o utilizador autenticado no 'state'
        user = scope.get("state", {}).get("user", None)

        # Validação do consentimento (Se não existir o campo ou for falso, considera anónimo)
        partilha_autorizada = getattr(user, "partilha_dados", False) if user else False

        if partilha_autorizada and user:
            # Hipótese True: Rastreamento completo autorizado
            user_contexto = f"[User ID: {user.id} | Email: {user.email}]"
        else:
            # Hipótese False: Anonimização total exigida
            user_contexto = "[Usuário ANÓNIMO devido às diretivas de privacidade]"

        # Captura os dados básicos da rota para contexto de erro técnico
        metodo = scope.get("method", "UNKNOWN")
        caminho = scope.get("path", "UNKNOWN")

        # Tratamento específico para erros do Banco de Dados (SQLAlchemy)
        if isinstance(exc, SQLAlchemyError):
            if isinstance(exc, IntegrityError):
                status_code = HTTPStatus.CONFLICT
                response_body = {'detail': 'Conflito de integridade: Registro já existe ou dados são inválidos.'}
                logger.warning('%s Violação de integridade em %s %s: %s', user_contexto, metodo, caminho, str(exc.orig))

            elif isinstance(exc, OperationalError):
                logger.critical(
                    '%s ERRO OPERACIONAL CRÍTICO: Banco de dados fora do ar ou inacessível em %s %s! Detalhes: %s', 
                    user_contexto, metodo, caminho, str(exc)
                )
            else:
                logger.error('%s Erro genérico do SQLAlchemy interceptado em %s %s: %s', user_contexto, metodo, caminho, str(exc))

        # Tratamento para erros inesperados do Python
        else:
             # Se a partilha for falsa, removemos o 'exc_info=True' para não printar o Stack Trace no log do Docker,
            # uma vez que o stack trace pode expor dados de variáveis internas da requisição do utilizador.
            if partilha_autorizada:
                logger.error('%s EXCEÇÃO NÃO TRATADA NA APLICAÇÃO em %s %s: %s', user_contexto, metodo, caminho, str(exc), exc_info=True)
            else:
                logger.error('%s EXCEÇÃO NÃO TRATADA NA APLICAÇÃO em %s %s: %s (Rastreamento completo ocultado por privacidade)', user_contexto, metodo, caminho, str(exc))

        # Constrói a resposta HTTP pura em nível ASGI para enviar ao cliente
        response = JSONResponse(status_code=status_code, content=response_body)

        # 2. CORREÇÃO: Alterado de (Scope, Receive, send) para as variáveis em minúsculo
        await response(scope, receive, send)

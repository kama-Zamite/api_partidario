import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from project_part.api.admin.admin_router import admin
from project_part.api.auth.auth_router import auth
from project_part.api.events.event_router import event
from project_part.api.noticias.noticias_router import news_router
from project_part.api.provincia.provincia_router import provincia
from project_part.api.notification_router.notification_router import router_notific
from project_part.api.finance.finance_router import finance
from project_part.api.Auth_2fa.router_2fa import router_2FA
from project_part.api.users.user_router import user
from project_part.api.privacy.privacy_router import privacy
from project_part.core.context import client_ip_ctx, user_agent_ctx
from project_part.core.health import health_router
from project_part.core.logging_config import setup_logging
from project_part.core.rate_limit import limiter
from project_part.core.setting import settings
from project_part.middlewares.exception_handler import (
    GlobalExceptionHandlerMiddleware,
)
from project_part.middlewares.https_redirect import (
    ProductionSecurityMiddleware,
)
from project_part.middlewares.loggingResponse import LoggingRequestMiddleware
from project_part.middlewares.payload_limit import ContentLengthLimitMiddleware

setup_logging()

logging.basicConfig(level=settings.LOG_LEVEL)
logging.getLogger('uvicorn.error').setLevel(settings.LOG_LEVEL)
logging.getLogger('uvicorn.access').setLevel(settings.LOG_LEVEL)

app = FastAPI(title='Uniao', description='uma api de povo para povo', version='1.0.0')


app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={
            'detail': 'Too many request',
        },
    ),
)

logger = logging.getLogger('uvicorn.error')
logger.info(
    'Aplicacao inicializada no modo [%s] com nivel de log [%s]',
    settings.ENV,
    settings.LOG_LEVEL,
)


# 5. Proteção contra Payload Gigante
app.add_middleware(ContentLengthLimitMiddleware, max_content_length=settings.MAX_CONTENT_LENGTH)

# 4. CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# 3. Utilidades de Rede, HTTPS e Segurança Geral
app.add_middleware(ProductionSecurityMiddleware)
app.add_middleware(LoggingRequestMiddleware)
app.add_middleware(GlobalExceptionHandlerMiddleware)


# 2. Configuração CORRETA do Rate Limit (SlowAPI)
app.add_middleware(SlowAPIMiddleware)

# 1. Configuração CORRETA do TrustedHost (Primeira barreira absoluta)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)


@app.middleware('http')
async def audit_context_middleware(request: Request, call_next):
    ip = request.headers.get('x-forwarded-for', request.client.host if request.client else None)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()

    client_ip_ctx.set(ip)
    user_agent_ctx.set(request.headers.get('user-agent'))
    return await call_next(request)


@app.get('/')
@limiter.limit('5/minute')
def home(request: Request):
    return {'msg': 'rota criada com sucesso!'}


app.include_router(auth)
app.include_router(router_2FA)
app.include_router(admin)

app.include_router(provincia)

app.include_router(user)

app.include_router(event)
app.include_router(news_router)

app.include_router(router_notific)
app.include_router(finance)

app.include_router(health_router)
app.include_router(privacy)

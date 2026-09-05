import json
import logging
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Annotated, List
from user_agents import parse
import uuid


from aiosmtplib import response
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Response,
    Request,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import TypeAdapter
import pyotp
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from project_part.core.secury import (
    Get_current_user,
    check_refresh_token,
    check_token_recuperar_senha,
    create_refresh_token,
    create_token,
    create_token_recuperar_senha,
    garante_escopo_territorial,
    hash_password,
    verify_password,
    gerar_e_registar_refresh_token,
)
from jwt import decode, PyJWTError
from project_part.core.setting import settings
from project_part.db import session
from project_part.db.cache import get_redis
from project_part.db.session import get_session
from project_part.model.models import (
    AdminScope,
    PasswordResetToken,
    Permissao,
    CadastrarComo,
    Role,
    User,
    UserRefreshToken,
    BackupCode,
)
from project_part.services.email_service.recuperar_senha import (
    enviar_email_real_async,
)
from project_part.services.email_service.loginEmail import email_sucesso_login_async
from project_part.api.auth.util import set_auth_cookies
from project_part.services.claudflare_turnfile import verificar_turnstile
from .schemas import (
    CreatePermissao,
    CreateRole,
    Limit,
    PedidoRecuperacao,
    ResponsePermissao,
    ResponseRole,
    Login2FARequest,
    UpgradePermissao,
    UpgradeRole,
    RedefinirSenhaSchema,
)
Claudflare_turnfile = Annotated[bool, Depends(verificar_turnstile)]
Session = Annotated[AsyncSession, Depends(get_session)]
Redis = Annotated[AsyncRedis, Depends(get_redis)]
Access_token = Annotated[OAuth2PasswordRequestForm, Depends()]
ScopeValid = Annotated[AdminScope, Depends(garante_escopo_territorial)]
Paginacao = Annotated[Limit, Depends()]
logger = logging.getLogger(__name__)


auth = APIRouter(prefix='/auth', tags=['Auth'])


TypeCacheBase = 'v4:permissao:listar'

router_auth = APIRouter(prefix="/auth", tags=["Autenticação"])

# Exemplo de rota de login protegida
# @router_auth.post("/login")
# async def login(
#     form_data: OAuth2PasswordRequestForm = Depends(),
#     db: Session = Depends(get_db),
#     _captcha: bool = Depends(verificar_turnstile)  # 🌟 PROTEÇÃO ATIVADA AQUI
# ):
#     """
#     O FastAPI só executa o bloco interno desta função se o token 
#     enviado no Header 'cf-turnstile-response' for 100% legítimo.
#     """
#     # Sua lógica de login/2FA já existente continua exatamente aqui...
#     return {"message": "Autenticado com sucesso e protegido contra bots!"}


@auth.post('/login', status_code=HTTPStatus.OK, summary='Autenticação de Usuário')
async def login(
    request: Request, 
    response: Response,
    session: Session,
    token: Access_token,
    backgroundTasks: BackgroundTasks,
    _captcha: Claudflare_turnfile
    ):
    """Endpoint para autenticação de usuário."""

    logger.info('Tentativa de login para o usuário: %s', token.username)

    try:
        # Isolamento estrito da primeira query
        user = await session.scalar(select(User).where(User.email == token.username))
    except Exception as query_err:
        await session.rollback()
        logger.error('Falha crítica ao consultar utilizador no banco: %s', str(query_err))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Erro interno de processamento na base de dados.'
        )

    if user and not user.ativo:
        logger.warning('Tentativa de login em conta desativada: %s', token.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='E-mail ou senha incorretos')

    if not user:
        logger.warning('Falha de login: usuario %s nao encontrado', token.username)
        # Executa a verificação dummy para mitigar ataques de temporização (Timing Attacks)
        verify_password(token.password, settings.DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='E-mail ou senha incorretos',
        )

    agora = datetime.now(timezone.utc)

    if user.bloqueado_permanente:
        logger.warning('Tentativa de login em conta bloqueada permanentemente: %s', token.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Conta bloqueada por segurança. Verifique seu e-mail para desbloquear.',
        )

    if user.bloqueado_ate and agora < user.bloqueado_ate:
        tempo_restante = int((user.bloqueado_ate - agora).total_seconds() / 60)
        logger.warning('Tentativa de login em conta temporariamente bloqueada: %s', token.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f'Muitas tentativas. Tente novamente em {tempo_restante} minutos.',
        )

    # --- Fluxo de Senha Incorreta ---
    if not verify_password(token.password, user.password_hash):
        # CORREÇÃO 1: Evita quebra por NoneType caso os valores na BD estejam como NULL
        tentativa_acertos = user.tentativa_acertos or 0
        tentativas_apos_bloqueio = user.tentativas_apos_bloqueio or 0

        if tentativa_acertos >= 5:
            user.tentativas_apos_bloqueio = tentativas_apos_bloqueio + 1
            logger.warning('Erro após desbloqueio temporário. Erro número: %d/2', user.tentativas_apos_bloqueio)

            if user.tentativas_apos_bloqueio >= 2:
                user.bloqueado_permanente = True
                logger.error('Usuário %s atingiu o limite máximo e foi bloqueado PERMANENTEMENTE.', token.username)
        else:
            user.tentativa_acertos = tentativa_acertos + 1
            if user.tentativa_acertos == 5:
                user.bloqueado_ate = agora + timedelta(minutes=15)
                logger.warning('Usuário %s atingiu 5 erros. Bloqueado por 15 minutos.', token.username)

        try:
            session.add(user)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error('Não foi possível atualizar as tentativas de acerto no DB: %s', str(e))

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='E-mail ou senha incorretos')


    ip_address = (
        request.headers.get("x-forwarded-for")
        or (
            request.client.host
            if request.client
            else None
        )
    )

    if not ip_address:
        ip_address = request.client.host if request.client else None

    # 3. Capturar o User-Agent (Navegador/Dispositivo)
    user_agent = request.headers.get("user-agent")
    
    # --- Fluxo de Autenticação com Sucesso ---
    logger.info('Tentando atualizar o ultimo login do usuario')
    user.ultimo_login = agora
    user.tentativas_apos_bloqueio = 0
    user.tentativa_acertos = 0
    user.bloqueado_ate = None


    if user.two_factor_enabled:
        logger.info('Usuário %s requer verificação de 2FA.', token.username)
        # Aqui você pode implementar a lógica para enviar o código 2FA ou redirecionar para o endpoint de verificação.
        try:
            session.add(user)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error('Falha ao salvar estado pré-2FA: %s', str(e))
        

        return  {
            "require_2fa": True,
            "user_id": str(user.id),
            "message": "Autenticação de dois fatores necessária. Verifique seu dispositivo.",
        }
    
    logger.info('Usuário %s autenticado com sucesso (Sem 2FA)', token.username)
    token_gerado = create_token({'sub': str(user.id)})


    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,      # <-- Faltava este argumento!
        user_id=user.id, 
        ip=ip_address, 
        user_agent=user_agent
    )

    try:
        session.add(user)
        await session.commit()
        # CORREÇÃO 2: Removido o 'await session.refresh(user)' que causava colisão de transação
        # com middlewares assíncronos de resposta após o commit já ter sido efetivado.
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))

    
    #enviar email

    user_agent_parsed = parse(user_agent)
    try:
        backgroundTasks.add_task(
            email_sucesso_login_async, 
            nome_completo=user.nome_completo, 
            ip_address=ip_address, 
            email_destino=user.email,
            navegador=user_agent_parsed.browser.family, 
            sistema_operacional=user_agent_parsed.os.family, 
            )
        logger.info("E-mail de login enviado com sucesso para %s", user.email)
    except Exception as e:
        logger.error("Falha ao enviar e-mail de login para %s: %s", user.email, str(e))


    set_auth_cookies(
        response=response,
        access_token=token_gerado,
        refresh_token=refresh_gerado,
    )
    response.headers["Cache-Control"] = "no-store"

    return {
        "require_2fa": False,
        "status": "success",
        "message": "Autenticação realizada com sucesso.",
    }





@auth.post('/login/2fa-verify', status_code=HTTPStatus.OK, summary='Verificação de 2FA')
async def verify_2fa(
    response: Response,
    request: Request,
    body: Login2FARequest,
    session: Session,
    backgroundTasks: BackgroundTasks,
):
    """
    Endpoint para verificação de autenticação de dois fatores (2FA).
    Este endpoint recebe o código 2FA do usuário, verifica a autenticidade e retorna um token de acesso e um refresh token.
    Args:
        response (Response): Objeto de resposta para configurar os cookies.
        session (Session): Sessão assíncrona do banco de dados (SQLAlchemy).
        body (Login2FARequest): Corpo da requisição contendo o código 2FA e o ID do usuário.
    Raises:
        HTTPException [401 UNAUTHORIZED]: Se o código 2FA estiver incorreto ou expirado.

    # async def login(response: Response, session: Session, token: Access_token):
   """

    logger.info('Tentativa de verificação 2FA para o usuário: %s', body.user_id)
    query = select(User).where(User.id == body.user_id)
    user = await session.scalar(query)

    if not user or not user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requisição de login inválida ou expirada."
        )

    codigo_limpo = body.codigo.strip()
    if len(codigo_limpo) == 6:
        totp = pyotp.TOTP(user.two_factor_secret)
        logger.info('Verificando código 2FA para o usuário: %s', body.user_id)
        #valid_window=1 permite aceitar códigos válidos dentro de uma janela de tempo de 30 segundos antes ou depois do código atual.
        if not totp.verify(codigo_limpo, valid_window=1):
            logger.warning('Código 2FA inválido para o usuário: %s', body.user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código 2FA inválido ou expirado."
            )
    elif len(codigo_limpo) == 8:
        # Aqui esta a lógica para verificar o código de backup de 8 dígitos.
        backup_result = await session.scalars(
            select(BackupCode).where(
                BackupCode.user_id == user.id,
                BackupCode.used == False
            )
        )
        codigos_disponiveis = backup_result.all()
        
        codigo_encontrado = None
        for codigo in codigos_disponiveis:
            if verify_password(codigo_limpo, codigo.code_hash):
                codigo_encontrado = codigo
                break
        if not codigo_encontrado:
            logger.warning('Código de backup inválido para o usuário: %s', body.user_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código de resgate inválido ou já utilizado."
            )

        try:
            codigo_encontrado.used = True
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error('Não foi possível marcar o código de resgate como usado: %s', str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro ao processar validação de segurança."
            )

    else:
        logger.warning('Código 2FA ou de backup com tamanho inválido para o usuário: %s', body.user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O código deve conter 6 dígitos (aplicativo) ou 8 dígitos (resgate)."
        )

        logger.info('Usuário %s autenticado com sucesso', token.username)
    token_gerado = create_token({'sub': str(user.id)})

    ip_address = (
        request.headers.get("x-forwarded-for")
        or (
            request.client.host
            if request.client
            else None
        )
    )

    if not ip_address:
        ip_address = request.client.host if request.client else None

    # 3. Capturar o User-Agent (Navegador/Dispositivo)
    user_agent = request.headers.get("user-agent")
    
    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,      # <-- Faltava este argumento!
        user_id=user.id, 
        ip=ip_address, 
        user_agent=user_agent
    )

    try:
        session.add(user)
        await session.commit()
        # CORREÇÃO 2: Removido o 'await session.refresh(user)' que causava colisão de transação
        # com middlewares assíncronos de resposta após o commit já ter sido efetivado.
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))

    user_agent_parsed = parse(user_agent)
    try:
        backgroundTasks.add_task(
            email_sucesso_login_async, 
            nome_completo=user.nome_completo, 
            ip_address=ip_address, 
            email_destino=user.email,
            navegador=user_agent_parsed.browser.family, 
            sistema_operacional=user_agent_parsed.os.family, 
            )
        logger.info("E-mail de login enviado com sucesso para %s", user.email)
    except Exception as e:
        logger.error("Falha ao enviar e-mail de login para %s: %s", user.email, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Falha ao enviar e-mail de login. Tente novamente mais tarde."
        )
    
    set_auth_cookies(
        response=response,
        access_token=token_gerado,
        refresh_token=refresh_gerado,
    )
    response.headers["Cache-Control"] = "no-store"

    return {
        "status": "success",
        "message": "Autenticação realizada com sucesso.",
    }





#     Este endpoint recebe as credenciais do usuário, verifica a autenticidade e retorna um token de acesso e um refresh token.
#     Args:
#         response (Response): Objeto de resposta para configurar os cookies.
#         session (Session): Sessão assíncrona do banco de dados (SQLAlchemy).
#         token (OAuth2PasswordRequestForm): Formulário contendo as credenciais do usuário (username e password).
#         Raises:
#             HTTPException [401 UNAUTHORIZED]: Se o e-mail ou a senha estiverem incorretos.
#             HTTPException [401 UNAUTHORIZED]: Se a conta do usuário estiver desativada (ativo=False).
#             HTTPException [401 UNAUTHORIZED]: Se a conta estiver bloqueada permanentemente.
#             HTTPException [401 UNAUTHORIZED]: Se a conta estiver bloqueada temporariamente (limite de erros atingido).
#         Returns:
#             TokenResponse: Um dicionário contendo o token de acesso, o token de atualização
#             e o tipo de token (Bearer).
#     """

#     logger.info('Tentativa de login para o usuário: %s', token.username)
#     user = await session.scalar(select(User).where(User.email == token.username))

#     if user and not user.ativo:
#         logger.warning('Tentativa de login em conta desativada: %s', token.username)
#         raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail='E-mail ou senha incorretos')

#     if not user:
#         logger.warning('Falha de login: usuario %s nao encontrado', token.username)
#         verify_password(token.password, settings.DUMMY_HASH)
#         raise HTTPException(
#             status_code=HTTPStatus.UNAUTHORIZED,
#             detail='E-mail ou senha incorretos',
#         )


#     agora = datetime.now(timezone.utc)

#     if user.bloqueado_permanente:
#         logger.warning('Tentativa de login em conta bloqueada permanentemente: %s', token.username)
#         raise HTTPException(
#             status_code=HTTPStatus.UNAUTHORIZED,
#             detail='Conta bloqueada por segurança. Verifique seu e-mail para desbloquear.'
#         )

#     if user.bloqueado_ate and agora < user.bloqueado_ate:
#         tempo_restante = int((user.bloqueado_ate - agora).total_seconds() / 60)
#         logger.warning('Tentativa de login em conta temporariamente bloqueada: %s', token.username)
#         raise HTTPException(
#             status_code=HTTPStatus.UNAUTHORIZED,
#             detail=f'Muitas tentativas. Tente novamente em {tempo_restante} minutos.'
#         )

#     if not verify_password(token.password, user.password_hash):

#         if user.tentativa_acertos >= 5:
#             user.tentativas_apos_bloqueio += 1
#             logger.warning('Erro após desbloqueio temporário. Erro número: %d/2', user.tentativas_apos_bloqueio)

#             if user.tentativas_apos_bloqueio >= 2:
#                 user.bloqueado_permanente = True
#                 logger.error('Usuário %s atingiu o limite máximo e foi bloqueado PERMANENTEMENTE.', token.username)

#                 #criacao da logica de envio de email aqui, responsabilidade do leonel
#         else:
#             user.tentativa_acertos += 1
#             if user.tentativa_acertos == 5:
#                 user.bloqueado_ate = agora + timedelta(minutes=15)
#                 logger.warning('Usuário %s atingiu 5 erros. Bloqueado por 15 minutos.', token.username)

#         try:
#             session.add(user)
#             await session.commit()
#         except Exception as e:
#             await session.rollback()
#             logger.error('Não foi possível atualizar as tentativas de acerto no DB: %s', str(e))
#         raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail='E-mail ou senha incorretos')

#     logger.info('Tentando a tualizar o ultimo login do usuario')
#     user.ultimo_login = agora
#     user.tentativas_apos_bloqueio = 0
#     user.tentativa_acertos = 0
#     user.bloqueado_ate = None

#     try:
#         session.add(user)
#         await session.commit()
#         await session.refresh(user)
#         logger.info('sucesso na atualizacao do ultimo_login do usuario')
#     except Exception as e:
#         await session.rollback()
#         logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))

#     logger.info('Usuário %s autenticado com sucesso', token.username)
#     token_gerado = create_token({'sub': str(user.id)})
#     refresh_gerado = create_refresh_token({'sub': str(user.id)})

#     response.set_cookie(
#         key='access_token',
#         value=token_gerado,
#         httponly=True,
#         secure=True,
#         samesite='none',
#         max_age=60 * 15,
#         path='/',
#     )
#     response.set_cookie(
#         key="refresh_token",
#         value=refresh_gerado,
#         httponly=True,
#         secure=True,
#         samesite="none",
#         max_age=60 * 60 * 24 * 7,
#         path="/auth/refresh",
#     )
#     return {
#         'access_token': token_gerado,
#         'token_type': 'bearer'
#     }



async def get_token_recuperar_senha_from_cookie(
    token_recuperar_senha: Annotated[
        str | None, Cookie(alias="token_recuperar_senha")
    ] = None,
) -> str | None:
    return token_recuperar_senha


@auth.post('/recuperar-senha', status_code=HTTPStatus.OK)
async def solicitar_recuperacao(
    payload: PedidoRecuperacao,
    session: Session,
    background_tasks: BackgroundTasks,
    _captcha: bool = Depends(verificar_turnstile),
    ):
    """Endpoint para solicitar a recuperação de senha. Recebe o e-mail do usuário, verifica se ele existe no banco de dados e, se existir, gera um token de recuperação e envia um e-mail com instruções para redefinir a senha.
    Args:
        payload (PedidoRecuperacao): Objeto contendo o e-mail do usuário.
        session (Session): Sessão assíncrona do banco de dados (SQLAlchemy).
        background_tasks (BackgroundTasks): Objeto para adicionar tarefas em segundo plano.
        _captcha (bool): Dependência para verificar o CAPTCHA do Cloudflare Turnstile.
    Raises:
        HTTPException [400 BAD REQUEST]: Se o e-mail não for fornecido ou estiver em formato inválido.
    Returns:
        dict: Mensagem informando que, se o e-mail existir no sistema, o usuário receberá um link de redefinição.
    """
    mensagem_padrao = {
        "status": "success",
        "message": "Se o e-mail estiver cadastrado, você receberá um link para redefinir a senha.",
    }

    logger.info("Procurar o e-mail ou numero '%s' de militante na Base de Dados", payload.email)
    query = select(User).where(User.email == payload.email)
    usuario_banco = await session.scalar(query)

    # aqui nao irei fazer a checagem se o email nao existe porque e intencional
    # fingimos que correu bem, se existir, geramos o token e enviamos em segundo plano
    if usuario_banco:
        token = await create_token_recuperar_senha(
            usuario_banco.id,
            payload.email, 
            session
            )
        # background_tasks.add_task(enviar_email_falso, payload.email, token)
        background_tasks.add_task(
            enviar_email_real_async,
            payload.email,
            token,
            usuario_banco.nome_completo
            )
    else:
        logger.info('Tentativa de recuperação para e-mail inexistente: %s', payload.email)

    return mensagem_padrao


@auth.post('/redefinir-senha', status_code=HTTPStatus.OK)
async def redefinir_senha(
    payload: RedefinirSenhaSchema,
    session: Session):
    """Endpoint para redefinir a senha do usuário. Recebe o token de recuperação e a nova senha, verifica a validade do token e atualiza a senha no banco de dados.
    Args:
        payload (RedefinirSenhaSchema): Objeto contendo o token de recuperação e a nova senha.
        session (Session): Sessão assíncrona do banco de dados (SQLAlchemy).
    Raises:
        HTTPException [404 NOT FOUND]: Se o usuário não for encontrado no banco de dados.
        HTTPException [400 BAD REQUEST]: Se houver erro de integridade ao salvar os dados.
    Returns:
        dict: Mensagem informando que a senha foi atualizada com sucesso.
    """

    email, token_id = await check_token_recuperar_senha(
        payload.token,
        session
        )
    try:
        logger.info('Busca o token com condição de ainda não ter sido usado')
        query_token = select(PasswordResetToken).where(
            PasswordResetToken.id == token_id,
            PasswordResetToken.usado.is_(False),
        )
        token_banco = await session.scalar(query_token)

        if not token_banco:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Este link de recuperação já foi utilizado ou é inválido.",
            )
        logger.info('Token de recuperação encontrado e válido: %s', token_id)
        query = select(User).where(
            User.email == email).options(selectinload(User.provincia), selectinload(User.municipio))

        user_banco = await session.scalar(query)

        if not user_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Usuário associado ao token não encontrado.')

        token_banco.usado = True
        pwd_hash = hash_password(payload.password)
        user_banco.password_hash = pwd_hash
        data_atualizacao = datetime.now(timezone.utc)
        user_banco.atualizado_em = data_atualizacao


        await session.commit()
        logger.info('Senha atualizada com sucesso para o usuário: %s', email)
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(
            "Erro crítico ao redefinir senha (token_id=%s): %s",
            token_id,
            str(e),
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar a redefinição de senha.",
        )
    return {
        "status": "success",
        "message": "Senha redefinida com sucesso!",
    }

@auth.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def refresh_token(
    request: Request,
    response: Response,
    session: Session,
    token_data: dict = Depends(check_refresh_token),
):

    user_id = token_data["user_id"]
    token_jti = token_data["jti"]

    agora = datetime.now(timezone.utc)

    try:

        # =====================================================
        # 1. LOCK DA LINHA
        # =====================================================

        result = await session.execute(
            select(UserRefreshToken)
            .where(
                UserRefreshToken.token_jti == token_jti
            )
            .with_for_update()
        )

        db_token = result.scalar_one_or_none()

        if not db_token:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 2. Verificar estado
        # =====================================================

        if db_token.revogado:

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 3. Detectar REUTILIZAÇÃO
        # =====================================================

        if db_token.utilizado:

            logger.warning(
                "Reutilização de refresh token detectada. "
                "user_id=%s",
                user_id,
            )

            # Revoga todas as sessões do usuário.
            await session.execute(
                update(UserRefreshToken)
                .where(
                    UserRefreshToken.user_id == user_id
                )
                .values(
                    revogado=True,
                    revogado_em=agora,
                )
            )

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 4. Verificar expiração
        # =====================================================

        if db_token.expira_em <= agora:

            db_token.revogado = True
            db_token.revogado_em = agora

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão expirada.",
            )

        # =====================================================
        # 5. Buscar usuário
        # =====================================================

        user = await session.scalar(
            select(User)
            .where(User.id == user_id)
        )

        if not user or not user.ativo:

            db_token.revogado = True
            db_token.revogado_em = agora

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 6. Consumir token antigo
        # =====================================================

        db_token.utilizado = True
        db_token.utilizado_em = agora

        # =====================================================
        # 7. Informações da nova sessão
        # =====================================================

        ip_address = (
            request.headers.get("x-forwarded-for")
            or (
                request.client.host
                if request.client
                else None
            )
        )

        user_agent = request.headers.get(
            "user-agent"
        )

        # =====================================================
        # 8. Criar NOVO refresh token
        # =====================================================

        novo_refresh_token = (
            await gerar_e_registar_refresh_token(
                session=session,
                user_id=user.id,
                ip=ip_address,
                user_agent=user_agent,
            )
        )

        # =====================================================
        # 9. Criar novo access token
        # =====================================================

        novo_access_token = create_token(
            {
                "sub": str(user.id),
                "type": "access",
            }
        )

        # =====================================================
        # 10. COMMIT ATÔMICO
        # =====================================================

        await session.commit()

        # =====================================================
        # 11. Atualizar cookies
        # =====================================================

        set_auth_cookies(
            response=response,
            access_token=novo_access_token,
            refresh_token=novo_refresh_token,
        )

        response.status_code = status.HTTP_200_OK
        response.headers["Cache-Control"] = "no-store"

        # Agora o retorno é 100% legítimo e o FastAPI aceitará o JSON perfeitamente
        return {
            "status": "success",
            "message": "Tokens de autenticação renovados com sucesso."
        }
    except HTTPException:

        raise

    except Exception:

        await session.rollback()

        logger.exception(
            "Erro interno durante refresh token."
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno de autenticação.",
        )



# @auth.get("/debug/cookies")
# async def debug_cookies(request: Request):
#     return {
#         "access_token": bool(
#             request.cookies.get("access_token")
#         ),
#         "refresh_token": bool(
#             request.cookies.get("refresh_token")
#         ),
#     }


@auth.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(
    request: Request,
    response: Response,
    session: Session,
):

    refresh_token = request.cookies.get(
        # "__Host-refresh_token"
        "refresh_token"
    )

    try:

        if refresh_token:

            try:

                payload = decode(
                    refresh_token,
                    settings.SECRET_KEY,
                    algorithms=[settings.ALGORITHM],
                )

                token_jti = payload.get("jti")

            except PyJWTError:

                token_jti = None

            if token_jti:

                agora = datetime.now(timezone.utc)

                result = await session.execute(
                    select(UserRefreshToken)
                    .where(
                        UserRefreshToken.token_jti == token_jti,
                        UserRefreshToken.revogado.is_(False),
                    )
                    .with_for_update()
                )

                db_token = (
                    result.scalar_one_or_none()
                )

                if db_token:

                    db_token.revogado = True
                    db_token.revogado_em = agora

                    await session.commit()

        # =====================================================
        # Apagar cookies
        # =====================================================

        response.delete_cookie(
            # key="__Host-access_token",
            key="access_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )

        response.delete_cookie(
            # key="__Host-refresh_token",
            key="refresh_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )

        response.headers["Cache-Control"] = "no-store"

        return 

    except Exception:

        await session.rollback()

        logger.exception(
            "Erro durante logout."
        )

        # Mesmo em caso de erro interno,
        # remove as credenciais do navegador.

        response.delete_cookie(
            # key="__Host-access_token",
            key="access_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )

        response.delete_cookie(
            # key="__Host-refresh_token",
            key="refresh_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        return {"detail": "Erro interno ao encerrar sessão."}




@auth.post('/permissoes/create', status_code=HTTPStatus.CREATED)
async def criar_permissao(
    schema: CreatePermissao, session: Session, redis: Redis, 
    # current_user: Get_current_user, scope: ScopeValid
):
    # if not current_user.scope:
    #     raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail='Usuario sem autorizacao')

    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para criar permissao.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para criar permissao.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # logger.info('Procurar usuario: %s no banco de dados...', current_user.nome_completo)
    nova_permissao = Permissao(nome=schema.nome)

    try:
        session.add(nova_permissao)
        await session.commit()
        await session.refresh(nova_permissao)
        await redis.delete('v1:permissao:listar')
        logger.info('Caches do "v1:permissao:listar" deletados com sucesso!')
        logger.info('permissao: %s foi criadas com sucesso', schema.nome)
        return {'msg': f'permissao {schema.nome} criada com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar permissao %s: %s',
            schema.nome,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: A permissao "{schema.nome}" ja se encontra cadastrada.',
        )


@auth.get(
    '/permissoes/list',
    status_code=HTTPStatus.OK,
    response_model=List[ResponsePermissao],
)
async def listar_permissoes(
    response: Response, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):

    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para criar permissao.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para criar permissao.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    try:
        permissao_save = await redis.get(TypeCacheBase)
        if permissao_save:
            response.headers['X-Caches-lock'] = 'Dados vindo do redis'
            logger.info('informacoes estao vindo do redis')
            return json.loads(permissao_save)
    except Exception as e:
        logger.error('Error: na solicitacao dos dados do redis %s', e)

    logger.info('Buscando dados no postgresSQL...')
    query = select(Permissao)
    permissao = await session.scalars(query)

    permissaoAll = permissao.all()
    if not permissaoAll:
        logger.warning('Nenhuma permissao foi encontrada')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhuma permissao foi encontrada',
        )

    try:
        adaptador = TypeAdapter(List[ResponsePermissao])
        list_json = adaptador.dump_json(permissaoAll).decode('utf-8')
        await redis.set(TypeCacheBase, list_json, ex=60)
        logger.info('Caches guardados com sucesso por 60 segundos!')
    except Exception as e:
        logger.error('Nao foi possivel guardar os caches no redis: %s', e)

    response.headers['X-Caches-lock'] = 'Dados vindo do postgresSQL...'
    return permissaoAll


@auth.post('/role/create', status_code=HTTPStatus.CREATED)
async def criar_role(
    schemas: CreateRole, session: Session, redis: Redis, 
    # current_user: Get_current_user, scope: ScopeValid
):

    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para criar Role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para criar role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    logger.info('Buscando todas as permissoes disponiveis no banco...')
    permissao = await session.scalars(select(Permissao).where(Permissao.nome.in_(schemas.permissoes_nome)))

    permissaoAll = permissao.all()
    if not permissaoAll:
        logger.warning('Nenhuma permissao foi encontrada')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhuma permissao foi encontrada',
        )

    logger.info('criar role %s', schemas.nome)
    novo_role = Role(nome=schemas.nome, permissoes=permissaoAll)

    try:
        session.add(novo_role)
        await session.commit()
        await session.refresh(novo_role)
        await redis.delete('v3:role:list')
        logger.info('Caches do v3:role:list deletados com sucesso!')
        logger.info('Role: %s, criado com sucesso!', schemas.nome)
        return {'msg': f'Role {schemas.nome}, criado com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar role %s: %s',
            schemas.nome,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: role {schemas.nome} ja cadastrado',
        )


@auth.get('/role/list', status_code=HTTPStatus.OK, response_model=List[ResponseRole])
async def listar_role(
    response: Response, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):

    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para listar Role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para listar role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    try:
        roles_save = await redis.get('v3:role:list')
        if roles_save:
            response.headers['X-Caches-lock'] = 'roles vindo do redis'
            logger.info('informacoes do roles esta vindo do redis')
            return json.loads(roles_save)

    except Exception as e:
        logger.error('Error: na solicitacao dos dados do redis %s', e)

    logger.info('Buscando dados no postgresSQL...')
    role = await session.scalars(select(Role).options(selectinload(Role.permissoes)))

    roleAll = role.all()
    if not roleAll:
        logger.warning('Nenhum role encontrado')
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Nenhum role encontrado')

    try:
        adaptador = TypeAdapter(List[ResponseRole])
        list_json = adaptador.dump_json(roleAll).decode('utf-8')
        await redis.set('v3:role:list', list_json, ex=60)
        logger.info('Caches gardados com sucesso por 60 segundos!')
    except Exception as e:
        logger.error('Nao foi possivel guardar os caches no redis: %s', e)

    response.headers['X-Caches-lock'] = 'Dados vindo do postgresSQL'
    return roleAll


@auth.put('/permissoes/upgrade/{id_permissao}', status_code=HTTPStatus.OK)
async def atualizar_permissao(
    id_permissao: int,
    schemas: UpgradePermissao,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para atualizar Permissoes.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para atualizar permissoes.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    logger.info('Buscando pela permissao %d...', id_permissao)
    permissao = await session.scalar(select(Permissao).where(Permissao.id == id_permissao))

    if not permissao:
        logger.warning('permissao %d nao foi encontrado(a)', id_permissao)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'permissao {schemas.nome} nao foi encontrado(a)',
        )

    logger.info('permissao %d foi encontrado', id_permissao)
    permissao.nome = schemas.nome
    try:
        session.add(permissao)
        await session.commit()
        await session.refresh(permissao)
        logger.info('Permissao %s atualizada com sucesso', schemas.nome)
        await redis.delete('v1:permissao:listar')
        logger.info('Caches do "v1:permissao:listar" foram eliminados')
        return {'msg': f'Permissao {schemas.nome} atualizada com sucesso'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar permissao %s: %s',
            schemas.nome,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: A permissao "{schemas.nome}" ja se encontra cadastrada.',
        )


@auth.delete('/permissoes/delete/{id_permissao}', status_code=HTTPStatus.OK)
async def eliminar_permissao(
    id_permissao: int, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):
    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para deletar permissao.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para para deletar permissao.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    logger.info('Buscando pela permissao %d...', id_permissao)
    permissao = await session.scalar(select(Permissao).where(Permissao.id == id_permissao))

    if not permissao:
        logger.warning('permissao %d nao foi encontrado(a)', id_permissao)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'permissao de id: {id_permissao} nao foi encontrado(a)',
        )

    logger.info('permissao %d foi encontrado', id_permissao)
    try:
        await session.delete(permissao)
        await session.commit()
        logger.info('Permissao %d deletado/(a) com sucesso', id_permissao)
        await redis.delete('v1:permissao:listar')
        logger.info('Caches do "v1:permissao:listar" foram eliminados')
        return {'msg': f'Permissao de id: {id_permissao} deletada com sucesso'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar permissao de id: %d: %s',
            id_permissao,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: A permissao "{id_permissao}" ja se encontra cadastrada.',
        )


@auth.put('/role/upgrade/{id_role}', status_code=HTTPStatus.OK)
async def atualizar_role(
    schemas: UpgradeRole,
    id_role: int,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para atualizar Role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para atualizar role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    logger.info('Buscando pelo role de id %d...', id_role)
    role = await session.scalar(select(Role).where(Role.id == id_role).options(selectinload(Role.permissoes)))
    if not role:
        logger.warning('Nenhuma role foi encontrada')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhuma role foi encontrada',
        )
    logger.info('role "%s" encontrado...', role.nome)
    role.nome = schemas.nome
    try:
        session.add(role)
        await session.commit()
        await session.refresh(role)
        logger.info('Permissao %s atualizada com sucesso', schemas.nome)
        await redis.delete('v3:role:list')
        logger.info('Caches do "v1:permissao:listar" foram eliminados')
        return {'msg': f'Permissao {schemas.nome} atualizada com sucesso'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar permissao %s: %s',
            schemas.nome,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: A permissao "{schemas.nome}" ja se encontra cadastrada.',
        )


@auth.delete('/role/delete/{id_role}', status_code=HTTPStatus.OK)
async def eliminar_role(
    id_role: int, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):
    if scope.provincia_id is not None:
        logger.warning('Erro: admin %s nao tem permissao para deletar Role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    if scope.municipio_id is not None:
        logger.info('Erro: admin %s nao tem permissao para deletar role.', current_user.email)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
        )

    logger.info('Buscando pelo role de id %d...', id_role)
    role = await session.scalar(select(Role).where(Role.id == id_role).options(selectinload(Role.permissoes)))
    if not role:
        logger.warning('Nenhuma role foi encontrada')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhuma role foi encontrada',
        )
    logger.info('role "%s" encontrado...', role.nome)
    try:
        await session.delete(role)
        await session.commit()
        logger.info('Permissao %s deletado com sucesso', role.nome)
        await redis.delete('v3:role:list')
        logger.info('Caches do "v1:permissao:listar" foram eliminados')
        return {'msg': f'Permissao {role.nome} deletado com sucesso'}
    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao criar permissao %s: %s',
            role.nome,
            str(e.orig),
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Erro: A permissao "{role.nome}" ja se encontra cadastrada.',
        )

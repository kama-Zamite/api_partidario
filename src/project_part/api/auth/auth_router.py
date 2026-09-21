import json
import logging
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Annotated, List
from user_agents import parse
import uuid
import asyncio


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
from project_part.core.rate_limit import limiter
from project_part.core.secury import (
    Get_current_user,
    check_refresh_token,
    check_token_recuperar_senha,
    create_token,
    create_token_recuperar_senha,
    garante_escopo_territorial,
    hash_password,
    verify_password,
    gerar_e_registar_refresh_token,
    verificar_permissao_global_pais,
    
)
from jwt import decode, PyJWTError
from project_part.core.revocar_token_apos_alterar_passWord import (
    emitir_access_token,
    revogar_todas_sessoes,
)  
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
from project_part.services.two_factor_challenge import (
    criar_challenge_2fa,
    get_client_ip,
    obter_challenge_valida,
    registrar_tentativa,
    consumir_challenge,
    CHALLENGE_TTL,
)
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

IP_MAX = 45
UA_MAX = 500

REFRESH_REUSE_GRACE_SECONDS = 10

TypeCacheBase = 'v4:permissao:listar'

router_auth = APIRouter(prefix="/auth", tags=["Autenticação"])


DETAIL_CHALLENGE_INVALIDA = 'Requisição de login inválida ou expirada. Faça login novamente.'
 

def get_client_ip(request: Request) -> str | None:
    xff = request.headers.get('x-forwarded-for')
    if xff:
        valor = xff.split(',')[0].strip()
    else:
        valor = request.client.host if request.client else None
    return valor[:45] if valor else None  # [HARDENING] era: return xff.split(',')[0].strip()




@auth.post('/login',
           status_code=status.HTTP_200_OK,
           summary='Autenticação de Usuário'
           )
@limiter.limit('3/minute')
async def login(
    request: Request, 
    response: Response,
    session: Session,
    token: Access_token,
    # backgroundTasks: BackgroundTasks,
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento na base de dados.'
        )

    if user and not user.ativo:
        logger.warning('Tentativa de login em conta desativada: %s', token.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='E-mail ou senha incorretos')

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


    ip_address = get_client_ip(request)

    if not ip_address:
        ip_address = request.client.host if request.client else None

    # 3. Capturar o User-Agent (Navegador/Dispositivo)
    user_agent = request.headers.get("user-agent")

    
    # --- Fluxo de Autenticação com Sucesso ---
    logger.info('Senha validada. Resetando contadores de tentativas do usuario')

    user.tentativas_apos_bloqueio = 0
    user.tentativa_acertos = 0
    user.bloqueado_ate = None


    if user.two_factor_enabled:
        logger.info('Usuário %s requer verificação de 2FA.', token.username)
        # Aqui você pode implementar a lógica para enviar o código 2FA ou redirecionar para o endpoint de verificação.
        try:
            challenge_token = await criar_challenge_2fa(
                session=session,
                user_id=user.id,
                ip=ip_address,
                user_agent=user_agent,
            )
            session.add(user)
            await session.commit()
            logger.info('Challenge 2FA criado com sucesso para o usuário %s', token.username)
        except Exception as e:
            await session.rollback()
            logger.error('Falha ao criar challenge 2FA: %s', str(e))
            raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail='Erro interno de processamento.',
                    )

        # return  {
        #     "require_2fa": True,
        #     "user_id": str(user.id),
        #     "message": "Autenticação de dois fatores necessária. Verifique seu dispositivo.",
        # }
        response.headers['Cache-Control'] = 'no-store'
        return {
                'require_2fa': True,
                'challenge_token': challenge_token,
                'expires_in': int(CHALLENGE_TTL.total_seconds()),
                'message': 'Autenticação de dois fatores necessária. Verifique seu dispositivo.',
            }
    
    logger.info('Usuário %s autenticado com sucesso (Sem 2FA)', token.username)
    user.ultimo_login = agora
    token_gerado = emitir_access_token(user.id, user.password_alterado_em)


    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,      # <-- Faltava este argumento!
        user_id=user.id, 
        ip=ip_address, 
        user_agent=user_agent
    )

    try:
        session.add(user)
        await session.commit()
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel concluir o login no DB: %s', str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento.',
        )
    
    #enviar email

    user_agent_parsed = parse(user_agent)
    # try:
    #     backgroundTasks.add_task(
    #         email_sucesso_login_async, 
    #         nome_completo=user.nome_completo, 
    #         ip_address=ip_address, 
    #         email_destino=user.email,
    #         navegador=user_agent_parsed.browser.family, 
    #         sistema_operacional=user_agent_parsed.os.family, 
    #         )
    #     logger.info("E-mail de login enviado com sucesso para %s", user.email)
    # except Exception as e:
    #     logger.error("Falha ao enviar e-mail de login para %s: %s", user.email, str(e))


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
@limiter.limit('7/minute')
async def verify_2fa(
    response: Response,
    request: Request,
    body: Login2FARequest,
    session: Session,
    # backgroundTasks: BackgroundTasks,
    _captcha: Claudflare_turnfile,
):
    """
    Endpoint para verificação de autenticação de dois fatores (2FA).
    Recebe a challenge emitida pelo /login (após validar a senha) e o código 2FA.
    Se tudo estiver correcto, emite o access token e o refresh token.
 
    Args:
        body (Login2FARequest): challenge_token + codigo (TOTP de 6 ou backup de 8 dígitos).
 
    Raises:
        HTTPException [401]: challenge inválida, expirada, já usada ou de outra origem.
        HTTPException [400]: código inválido, expirado ou já usado.
        HTTPException [500]: Erro interno do servidor.
        HTTPException [404]: Usuário não encontrado.
        HTTPException [403]: Acesso negado.
        HTTPException [429]: Requisições em excesso.
        HTTPException [409]: Conflito de dados.
    """

    logger.info('Tentativa de verificação 2FA')
    ip_address = get_client_ip(request)
    user_agent = request.headers.get('user-agent')

    challenge = await obter_challenge_valida(
        session=session,
        token_em_claro=body.challenge_token,
        ip=ip_address,
        user_agent=user_agent,
    )
    if not challenge:
        logger.warning('Challenge 2FA inválida, expirada, usada ou de origem diferente (ip=%s)', ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
     
    # if not user or not user.two_factor_enabled:
    #     raise HTTPException(
    #         status_code=status.HTTP_400_BAD_REQUEST,
    #         detail="Requisição de login inválida ou expirada."
    #     )
    challenge_id = challenge.id
    user_id = challenge.user_id

    if not await registrar_tentativa(session, challenge_id):
        logger.warning('Challenge %s sem tentativas restantes', challenge_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)

    logger.info('Tentativa de verificação 2FA para o usuário: %s', user_id)

    user = await session.scalar(select(User).where(User.id == user_id))

    if not user or not user.ativo or user.bloqueado_permanente or not user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=DETAIL_CHALLENGE_INVALIDA)
 

    codigo_limpo = body.codigo.strip()
    codigo_encontrado = None 

    if len(codigo_limpo) == 6:
        totp = pyotp.TOTP(user.two_factor_secret)
        logger.info('Verificando código 2FA')
        #valid_window=1 permite aceitar códigos válidos dentro de uma janela de tempo de 30 segundos antes ou depois do código atual.
        if not totp.verify(codigo_limpo, valid_window=1):
            logger.warning('Código 2FA inválido')
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
        
        for codigo in codigos_disponiveis:
            if verify_password(codigo_limpo, codigo.code_hash):
                codigo_encontrado = codigo
                break
        if not codigo_encontrado:
            logger.warning('Código de backup inválido')
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Código de resgate inválido ou já utilizado."
            )

        # try:
        #     codigo_encontrado.used = True
        #     await session.commit()
        # except Exception as e:
        #     await session.rollback()
        #     logger.error('Não foi possível marcar o código de resgate como usado: %s', str(e))
        #     raise HTTPException(
        #         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        #         detail="Erro ao processar validação de segurança."
        #     )

    else:
        logger.warning('Código 2FA ou de backup com tamanho inválido')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O código deve conter 6 dígitos (aplicativo) ou 8 dígitos (resgate)."
        )


    nome_completo = user.nome_completo
    email_destino = user.email
    user_id_str = str(user.id)
    pwd_alterado_em = user.password_alterado_em



    try:
        if not await consumir_challenge(session, challenge_id):
            # Outro pedido concorrente já consumiu esta challenge (replay)
            await session.rollback()
            logger.warning('Challenge %s já consumida (possível replay)', challenge_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=DETAIL_CHALLENGE_INVALIDA
                )
 
        if codigo_encontrado is not None:
            # UPDATE condicional: garante uso único do código de backup mesmo com concorrência
            resultado_backup = await session.execute(
                update(BackupCode)
                .where(BackupCode.id == codigo_encontrado.id, BackupCode.used == False)  # noqa: E712
                .values(used=True)
            )
            if resultado_backup.rowcount != 1:
                await session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail='Código de resgate inválido ou já utilizado.',
                )
 
        # [FIX-2FA] ultimo_login gravado só agora (login realmente concluído).
        user.ultimo_login = datetime.now(timezone.utc)
        session.add(user)
        await session.commit()
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error('Não foi possível concluir a validação 2FA: %s', str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro ao processar validação de segurança.',
        )

    logger.info('Usuário %s autenticado com sucesso (2FA)', user_id_str)
     
    token_gerado = emitir_access_token(user_id, pwd_alterado_em)

    # ip_address = (
    #     request.headers.get("x-forwarded-for")
    #     or (
    #         request.client.host
    #         if request.client
    #         else None
    #     )
    # )

    # if not ip_address:
    #     ip_address = request.client.host if request.client else None

    # # 3. Capturar o User-Agent (Navegador/Dispositivo)
    # user_agent = request.headers.get("user-agent")
    
    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,      # <-- Faltava este argumento!
        user_id=user_id, 
        ip=ip_address, 
        user_agent=(user_agent or '')[:500] or None,
    )

    try:
        # session.add(user)
        await session.commit()
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))
        raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Erro interno de processamento.',
            )

    user_agent_parsed = parse(user_agent)
    # try:
    #     # backgroundTasks.add_task(
    #     #     email_sucesso_login_async, 
    #     #     nome_completo=user.nome_completo, 
    #     #     ip_address=ip_address, 
    #     #     email_destino=user.email,
    #     #     navegador=user_agent_parsed.browser.family, 
    #     #     sistema_operacional=user_agent_parsed.os.family, 
    #     #     )
    #     logger.info("E-mail de login enviado com sucesso para %s", user.email)
    # except Exception as e:
    #     logger.error("Falha ao enviar e-mail de login para %s: %s", user.email, str(e))
    #     raise HTTPException(
    #         status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    #         detail="Falha ao enviar e-mail de login. Tente novamente mais tarde."
    #     )
    
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
@limiter.limit('5/minute')
async def solicitar_recuperacao(
    request: Request,
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



@auth.post('/redefinir-senha', status_code=status.HTTP_200_OK, summary='Redefinir Senha')
@limiter.limit('5/minute')
async def redefinir_senha(
    request: Request,
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
    pwd_hash = await asyncio.to_thread(hash_password, payload.password)
    try:
        user_banco = await session.scalar(select(User).where(User.email == email))

        if not user_banco:
            logger.info('Usuário associado ao token de recuperação não encontrado: %s', email)
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Usuário associado ao token não encontrado.')

        user_id = user_banco.id
        logger.info('Consumindo token de recuperação: %s', token_id)
        resultado_token = await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.id == token_id,
                PasswordResetToken.usado.is_(False),
            )
            .values(usado=True)
            .execution_options(synchronize_session=False)
        )
        if resultado_token.rowcount != 1:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Este link de recuperação já foi utilizado ou é inválido.",
            )
        logger.info('Token de recuperação consumido com sucesso: %s', token_id)


        data_atualizacao = datetime.now(timezone.utc)
        user_banco.password_hash = pwd_hash
        user_banco.atualizado_em = data_atualizacao
        user_banco.password_alterado_em = data_atualizacao

        await session.flush()

        revogados = await revogar_todas_sessoes(session, user_id, data_atualizacao)
        await session.commit()
        logger.info(
                'Senha atualizada com sucesso para o usuário %s. Sessões revogadas: %d',
                user_id,  # [HARDENING] id em vez do e-mail nos logs
                revogados,
            )

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
    # [SEC-008] Não emitimos sessão aqui: o utilizador tem de fazer login com a nova
    #           senha (e passar no 2FA, se activo).
    return {
        "status": "success",
        "message": "Senha redefinida com sucesso!",
    }
        
        
    # try:
    #     logger.info('Busca o token com condição de ainda não ter sido usado')
    #     query_token = select(PasswordResetToken).where(
    #         PasswordResetToken.id == token_id,
    #         PasswordResetToken.usado.is_(False),
    #     )
    #     token_banco = await session.scalar(query_token)

    #     if not token_banco:
    #         raise HTTPException(
    #             status_code=HTTPStatus.BAD_REQUEST,
    #             detail="Este link de recuperação já foi utilizado ou é inválido.",
    #         )
    #     logger.info('Token de recuperação encontrado e válido: %s', token_id)
    #     query = select(User).where(
    #         User.email == email).options(selectinload(User.provincia), selectinload(User.municipio))

    #     user_banco = await session.scalar(query)

    #     if not user_banco:
    #         raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Usuário associado ao token não encontrado.')

    #     token_banco.usado = True
    #     pwd_hash = hash_password(payload.password)
    #     user_banco.password_hash = pwd_hash
    #     data_atualizacao = datetime.now(timezone.utc)
    #     user_banco.atualizado_em = data_atualizacao


    #     await session.commit()
    #     logger.info('Senha atualizada com sucesso para o usuário: %s', email)
    # except HTTPException:
    #     raise
    # except Exception as e:
    #     await session.rollback()
    #     logger.error(
    #         "Erro crítico ao redefinir senha (token_id=%s): %s",
    #         token_id,
    #         str(e),
    #     )
    #     raise HTTPException(
    #         status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    #         detail="Erro interno ao processar a redefinição de senha.",
    #     )
    # return {
    #     "status": "success",
    #     "message": "Senha redefinida com sucesso!",
    # }



@auth.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
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
        # 1. Buscar usuário
        # =====================================================

        user = await session.scalar(
            select(User)
            .where(User.id == user_id)
        )

        if not user:
            logger.warning(
                "Refresh token com jti de outro utilizador. jwt_user=%s",
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token com jti de outro utilizador.",
            )
        # =====================================================
        # 2. LOCK DA LINHA
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
            logger.warning(
                "Refresh token não encontrado. jti=%s",
                token_jti,
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token não encontrado.",
            )

        if str(db_token.user_id) != str(user_id):
            logger.warning(
                "Refresh token com jti de outro utilizador. jwt_user=%s",
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token com jti de outro utilizador.",
            )
        # =====================================================
        # 3. Verificar estado
        # =====================================================

        if db_token.revogado:
            logger.warning(
                "Refresh token revogado. jti=%s",
                token_jti,
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token revogado.",
            )

        # =====================================================
        # 4. Detectar REUTILIZAÇÃO
        # =====================================================

        if db_token.utilizado:

            utilizado_ha = (
                    (agora - db_token.utilizado_em).total_seconds()
                    if db_token.utilizado_em
                    else None
                        )

            if utilizado_ha is not None and 0 <= utilizado_ha <= REFRESH_REUSE_GRACE_SECONDS:
                logger.info(
                    "Refresh concorrente tolerado (%.1fs após a rotação). user_id=%s",
                    utilizado_ha,
                    user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Sessão em renovação. Repita o pedido.",
                )

            logger.warning(
                "Reutilização de refresh token detectada. "
                "user_id=%s",
                user_id,
            )

            # Revoga todas as sessões do usuário.
            await revogar_todas_sessoes(session, user_id, agora)
             

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Reutilização de refresh token detectada.",
            )

        # =====================================================
        # 5. Verificar expiração
        # =====================================================

        if db_token.expira_em <= agora:

            db_token.revogado = True
            db_token.revogado_em = agora

            await session.commit()
            logger.warning(
                "Refresh token expirado. user_id=%s",
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão expirada.",
            )



         
        # =====================================================
        # 6. Verificar estado da conta
        # =====================================================
        # (O utilizador já foi carregado e bloqueado no passo 1.)
        # [HARDENING] Conta desativada ou bloqueada permanentemente: revoga TODAS as
        #             sessões (antes só revogava o token apresentado, e os outros
        #             dispositivos continuavam a poder renovar). Alinhado com o check_token.
 
        if not user.ativo or user.bloqueado_permanente:
            logger.warning(
                "Refresh token de conta desativada ou bloqueada permanentemente. user_id=%s ",
                user_id,
            )
            await revogar_todas_sessoes(session, user_id, agora)
 
            await session.commit()
 
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token de conta desativada ou bloqueada permanentemente. user_id=%s.",
                params={"user_id": user_id},
            )
        
        # =====================================================
        # 7. Consumir token antigo
        # =====================================================

        db_token.utilizado = True
        db_token.utilizado_em = agora

        # =====================================================
        # 8. Informações da nova sessão
        # =====================================================

        # ip_address = (
        #     request.headers.get("x-forwarded-for")
        #     or (
        #         request.client.host
        #         if request.client
        #         else None
        #     )
        # )

        ip_address = (get_client_ip(request) or "")[:IP_MAX] or None
         

        # user_agent = request.headers.get(
        #     "user-agent"
        # )

        user_agent = (
            request.headers.get("user-agent") or ""
        )[:UA_MAX] or None
         

        # =====================================================
        # 9. Criar NOVO refresh token
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
        # 10. Criar novo access token
        # =====================================================

        # novo_access_token = create_token(
        #     {
        #         "sub": str(user.id),
        #         "type": "access",
        #     }
        # )

        novo_access_token = emitir_access_token(
            user.id,
            user.password_alterado_em,
        )
        # =====================================================
        # 11. COMMIT ATÔMICO
        # =====================================================
        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.exception(
                "Falha ao gravar refresh token no banco de dados."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro interno de autenticação.",
            )

        # =====================================================
        # 12. Atualizar cookies
        # =====================================================

        set_auth_cookies(
            response=response,
            access_token=novo_access_token,
            refresh_token=novo_refresh_token,
        )

        # response.status_code = status.HTTP_200_OK
        response.headers["Cache-Control"] = "no-store"

        # Agora o retorno é 100% legítimo e o FastAPI aceitará o JSON perfeitamente
        return {
            "status": "success",
            "message": "Tokens de autenticação renovados com sucesso."
        }
    except HTTPException:
        logger.warning(
            "Falha ao renovar refresh token para user_id=%s. Detalhes: %s",
            user_id,
            str(e)
        )
        raise

    except Exception:
        logger.warning(
            "Falha ao renovar refresh token para user_id=%s. Detalhes: %s",
            user_id,
            str(e)
        )

        await session.rollback()

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
@limiter.limit('10/minute')
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
@limiter.limit('5/minute')
async def criar_permissao(
    request: Request,
    schema: CreatePermissao,
    session: Session,
    redis: Redis, 
    current_user: Get_current_user, scope: ScopeValid
):
    verificar_permissao_global_pais(scope, current_user)
    logger.info('Procurar usuario: %s no banco de dados...', current_user.nome_completo)
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
@limiter.limit('5/minute')
async def listar_permissoes(
    request: Request,
    response: Response,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid
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
@limiter.limit('5/minute')
async def criar_role(
    request: Request,
    schemas: CreateRole,
    session: Session,
    redis: Redis, 
    current_user: Get_current_user,
    scope: ScopeValid
):
    verificar_permissao_global_pais(scope, current_user)

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
@limiter.limit('5/minute')
async def listar_role(
    request: Request,
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
@limiter.limit('5/minute')
async def atualizar_permissao(
    request: Request,
    id_permissao: int,
    schemas: UpgradePermissao,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """Endpoint para atualizar uma permissão existente. Recebe o ID da permissão e os novos dados, verifica a validade do ID e atualiza a permissão no banco de dados."""
    verificar_permissao_global_pais(scope, current_user)
    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para atualizar Permissoes.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para atualizar permissoes.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

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
@limiter.limit('5/minute')
async def eliminar_permissao(
    request: Request,
    id_permissao: int, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):
    """
    Endpoint para deletar uma permissão existente. Recebe o ID da permissão, verifica a validade do ID e remove a permissão do banco de dados.
    Args:
        request (Request): O objeto de requisição.
        id_permissao (int): O ID da permissão a ser deletada.
        session (Session): A sessão do banco de dados.
        redis (Redis): A instância do Redis.
        current_user (Get_current_user): O usuário atual.
        scope (ScopeValid): O escopo de validade.
    Raises:
        HTTPException [403 FORBIDDEN]: Se o usuário não tiver permissão para deletar
        HTTPException [404 NOT FOUND]: Se a permissão não for encontrada.

    """
    verificar_permissao_global_pais(scope, current_user)
    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para deletar permissao.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para para deletar permissao.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

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
@limiter.limit('5/minute')
async def atualizar_role(
    request: Request,
    schemas: UpgradeRole,
    id_role: int,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """ 
    Endpoint para atualizar uma role existente. Recebe o ID da role e os novos dados, verifica a validade do ID e atualiza a role no banco de dados.
    Args:
        request (Request): O objeto de requisição.
        schemas (UpgradeRole): O esquema de atualização da role.
        id_role (int): O ID da role a ser atualizada.
        session (Session): A sessão do banco de dados.
        redis (Redis): A instância do Redis.
        current_user (Get_current_user): O usuário atual.
        scope (ScopeValid): O escopo de validade.
    Raises:
        HTTPException [403 FORBIDDEN]: Se o usuário não tiver permissão para atualizar a

    """
    verificar_permissao_global_pais(scope, current_user)
    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para atualizar Role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para atualizar role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

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
@limiter.limit('5/minute')
async def eliminar_role(
    request: Request,
    id_role: int, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
): 

    verificar_permissao_global_pais(scope, current_user)
    # if scope.provincia_id is not None:
    #     logger.warning('Erro: admin %s nao tem permissao para deletar Role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

    # if scope.municipio_id is not None:
    #     logger.info('Erro: admin %s nao tem permissao para deletar role.', current_user.email)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail=f'Erro: admin {current_user.email} nao tem permissao'
    #     )

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

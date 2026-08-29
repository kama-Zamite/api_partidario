import logging
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Cookie, status
from fastapi.security import OAuth2PasswordBearer
from jwt import DecodeError, PyJWTError, decode, encode
from pwdlib import PasswordHash
from slowapi.util import get_remote_address
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from project_part.db.session import get_session
from project_part.model.models import (
    AdminScope,
    PasswordResetToken,
    Role,
    User,
    UserRefreshToken,
)

from .setting import settings

logger = logging.getLogger(__name__)
passHash = PasswordHash.recommended()
Oauth_bearer = OAuth2PasswordBearer(tokenUrl='/auth/login')

token_bearer = Annotated[str, Depends(Oauth_bearer)]
Session = Annotated[AsyncSession, Depends(get_session)]


def hash_password(plainText: str):
    return passHash.hash(plainText)


def verify_password(plainText: str, hashPassWord: str):
    return passHash.verify(plainText, hashPassWord)


def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=int(settings.EXPIRE_TOKEN))
    to_encode.update({'exp': int(expire.timestamp())})
    payload = encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return payload


async def create_token_recuperar_senha(
        user_uuid: uuid.UUID,
        email: str,
        session: Session
        ) -> str:
    """Cria o token no banco e retorna o JWT (para ser setado no cookie)."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=int(settings.EXPIRE_TOKEN_RECUPERAR_SENHA))

    token_id = str(uuid.uuid4())

    db_token = PasswordResetToken(
        id=token_id,
        user_id=user_uuid,
        usado=False
        )
    try:
        session.add(db_token)
        await session.commit()
    except Exception as e:
        logger.error("Erro ao adicionar token de recuperação de senha: %s", str(e.args))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro ao criar token de recuperação de senha!",
        )

    dados_token = {
        'sub': str(email),
        'jti': str(token_id),
        'scope': 'recuperacao_senha',
        'exp': int(expire.timestamp()),
    }
    return encode(
        dados_token,
        settings.SECRET_KEY_RECUPERAR_SENHA,
        algorithm=settings.ALGORITHM
        )


# async def check_token_recuperar_senha(token: str, session: Session) -> str:
#     try:
#         payload = decode(
#             token, settings.SECRET_KEY_RECUPERAR_SENHA, algorithms=[settings.ALGORITHM]
#         )
#         email = payload.get('sub')
#         scope = payload.get('scope')
#         token_id = payload.get('jti')

#         if not email or scope != 'recuperacao_senha' or not token_id:
#             logger.warning("Token de recuperação de senha inválido ou com escopo incorreto.")
#             raise HTTPException(
#                 status_code=HTTPStatus.UNAUTHORIZED,
#                 detail='Token de recuperação de senha inválido!',
#                 headers={'WWW-Authenticate': 'Bearer'},
#             )
#     except PyJWTError as e:
#         logger.error("Erro ao decodificar o token de recuperação de senha: %s", str(e.args))
#         raise HTTPException(
#             status_code=HTTPStatus.UNAUTHORIZED,
#             detail='Token de recuperação de senha inválido!',
#             headers={'WWW-Authenticate': 'Bearer'},
#         )

#     query_token = select(PasswordResetToken).where(PasswordResetToken.id == token_id)
#     token_banco = await session.scalar(query_token)

#     if not token_banco or token_banco.usado:
#         logger.warning(f"Tentativa de reutilização do token ID {token_id} para o e-mail: {email}")
#         raise HTTPException(
#             status_code=HTTPStatus.UNAUTHORIZED,
#             detail="Este link de recuperação já foi utilizado e foi anulado!"
#         )

#     user_banco = await session.scalar(select(User).where(User.email == email))

#     # NOVO: valida se o usuário ainda existe antes de usar user_banco.id
#     if not user_banco:
#         logger.warning("Usuário com e-mail %s não encontrado ao validar token de recuperação.", email)
#         raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Utilizador não encontrado.")

#     try:
#         token_banco.usado = True
#         session.add(token_banco)

#         # CORRIGIDO: o update precisa ser executado via session.execute(), não passado para commit()
#         await session.execute(
#             update(PasswordResetToken)
#             .where(
#                 PasswordResetToken.user_id == user_banco.id,
#                 PasswordResetToken.usado == False,
#                 PasswordResetToken.id != token_id
#             )
#             .values(usado=True)
#         )

#         await session.commit()
#     except IntegrityError:
#         await session.rollback()
#         raise HTTPException(HTTPStatus.BAD_REQUEST, detail='Erro ao salvar os dados.')

#     return email


async def check_token_recuperar_senha(
        token: str | None,
        session: Session
        ) -> tuple[str, str]:
    """Valida o token e retorna (email, token_id) sem gravar nada no banco."""

    if not token:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="Token de recuperação de senha não encontrado no cookie!",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = decode(
            token,
            settings.SECRET_KEY_RECUPERAR_SENHA,
            algorithms=[settings.ALGORITHM]
            )
        
        email = payload.get('sub')
        scope = payload.get('scope')
        token_id = payload.get('jti')

        if not email or scope != 'recuperacao_senha' or not token_id:
            logger.warning('Token de recuperação de senha inválido ou com escopo incorreto.')
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED,
                detail='Token de recuperação de senha inválido!',
                headers={'WWW-Authenticate': 'Bearer'},
            )
    except PyJWTError as e:
        logger.error('Erro ao decodificar o token de recuperação de senha: %s', str(e.args))
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail='Token de recuperação de senha inválido!',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    query_token = select(PasswordResetToken).where(PasswordResetToken.id == token_id)
    token_banco = await session.scalar(query_token)

    if not token_banco or token_banco.usado:
        logger.warning('Tentativa de reutilização do token ID %s para o e-mail: %s', token_id, email)
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail='Este link de recuperação já foi utilizado e foi anulado!'
        )

    return email, token_id


# def create_refresh_token(data: dict):
#     to_encode = data.copy()
#     expire = datetime.now(timezone.utc) + timedelta(minutes=int(settings.REFRESH_TOKEN))
#     to_encode.update({'exp': int(expire.timestamp())})
#     payload = encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

#     return payload


async def check_token(request: Request, session: Session):
    http_responses = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail='Error: token invalido!',
        headers={'WWW-Authenticate': 'Bearer'},
    )
    token = request.cookies.get('access_token')
    auth_header = request.headers.get('Authorization')
    if auth_header and 'undefined' in auth_header:
        logger.warning("Front-end enviou 'Authorization: Bearer undefined'")
        raise http_responses

    if not token:
        logger.warning("Tentativa de acesso sem o cookie 'access_token'")
        raise http_responses

    try:
        payload = decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get('sub')
        expire_token = payload.get('exp')
        logger.info('CONTEÚDO DO TOKEN -> sub: %s , exp: %d', str(user_id), int(expire_token))
        if not user_id or not expire_token:
            logger.warning("Token não possui 'sub' ou 'exp'")
            raise http_responses
    except PyJWTError as e:
        logger.error('ERRO CRÍTICO NA DECODIFICAÇÃO DO JWT: %s', str(e.args))
        raise http_responses

    try:
        user_uuid = UUID(user_id)
    except ValueError:
        logger.warning("Token com 'sub' inválido (não é UUID): %s", user_id)
        raise http_responses

    user = await session.scalar(select(User).where(User.id == user_uuid).options(selectinload(User.scope)))
    if not user:
        logger.warning('Usuário com ID %s não existe mais no banco', user_uuid)
        raise http_responses

    return user


def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=int(settings.REFRESH_TOKEN))
    to_encode.update({'exp': int(expire.timestamp())})
    payload = encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return payload


Get_current_user = Annotated[User, Depends(check_token)]


# async def check_refresh_token(request: Request, session: AsyncSession):  # <-- Corrigido para AsyncSession
#     http_responses = HTTPException(
#         status_code=HTTPStatus.UNAUTHORIZED,
#         detail='Error: refresh_token invalido!',
#         headers={'WWW-Authenticate': 'Bearer'},
#     )
    
#     refresh_token = request.cookies.get('refresh_token')
#     auth_header = request.headers.get('Authorization')

#     if auth_header and 'undefined' in auth_header:
#         logger.warning("Front-end enviou 'Authorization: Bearer undefined'")
#         raise http_responses
    
#     if not refresh_token:
#         logger.warning("Tentativa de acesso sem o cookie 'refresh_token'")  # <-- Corrigido texto do log
#         raise http_responses
    
#     try:
#         payload = decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
#         user_id = payload.get('sub')
#         expire_refresh_token = payload.get('exp')
        
#         # Validação preventiva antes do log para evitar int(None)
#         if not user_id or not expire_refresh_token:
#             logger.warning("Refresh Token não possui 'sub' ou 'exp'")
#             raise http_responses
            
#         logger.info('CONTEÚDO DO REFRESH TOKEN -> sub: %s , exp: %s', str(user_id), str(expire_refresh_token))
        
#     except PyJWTError as e:
#         logger.error('ERRO CRÍTICO NA DECODIFICAÇÃO DO JWT: %s', str(e.args) if e.args else str(e))
#         raise http_responses

#     try:
#         parseInt = UUID(user_id)
#     except ValueError:
#         logger.warning("Token com 'sub' inválido (não é UUID): %s", user_id)
#         raise http_responses
        
#     # Executa a busca assíncrona corretamente
#     user = await session.scalar(
#         select(User)
#         .where(User.id == parseInt)
#         .options(selectinload(User.scope))
#     )
    
#     if not user:
#         logger.warning('Usuário com ID %s não existe mais no banco', parseInt)
#         raise http_responses
        
#     return user

async def gerar_e_registar_refresh_token(
    session: Session,
    user_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
) -> str:

    agora = datetime.now(timezone.utc)

    # Uma única fonte de verdade para a expiração.
    expiracao = agora + timedelta(
        seconds=settings.TIME_REFRESH_TOKEN
    )

    # JTI aleatório e único.
    token_jti = str(uuid.uuid4())

    payload = {
        "sub": str(user_id),
        "jti": token_jti,
        "type": "refresh",
        "iat": int(agora.timestamp()),
        "exp": int(expiracao.timestamp()),
    }

    refresh_token_jwt = encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    novo_token = UserRefreshToken(
        token_jti=token_jti,
        user_id=user_id,
        ip_address=ip,
        user_agent=user_agent,
        revogado=False,
        utilizado=False,
        expira_em=expiracao,
    )

    session.add(novo_token)

    try:
        # Não fazemos commit aqui.
        #
        # Quem chama esta função controla a transação.
        await session.flush()

    except Exception:

        await session.rollback()

        logger.exception(
            "Falha ao registrar refresh token."
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno de autenticação.",
        )

    return refresh_token_jwt


async def check_refresh_token(
    request: Request,
) -> dict:

    erro = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão inválida.",
    )

    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise erro

    try:

        payload = decode(
            refresh_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )

        user_id = payload.get("sub")
        token_jti = payload.get("jti")
        token_type = payload.get("type")

        if not user_id:
            raise erro

        if not token_jti:
            raise erro

        if token_type != "refresh":
            raise erro

        user_uuid = uuid.UUID(user_id)

        return {
            "user_id": user_uuid,
            "jti": token_jti,
        }

    except (
        PyJWTError,
        ValueError,
        TypeError,
    ):

        raise erro



    

class GaranteEscopoTerritorial:
    """
    Dependência reutilizável para validar permissões de escrita (Criar, Editar, Deletar)
    baseadas na Role e no Escopo Territorial do Administrador.
    """

    async def __call__(self, current_user: Get_current_user, session: Session) -> AdminScope:

        # 1. Validação de Role (Busca otimizada)
        current_role_stmt = select(Role.nome).where(Role.id == current_user.role_id)
        current_role_name = await session.scalar(current_role_stmt)

        if current_role_name != 'admin':
            logger.warning('Usuário %s sem permissão administrativa tentou executar ação protegida.', current_user.id)
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Requer privilégios de administrador.'
            )
        scope_stmt = select(AdminScope).where(AdminScope.user_id == current_user.id)
        scope = await session.scalar(scope_stmt)

        if not scope:
            logger.warning('Admin %s tentou operar sem um escopo territorial configurado.', current_user.id)
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Administrador não possui escopo configurado.'
            )

        return scope


garante_escopo_territorial = GaranteEscopoTerritorial()


def verificar_permissao_global_pais(scope: AdminScope, current_user: Get_current_user):
    """
    Verifica se o Admin possui amarras territoriais.
    Para criar Províncias ou Municípios, o escopo DEVE ser global (campos nulos).
    """
    if scope.provincia_id is not None or scope.municipio_id is not None:
        logger.warning(
            'Tentativa de violação de escopo: Admin regional %s tentou alterar a estrutura político-administrativa.',
            current_user.email,
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Apenas administradores globais podem gerenciar a estrutura territorial do país.',
        )


def get_logged_user_id(request: Request) -> str:
    auth_header = request.headers.get('authorization')

    if auth_header and auth_header.startswith('Bearer '):
        partes = auth_header.split(' ')
        if len(partes) > 1:
            token = partes[1].strip()
            if token:
                return f'rate_limit_user:{token}'

    # CORREÇÃO: Se não houver token, usa o IP como identificador
    return f'rate_limit_ip:{get_remote_address(request)}'

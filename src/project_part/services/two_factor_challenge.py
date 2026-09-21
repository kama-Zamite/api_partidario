# =============================================================================
# two_factor_challenge.py — SUBSTITUI o teu ficheiro actual (mesmos nomes de
# colunas: usado_as, expira_as, tentativas; mesmo alias `Session`).
#
# O que mudou em relação ao que tens em produção (marcado com # [FIX-2FA]):
#   1) obter_challenge_valida regista NO SERVIDOR o motivo exacto da rejeição
#      (o cliente continua a receber o mesmo 401 genérico). Hoje falha em silêncio.
#   2) CHALLENGE_EXIGIR_IP = False: diferença de IP passa a ser só um WARNING.
#   3) strip() no token recebido (espaços/newlines colados a mais).
#   4) get_client_ip trunca a 45 caracteres (limite de UserRefreshToken.ip_address).
#   5) Comparações seguras para qualquer texto (compare_digest com str não-ASCII
#      levanta TypeError -> 500 com um x-forwarded-for/user-agent estranho).
# =============================================================================
import hashlib
import hmac
import logging
import secrets
import uuid

from datetime import timedelta, timezone, datetime

from fastapi import (
    Request,
    Depends,
    HTTPException,
    status
)
from typing import Annotated
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from project_part.model.models import TwoFactorChallenge
from project_part.db.session import get_session

# [FIX-2FA] Logger do módulo (aparece no mesmo formato dos teus outros logs)
logger = logging.getLogger(__name__)

# [FIX-2FA] Parâmetros da challenge
# Tens 20 min. Funciona, mas é uma janela grande para um segundo factor:
# 5 a 10 minutos é o habitual.
CHALLENGE_TTL = timedelta(minutes=20)
CHALLENGE_MAX_ATTEMPTS = 5             # tentativas de código por challenge

# [FIX-2FA] Ligação ESTRITA ao IP. Atrás de Cloudflare + Render e com utilizadores em
#           redes móveis o IP pode mudar entre /login e /2fa-verify. Com False o IP
#           continua a ser guardado e comparado, mas a diferença só gera um WARNING.
#           Continuam a proteger: token de 256 bits, expiração, uso único, limite de
#           tentativas e ligação ao User-Agent.
CHALLENGE_EXIGIR_IP = False

IP_MAX = 45  # [FIX-2FA] limite da coluna UserRefreshToken.ip_address

Session = Annotated[AsyncSession, Depends(get_session)]

def _sha256(valor: str | None) -> str:
    return hashlib.sha256((valor or '').encode('utf-8')).hexdigest()


def _iguais(a: str | None, b: str | None) -> bool:
    """
    [FIX-2FA] Comparação em tempo constante SEM o limite ASCII do compare_digest
    para str (um header com caracteres não-ASCII dava TypeError -> 500).
    """
    return hmac.compare_digest((a or '').encode('utf-8'), (b or '').encode('utf-8'))


def get_client_ip(request: Request) -> str | None:
    """
    [FIX-2FA] Extrai o IP do cliente de forma consistente (login e 2fa-verify
    têm de usar exactamente a mesma lógica, senão a comparação falha).

    O X-Forwarded-For pode ser uma lista "cliente, proxy1, proxy2" -> usamos o
    primeiro. ATENÇÃO: esse header só é fiável se a app estiver atrás de um
    proxy de confiança que o sobrescreve (nginx/Cloudflare). Caso contrário o
    cliente pode forjá-lo. Idealmente configura o uvicorn com
    --proxy-headers --forwarded-allow-ips=<ip do proxy> e usa request.client.host.
    """
    xff = request.headers.get('x-forwarded-for')
    if xff:
        valor = xff.split(',')[0].strip()
    else:
        valor = request.client.host if request.client else None
    # [FIX-2FA] Truncado ao limite da coluna (antes: return xff.split(',')[0].strip())
    return valor[:IP_MAX] if valor else None


async def criar_challenge_2fa(
    session: AsyncSession,  # [FIX-2FA] era `Session` (alias com Depends); numa função normal o tipo correcto é AsyncSession
    user_id: uuid.UUID,
    ip: str | None,
    user_agent: str | None,
) -> str:
    """
    [FIX-2FA] Emite a challenge APÓS a senha ser validada.
    Devolve o token em claro (só existe aqui e no cliente).
    NÃO faz commit: o chamador faz, para ficar na mesma transacção do login.
    """
    agora = datetime.now(timezone.utc)

    # Invalida challenges pendentes anteriores do mesmo utilizador
    # (só a mais recente é válida).
    await session.execute(
        update(TwoFactorChallenge)
        .where(TwoFactorChallenge.user_id == user_id, TwoFactorChallenge.usado_as.is_(None))
        .values(usado_as=agora)
    )

    token_em_claro = secrets.token_urlsafe(32)  # 256 bits de entropia
    session.add(
        TwoFactorChallenge(
            token_hash=_sha256(token_em_claro),
            user_id=user_id,
            ip_address=ip,
            user_agent_hash=_sha256(user_agent),
            tentativas=0,
            expira_as=agora + CHALLENGE_TTL,
        )
    )
    return token_em_claro


async def obter_challenge_valida(
    session: AsyncSession,
    token_em_claro: str,
    ip: str | None,
    user_agent: str | None,
) -> TwoFactorChallenge | None:
    """
    [FIX-2FA] Devolve a challenge só se: existir, não estiver usada, não estiver
    expirada, não tiver esgotado tentativas e o User-Agent coincidir com o do login
    (o IP só é exigido se CHALLENGE_EXIGIR_IP = True).

    O CLIENTE recebe sempre o mesmo 401 genérico; o SERVIDOR regista o motivo exacto
    de cada rejeição, para diagnosticar produção sem dar pistas a um atacante.
    Nunca se regista o token, só o id da challenge.
    """
    token_limpo = (token_em_claro or '').strip()  # [FIX-2FA] strip()

    challenge = await session.scalar(
        select(TwoFactorChallenge).where(
            TwoFactorChallenge.token_hash == _sha256(token_limpo)
        )
    )
    if not challenge:
        # secrets.token_urlsafe(32) gera SEMPRE 43 caracteres. Outro comprimento
        # significa token copiado com aspas/espaços ou cortado.
        logger.warning(
            '2FA challenge rejeitada: token não encontrado na base '
            '(comprimento recebido=%d, esperado=43)',
            len(token_limpo),
        )
        return None

    agora = datetime.now(timezone.utc)
    if challenge.usado_as is not None:
        logger.warning(
            '2FA challenge rejeitada: já usada ou invalidada por um login mais recente '
            '(challenge=%s, usado_as=%s)', challenge.id, challenge.usado_as,
        )
        return None
    if challenge.expira_as <= agora:
        logger.warning(
            '2FA challenge rejeitada: expirada (challenge=%s, expira_as=%s, agora=%s)',
            challenge.id, challenge.expira_as, agora,
        )
        return None
    if challenge.tentativas >= CHALLENGE_MAX_ATTEMPTS:
        logger.warning('2FA challenge rejeitada: tentativas esgotadas (challenge=%s)', challenge.id)
        return None

    # Comparações em tempo constante
    if not _iguais(challenge.ip_address, ip):
        logger.warning(
            '2FA challenge: IP diferente do login (challenge=%s, login=%r, agora=%r, exigir_ip=%s)',
            challenge.id, challenge.ip_address, ip, CHALLENGE_EXIGIR_IP,
        )
        if CHALLENGE_EXIGIR_IP:
            return None
    if not _iguais(challenge.user_agent_hash, _sha256(user_agent)):
        logger.warning(
            '2FA challenge rejeitada: User-Agent diferente do login (challenge=%s)', challenge.id,
        )
        return None

    return challenge


async def registrar_tentativa(session: AsyncSession, challenge_id: uuid.UUID) -> bool:
    """
    [FIX-2FA] Incrementa tentativas de forma ATÓMICA (UPDATE condicional) ANTES
    de validar o código. Assim, pedidos concorrentes não conseguem contornar o
    limite. Devolve False se a challenge já não aceitar mais tentativas.
    """
    resultado = await session.execute(
        update(TwoFactorChallenge)
        .where(
            TwoFactorChallenge.id == challenge_id,
            TwoFactorChallenge.usado_as.is_(None),
            TwoFactorChallenge.tentativas < CHALLENGE_MAX_ATTEMPTS,
        )
        .values(tentativas=TwoFactorChallenge.tentativas + 1)
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao registrar tentativa de 2FA"
            )
    return resultado.rowcount == 1


async def consumir_challenge(session: AsyncSession, challenge_id: uuid.UUID) -> bool:
    """
    [FIX-2FA] Marca como usada de forma ATÓMICA (uso único). Se dois pedidos
    tentarem consumir a mesma challenge, só um obtém rowcount == 1.
    NÃO faz commit: o chamador faz, junto com o resto da transacção.
    """
    agora = datetime.now(timezone.utc)
    resultado = await session.execute(
        update(TwoFactorChallenge)
        .where(
            TwoFactorChallenge.id == challenge_id,
            TwoFactorChallenge.usado_as.is_(None),
            TwoFactorChallenge.expira_as > agora,
        )
        .values(usado_as=agora)
    )
    return resultado.rowcount == 1











# import hashlib
# import hmac
# import secrets
# import uuid

# from datetime import timedelta, timezone, datetime
 
# from fastapi import (
#     Request,
#     Depends,
#     HTTPException,
#     status
# )
# from typing import Annotated
# from sqlalchemy import select, update
# from sqlalchemy.ext.asyncio import AsyncSession
# from project_part.model.models import TwoFactorChallenge
# from project_part.db.session import get_session


# # [FIX-2FA] Parâmetros da challenge
# CHALLENGE_TTL = timedelta(minutes=20)   # curta duração
# CHALLENGE_MAX_ATTEMPTS = 5             # tentativas de código por challenge
 
# Session = Annotated[AsyncSession, Depends(get_session)]

# def _sha256(valor: str | None) -> str:
#     return hashlib.sha256((valor or '').encode('utf-8')).hexdigest()
 
 
# def get_client_ip(request: Request) -> str | None:
#     """
#     [FIX-2FA] Extrai o IP do cliente de forma consistente (login e 2fa-verify
#     têm de usar exactamente a mesma lógica, senão a comparação falha).
 
#     O X-Forwarded-For pode ser uma lista "cliente, proxy1, proxy2" -> usamos o
#     primeiro. ATENÇÃO: esse header só é fiável se a app estiver atrás de um
#     proxy de confiança que o sobrescreve (nginx/Cloudflare). Caso contrário o
#     cliente pode forjá-lo. Idealmente configura o uvicorn com
#     --proxy-headers --forwarded-allow-ips=<ip do proxy> e usa request.client.host.
#     """
#     xff = request.headers.get('x-forwarded-for')
#     if xff:
#         return xff.split(',')[0].strip()
#     return request.client.host if request.client else None
 
 
# async def criar_challenge_2fa(
#     session: Session,
#     user_id: uuid.UUID,
#     ip: str | None,
#     user_agent: str | None,
# ) -> str:
#     """
#     [FIX-2FA] Emite a challenge APÓS a senha ser validada.
#     Devolve o token em claro (só existe aqui e no cliente).
#     NÃO faz commit: o chamador faz, para ficar na mesma transacção do login.
#     """
#     agora = datetime.now(timezone.utc)
 
#     # Invalida challenges pendentes anteriores do mesmo utilizador
#     # (só a mais recente é válida).
#     await session.execute(
#         update(TwoFactorChallenge)
#         .where(TwoFactorChallenge.user_id == user_id, TwoFactorChallenge.usado_as.is_(None))
#         .values(usado_as=agora)
#     )
 
#     token_em_claro = secrets.token_urlsafe(32)  # 256 bits de entropia
#     session.add(
#         TwoFactorChallenge(
#             token_hash=_sha256(token_em_claro),
#             user_id=user_id,
#             ip_address=ip,
#             user_agent_hash=_sha256(user_agent),
#             tentativas=0,
#             expira_as=agora + CHALLENGE_TTL,
#         )
#     )
#     return token_em_claro
 
 
# async def obter_challenge_valida(
#     session: Session,
#     token_em_claro: str,
#     ip: str | None,
#     user_agent: str | None,
# ) -> TwoFactorChallenge | None:
#     """
#     [FIX-2FA] Devolve a challenge só se: existir, não estiver usada, não estiver
#     expirada, não tiver esgotado tentativas e o IP/User-Agent coincidirem com os
#     do login. Qualquer falha -> None (o chamador responde sempre com a mesma
#     mensagem genérica, para não dar pistas).
#     """
#     challenge = await session.scalar(
#         select(TwoFactorChallenge).where(
#             TwoFactorChallenge.token_hash == _sha256(token_em_claro)
#         )
#     )
#     if not challenge:
#         return None
 
#     agora = datetime.now(timezone.utc)
#     if challenge.usado_as is not None:
#         return None
#     if challenge.expira_as <= agora:
#         return None
#     if challenge.tentativas >= CHALLENGE_MAX_ATTEMPTS:
#         return None
 
#     # Comparações em tempo constante
#     if not hmac.compare_digest(challenge.ip_address or '', ip or ''):
#         return None
#     if not hmac.compare_digest(challenge.user_agent_hash, _sha256(user_agent)):
#         return None
 
#     return challenge
 
 
# async def registrar_tentativa(session: AsyncSession, challenge_id: uuid.UUID) -> bool:
#     """
#     [FIX-2FA] Incrementa tentativas de forma ATÓMICA (UPDATE condicional) ANTES
#     de validar o código. Assim, pedidos concorrentes não conseguem contornar o
#     limite. Devolve False se a challenge já não aceitar mais tentativas.
#     """
#     resultado = await session.execute(
#         update(TwoFactorChallenge)
#         .where(
#             TwoFactorChallenge.id == challenge_id,
#             TwoFactorChallenge.usado_as.is_(None),
#             TwoFactorChallenge.tentativas < CHALLENGE_MAX_ATTEMPTS,
#         )
#         .values(tentativas=TwoFactorChallenge.tentativas + 1)
#     )
#     try:
#         await session.commit()
#     except Exception:
#         await session.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Erro ao registrar tentativa de 2FA"
#             )
#     return resultado.rowcount == 1
 
 
# async def consumir_challenge(session: AsyncSession, challenge_id: uuid.UUID) -> bool:
#     """
#     [FIX-2FA] Marca como usada de forma ATÓMICA (uso único). Se dois pedidos
#     tentarem consumir a mesma challenge, só um obtém rowcount == 1.
#     NÃO faz commit: o chamador faz, junto com o resto da transacção.
#     """
#     agora = datetime.now(timezone.utc)
#     resultado = await session.execute(
#         update(TwoFactorChallenge)
#         .where(
#             TwoFactorChallenge.id == challenge_id,
#             TwoFactorChallenge.usado_as.is_(None),
#             TwoFactorChallenge.expira_as > agora,
#         )
#         .values(usado_as=agora)
#     )
#     return resultado.rowcount == 1
 
 
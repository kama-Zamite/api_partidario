import hashlib
import hmac
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


# [FIX-2FA] Parâmetros da challenge
CHALLENGE_TTL = timedelta(minutes=5)   # curta duração
CHALLENGE_MAX_ATTEMPTS = 5             # tentativas de código por challenge
 
Session = Annotated[AsyncSession, Depends(get_session)]

def _sha256(valor: str | None) -> str:
    return hashlib.sha256((valor or '').encode('utf-8')).hexdigest()
 
 
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
        return xff.split(',')[0].strip()
    return request.client.host if request.client else None
 
 
async def criar_challenge_2fa(
    session: Session,
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
    session: Session,
    token_em_claro: str,
    ip: str | None,
    user_agent: str | None,
) -> TwoFactorChallenge | None:
    """
    [FIX-2FA] Devolve a challenge só se: existir, não estiver usada, não estiver
    expirada, não tiver esgotado tentativas e o IP/User-Agent coincidirem com os
    do login. Qualquer falha -> None (o chamador responde sempre com a mesma
    mensagem genérica, para não dar pistas).
    """
    challenge = await session.scalar(
        select(TwoFactorChallenge).where(
            TwoFactorChallenge.token_hash == _sha256(token_em_claro)
        )
    )
    if not challenge:
        return None
 
    agora = datetime.now(timezone.utc)
    if challenge.usado_as is not None:
        return None
    if challenge.expira_as <= agora:
        return None
    if challenge.tentativas >= CHALLENGE_MAX_ATTEMPTS:
        return None
 
    # Comparações em tempo constante
    if not hmac.compare_digest(challenge.ip_address or '', ip or ''):
        return None
    if not hmac.compare_digest(challenge.user_agent_hash, _sha256(user_agent)):
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
 
 
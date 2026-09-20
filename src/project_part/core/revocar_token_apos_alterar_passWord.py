import uuid
from datetime import datetime, timedelta, timezone
from fastapi import Depends
from typing import Annotated
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
# from project_part.core.secury import create_token
from project_part.db.session import get_session 
from project_part.model.models import UserRefreshToken      # <-- ajusta o import
 

Session = Annotated[AsyncSession, Depends(get_session)]


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
 
 
def versao_senha(password_alterado_em: datetime | None) -> int:
    """
    [SEC-008] Converte password_alterado_em num inteiro (milissegundos desde a
    epoch) usando só aritmética inteira, para dar sempre o mesmo resultado no
    momento de emitir e no momento de validar o token.
    None (senha nunca alterada) -> 0.
    """
    if password_alterado_em is None:
        return 0
    if password_alterado_em.tzinfo is None:
        # Coluna sem timezone: assume UTC (é o que o resto do código grava).
        password_alterado_em = password_alterado_em.replace(tzinfo=timezone.utc)
    return (password_alterado_em - _EPOCH) // timedelta(milliseconds=1)
 
 
def emitir_access_token(user_id: uuid.UUID, password_alterado_em: datetime | None) -> str:
    """
    [SEC-008] Ponto ÚNICO de emissão de access tokens. Recebe valores simples
    (e não o objecto User) para poder ser chamado depois de um commit sem
    disparar lazy-load em objectos expirados.
    """
    from project_part.core.secury import create_token

    return create_token(
        {
            'sub': str(user_id),
            'type': 'access',
            'pwv': versao_senha(password_alterado_em),
        }
    )
 
 
def token_reflete_senha_atual(payload: dict, user) -> bool:
    """
    [SEC-008] True só se a versão de senha do token == versão actual do utilizador.
 
    Token legado (emitido antes deste deploy, sem `pwv`) conta como 0:
      - utilizador que nunca mudou a senha (versão 0) -> continua válido, ninguém
        é deslogado à força no deploy;
      - utilizador que já tinha mudado a senha (versão != 0) -> rejeitado, o
        cliente faz refresh e recebe um token novo já com `pwv`.
    """
    try:
        pwv_token = int(payload.get('pwv', 0))
    except (TypeError, ValueError):
        return False
    return pwv_token == versao_senha(user.password_alterado_em)
 
 
async def revogar_todas_sessoes(
    session: Session,
    user_id: uuid.UUID,
    agora: datetime | None = None,
) -> int:
    """
    [SEC-008] Revoga TODOS os refresh tokens activos do utilizador.
    NÃO faz commit: o chamador faz, para que troca de senha + revogação sejam
    atómicas (ou tudo, ou nada). Devolve o nº de tokens revogados.
    Só toca em revogado=False para preservar o revogado_em original dos que já
    tinham sido revogados antes (auditoria).
    """
    agora = agora or datetime.now(timezone.utc)
    resultado = await session.execute(
        update(UserRefreshToken)
        .where(
            UserRefreshToken.user_id == user_id,
            UserRefreshToken.revogado.is_(False),
        )
        .values(revogado=True, revogado_em=agora)
        .execution_options(synchronize_session=False)
    )
    return resultado.rowcount or 0
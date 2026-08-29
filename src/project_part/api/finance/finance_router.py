import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated
from sqlalchemy.future import select
from project_part.services.notification import disparar_notificacao_usuario
from project_part.model.models import RoleCategoriaNotificacao, User
from project_part.db.session import get_session
import logging



Session = Annotated[AsyncSession, Depends(get_session)]


logger = logging.getLogger(__name__)

finance = APIRouter(prefix="/finance", tags=["Financeiro"])

@finance.post("/quotas/validar/{user_id}", summary="Validar pagamento de quota e notificar militante")
async def validar_pagamento_quota(
    user_id: uuid.UUID,
    session: Session
):
    # ... Lógica do banco de dados para validar a quota do militante ...]

    query = select(User).where(User.id == user_id)
    user_militante = await session.scalar(query)

    if not user_militante:
        logger.error("Militante com ID %s não encontrado.", user_id)
        return {"detail": "Militante não encontrado."}

    logger.info("Validando pagamento de quota para o usuário %s", user_id)
    # A FUNÇÃO ENTRA AQUI:
    # Se o militante tiver desativado o toggle de Quotas, a função ignora silenciosamente.
    await disparar_notificacao_usuario(
        session=session,
        user_id=user_militante.id,  # Certifique-se de que user_militante é um objeto User válido
        titulo="Quota Confirmada!",
        mensagem="A sua contribuição mensal foi registada com sucesso na Plataforma Digital.",
        destinatario="MILITANTE",
        criado_as = datetime.now(timezone.utc),
        categoria=RoleCategoriaNotificacao.QUOTA
    )
    try:
        await session.commit()
        return {"detail": "Quota validada e militante notificado se autorizado."}
    except Exception as e:
        await session.rollback()
        logger.error("Erro ao validar quota para o usuário %s: %s", user_id, str(e))
        return {"detail": "Erro ao validar quota."}

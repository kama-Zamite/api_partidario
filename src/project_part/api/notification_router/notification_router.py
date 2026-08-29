from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Annotated, Optional
import logging
from project_part.core.secury import Get_current_user
from project_part.api.notification_router.schemas import NotificationPreferencesUpdate
from project_part.model.models import User, Notification, RoleCategoriaNotificacao
from project_part.db.session import get_session


Session = Annotated[AsyncSession, Depends(get_session)]

logger = logging.getLogger(__name__)
router_notific = APIRouter(prefix="/notifications", tags=["Notificações"])


@router_notific.get('/preferencias', summary='Obter preferências de notificação')
async def obter_preferencias_notificacao(
    current_user: Get_current_user
):
    """Retorna o estado atual dos toggles de notificação do utilizador."""
    logger.info("Obtendo preferências de notificação para o usuário %s", current_user.id)
    return {
        "notificacoes_gerais": current_user.notificacoes_gerais,
        "comunicados_oficiais": current_user.comunicados_oficiais,
        "eventos_mobilizacoes": current_user.eventos_mobilizacoes,
        "contribuicoes_quota": current_user.contribuicoes_quota,
        "noticias_partido": current_user.noticias_partido,
    }


@router_notific.patch('/preferencias', summary='Atualizar preferências de notificação')
async def atualizar_preferencias_notificacao(
    dados: NotificationPreferencesUpdate,
    session: Session,
    current_user: Get_current_user
):
    """Atualiza atomicamente as preferências de notificação do utilizador."""
    try:
        # Loop para aplicar dinamicamente apenas os campos enviados pelo frontend
        logger.info("Atualizando preferências de notificação para o usuário %s", current_user.id)
        for campo, valor in dados.model_dump(exclude_none=True).items():
            setattr(current_user, campo, valor)
        
        await session.commit()
        await session.refresh(current_user)
        
        return {"detail": "Preferências de notificação atualizadas com sucesso."}
    except Exception as e:
        await session.rollback()
        logger.error("Erro ao atualizar preferências de notificação para o usuário %s: %s", current_user.id, e)
        raise HTTPException(status_code=500, detail="Erro ao salvar preferências.")






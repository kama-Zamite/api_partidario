from http import HTTPStatus
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Form
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
# Ajuste os imports conforme a tua 
from project_part.core.secury import (
    Get_current_user,
    )
from project_part.db.session import get_session
from project_part.model.models import (
    MensagemSuporte,
    RoleMensagemSuporte,
    CategoriaMensagemSuporte,
    Notification,
    NoticiaCategoria,
    AdminScope,
    User,
)
from project_part.services.claudflare_turnfile import verificar_turnstile
from .schemas import (
        MensagemSuporteCreate, 
        MensagemSuporteResponse,
    )

Claudflare_turnfile = Annotated[bool, Depends(verificar_turnstile)]
Session = Annotated[AsyncSession, Depends(get_session)]
logger = logging.getLogger(__name__)

suporte_router = APIRouter(prefix="/suporte", tags=["Suporte"])

admin_id = 1


@suporte_router.post(
    "/mensagem",
    status_code=HTTPStatus.CREATED,
    response_model=MensagemSuporteResponse,
    summary="Enviar mensagem de suporte",
)
async def enviar_mensagem_suporte(
    session: Session,
    current_user: Get_current_user,
    _captcha: Claudflare_turnfile,
    categoria: CategoriaMensagemSuporte = Form(...),
    assunto: str = Form(..., min_length=5, max_length=200),
    mensagem: str = Form(..., min_length=10, max_length=3000),
):
    """
    Recebe uma mensagem de suporte enviada pelo formulário.
    
    - Guarda a mensagem na base de dados
    - (Opcional) dispara e-mail para a equipa de suporte
    """

    try:
        dados_validos = MensagemSuporteCreate(
            categoria=categoria,
            assunto=assunto,
            mensagem=mensagem,
        )
    except Exception as err:
        logger.error("Erro de validação dos dados do formulário: %s", err)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dados inválidos fornecidos. Verifique os campos e tente novamente.",
        )


    query_admin_regional = (
        select(User)
        .join(AdminScope, AdminScope.user_id == User.id)
        .where(
            User.role_id == admin_id,
            (AdminScope.municipio_id == current_user.municipio_id) | 
            (AdminScope.provincia_id == current_user.provincia_id)
        )
        .limit(1)
    )
    admin_alvo = await session.scalar(query_admin_regional)

    if not admin_alvo:
        logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
        query_admin_geral = select(User).where(User.role_id == admin_id).limit(1)
        admin_alvo = await session.scalar(query_admin_geral)

    if not admin_alvo:
        logger.critical("Falha crítica: Nenhum administrador cadastrado no sistema inteiro.")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail="Nenhum administrador disponível para processar a solicitação no momento."
        )

    try:
        nova_mensagem = MensagemSuporte(
            categoria=dados_validos.categoria,
            assunto=dados_validos.assunto,
            mensagem=dados_validos.mensagem,
            admin_id=admin_alvo.id,
            user_id=current_user.id,
            status=RoleMensagemSuporte.PENDENTE.value,
        )

        session.add(nova_mensagem)
        await session.commit()
        await session.refresh(nova_mensagem)

        logger.info("Nova mensagem de suporte recebida: %s", nova_mensagem.id)
        # Opcional: enviar e-mail para suporte@unita.ao
        # await enviar_email_suporte(nova_mensagem)

        return MensagemSuporteResponse(
            id=nova_mensagem.id,
            mensagem="Mensagem enviada com sucesso. A nossa equipa responderá de segunda a sábado."
        )

    except Exception as err:
        await session.rollback()
        logger.error("Erro ao gravar mensagem de suporte: %s", err)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível enviar a mensagem. Tente novamente mais tarde.",
        )
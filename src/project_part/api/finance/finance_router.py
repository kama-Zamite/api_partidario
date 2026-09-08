from datetime import datetime, timezone
from http import HTTPStatus
from decimal import Decimal

from typing import Any, Optional, Annotated
import logging
from fastapi import APIRouter, Request, Query, HTTPException, Depends

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

# from project_part.model.finance import (
#     DonationStatusEnum,
#     Doacao,
#     TipoMovimentoEnum,
#     AcaoMovimentoEnum,
#     PagamentoQuota,
#     QuotaStatusEnum,
    
# )
from project_part.core.setting import settings
from project_part.model.models import (
    CadastrarComo,
    RoleCategoriaNotificacao,
    Notification,
    User,
    AdminScope,
    DonationStatusEnum,
    Doacao,
    TipoMovimentoEnum,
    AcaoMovimentoEnum,
    PagamentoQuota,
    QuotaStatusEnum,
    MetodoPagamentoEnum,
)
from project_part.core.secury import Get_current_user
from project_part.db.session import get_session
from project_part.services.finance_audit import registar_movimento
from .schemas import (
    DoacaoCreate,
    QuotaCreate,

) 

Session = Annotated[AsyncSession, Depends(get_session)]

logger = logging.getLogger(__name__)
finance = APIRouter(prefix='/finance', tags=['Financeiro'])

@finance.post('/doacao', status_code=HTTPStatus.CREATED)
async def criar_doacao(
    request: Request,
    body: DoacaoCreate,
    session: Session,
    current_user: Get_current_user,
):
    doacao = Doacao(
        user_id=current_user.id,
        quantia=body.quantia,
        moeda='AOA',
        metodo_pagamento=body.metodo_pagamento,
        referencia=body.referencia.strip() if body.referencia else None,
        id_transacao=body.id_transacao.strip() if body.id_transacao else None,
        observacao=body.observacao,
        status=DonationStatusEnum.PENDING,
    )
    session.add(doacao)
    await session.flush()

    await registar_movimento(
        session,
        tipo=TipoMovimentoEnum.DOACAO,
        origem_id=doacao.id,
        user_id=current_user.id,
        quantia=doacao.quantia,
        moeda=doacao.moeda,
        acao=AcaoMovimentoEnum.CRIADA,
        status_anterior=None,
        status_novo=DonationStatusEnum.PENDING.value,
        ator_id=current_user.id,
        detalhe={
            'metodo_pagamento': doacao.metodo_pagamento.value,
            'referencia': doacao.referencia,
        },
    )

    query_admin_regional = (
        select(User)
        .join(AdminScope, AdminScope.user_id == User.id)
        .where(
            User.role_id == settings.ADMIN_ROLE_ID,
            (AdminScope.municipio_id == current_user.municipio_id) | 
            (AdminScope.provincia_id == current_user.provincia_id)
        )
        .limit(1)
    )
    admin_alvo = await session.scalar(query_admin_regional)
    
    if not admin_alvo:
        logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
        query_admin_geral = select(User).where(User.role_id == settings.ADMIN_ROLE_ID).limit(1)
        admin_alvo = await session.scalar(query_admin_geral)

    # --- CORREÇÃO DO BUG AQUI ---
    # Usamos a foreign key direta 'role_id' do current_user em vez da relação de objeto 'role'
    if current_user.role_id == settings.ADMIN_ROLE_ID or current_user.role_id == settings.ROLE_MILITANTE_ID:
        tipo_user = 'militante'
    else:
        tipo_user = 'simpatizante'
    
    if admin_alvo:
        notificacao_admin = Notification(
            admin_id=admin_alvo.id,
            user_id=current_user.id,
            titulo="Doacao",
            mensagem=f"O {tipo_user} {current_user.nome_completo} (Nº {current_user.militante_numero or 'Pendente'}) fez uma doacao.",
            destinatario="ADMIN",
            categoria=RoleCategoriaNotificacao.DOACAO
        )
        session.add(notificacao_admin)
    
    try:
        await session.commit()
        # O session.refresh foi ELIMINADO daqui, pois não é necessário para o dicionário de retorno.
    except IntegrityError:
        await session.rollback()
        raise HTTPException(HTTPStatus.CONFLICT, detail='Referência ou ID de transação já existe.')

    return {
        "msg": "doacao enviada com sucesso, aguarde a aprovação do admin.",
    }



@finance.post('/quota', status_code=HTTPStatus.CREATED)
# @limiter.limit('10/minute')
async def criar_pagamento_quota(
    request: Request,
    quantia: Decimal,
    metodo_pagamento: MetodoPagamentoEnum,
    referencia: str | None,
    id_transacao: str | None,
    meses_pagar: int,
    observacao: str | None,
    session: Session,
    current_user: Get_current_user,
):
    if current_user.cadastrar_militante != CadastrarComo.MILITANTE:
        raise HTTPException(
            HTTPStatus.FORBIDDEN,
            detail='Apenas militantes pagam quota.'
            )


    try:
        logger.info("Criando pagamento de quota para o usuário %s", current_user.id)
        body = QuotaCreate(
            quantia=quantia,
            metodo_pagamento=metodo_pagamento,
            referencia=referencia,
            id_transacao=id_transacao,
            meses_pagar=meses_pagar,
            observacao=observacao,
        )
    except ValueError as e:
        logger.error("Erro de validação ao criar pagamento de quota: %s", str(e))
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=str(e)
        )

    
    query_quota = (
        select(PagamentoQuota)
        .where(
            PagamentoQuota.user_id == current_user.id,
            PagamentoQuota.status == QuotaStatusEnum.PENDING
        )
    )

    pagamento_pendente = await session.scalar(query_quota)
    if pagamento_pendente:
        logger.warning("Usuário %s já possui um pagamento de quota pendente.", current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Você já possui um pagamento de quota pendente.'
        )

    quota_periodo = query_quota.where(PagamentoQuota.periodo == current_user.id)

    logger.info("Calculando o valor total da quota para o usuário %s", current_user.id)
    periodo_atual = datetime.now(timezone.utc).strftime('%Y-%m')
    valor_total_quota = body.quantia * body.meses_pagar
    pagamento = PagamentoQuota(
        user_id=current_user.id,
        quantia=valor_total_quota,
        moeda='AOA',
        periodo=periodo_atual,
        metodo_pagamento=body.metodo_pagamento,
        referencia=body.referencia.strip() if body.referencia else None,
        id_transacao=body.id_transacao.strip() if body.id_transacao else None,
        observacao=body.observacao,
        status=QuotaStatusEnum.PENDING,
    )
    try:
        logger.info("Adicionando pagamento de quota à sessão para o usuário %s", current_user.id)
        session.add(pagamento)
        await session.flush()
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Erro ao armazenar o pagamento de quota'
        )

    await registar_movimento(
        session,
        tipo=TipoMovimentoEnum.QUOTA,
        origem_id=pagamento.id,
        user_id=current_user.id,
        quantia=pagamento.quantia,
        moeda=pagamento.moeda,
        acao=AcaoMovimentoEnum.CRIADA,
        status_novo=QuotaStatusEnum.PENDING.value,
        ator_id=current_user.id,
        detalhe={'periodo': pagamento.periodo, 'metodo': pagamento.metodo_pagamento.value},
    )

    # try:
    #     await session.commit()
    # except Exception as e:
    #     await session.rollback()
    #     logger.error("Erro ao salvar solicitação e notificação: %s", str(e))
    #     raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Erro ao salvar dados no banco.")
    
    query_admin_regional = (
            select(User)
            .join(AdminScope, AdminScope.user_id == User.id)
            .where(
                User.role_id == settings.ADMIN_ROLE_ID,
                (AdminScope.municipio_id == current_user.municipio_id) | 
                (AdminScope.provincia_id == current_user.provincia_id)
            )
            .limit(1)
        )
    admin_alvo = await session.scalar(query_admin_regional)
    
    if not admin_alvo:
        logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
        query_admin_geral = select(User).where(User.role_id == settings.ADMIN_ROLE_ID).limit(1)
        admin_alvo = await session.scalar(query_admin_geral)

    notificacao_admin = Notification(
        admin_id=admin_alvo.id,
        user_id = current_user.id,
        titulo="Pagamento de Quota",
        mensagem=f"O militante {current_user.nome_completo} (Nº {current_user.militante_numero or 'Pendente'}) fez um pagamento de quota.",
        destinatario="ADMIN",
        categoria=RoleCategoriaNotificacao.QUOTA
        )
    
    session.add(notificacao_admin)
    try:
        await session.commit()
        await session.refresh(pagamento)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(HTTPStatus.CONFLICT, detail='Referência ou ID de transação já existe.')


    return {
        "msg": "Pagamento de quota enviado com sucesso, aguarde a aprovação do admin.",
    }









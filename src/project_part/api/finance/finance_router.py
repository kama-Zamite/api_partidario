from datetime import datetime, timezone
from http import HTTPStatus
from decimal import Decimal

from typing import Any, Optional, Annotated
import logging
from fastapi import APIRouter, Request, Query, HTTPException, Depends, status
from project_part.core.rate_limit import limiter
from dateutil.relativedelta import relativedelta  # Garante manipulação exata de meses
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from project_part.core.rate_limit import limiter
from project_part.services.claudflare_turnfile import verificar_turnstile


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

Claudflare_turnfile = Annotated[bool, Depends(verificar_turnstile)]


Session = Annotated[AsyncSession, Depends(get_session)]

logger = logging.getLogger(__name__)
finance = APIRouter(prefix='/finance', tags=['Financeiro'])

QUOTA_PENDENTE_UQ = 'uq_pagamento_quota_user_pending'
DETAIL_QUOTA_PENDENTE = 'Você já possui um pagamento de quota pendente aguardando aprovação.'
MAX_MESES_PAGAR = 120

@finance.post('/doacao', status_code=HTTPStatus.CREATED)
async def criar_doacao(
    request: Request,
    body: DoacaoCreate,
    session: Session,
    _captcha: Claudflare_turnfile,
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






@finance.post('/doacao/anonimo', status_code=HTTPStatus.CREATED)
@limiter.limit('5/minute')
async def criar_doacao_anonimo(
    request: Request,
    body: DoacaoCreate,
    session: Session,
    _captcha: Claudflare_turnfile

):
    """Doação sem conta. Notifica apenas superadmin."""
    doacao = Doacao(
        user_id=None,
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
        user_id=None,
        quantia=doacao.quantia,
        moeda=doacao.moeda,
        acao=AcaoMovimentoEnum.CRIADA,
        status_anterior=None,
        status_novo=DonationStatusEnum.PENDING.value,
        ator_id=None,
        detalhe={
            'metodo_pagamento': doacao.metodo_pagamento.value,
            'referencia': doacao.referencia,
            'anonimo': True,
        },
    )

    # Só superadmin (sem território)
    superadmin_ids = (
        await session.scalars(
            select(User.id)
            .join(AdminScope, AdminScope.user_id == User.id)
            .where(
                User.role_id == settings.ADMIN_ROLE_ID,
                User.ativo.is_(True),
                AdminScope.provincia_id.is_(None),
                AdminScope.municipio_id.is_(None),
            )
        )
    ).all()

    if not superadmin_ids:
        logger.warning(
            'Doação anónima %s criada sem superadmin para notificar',
            doacao.id,
        )
    else:
        for admin_id in superadmin_ids:
            session.add(
                Notification(
                    admin_id=admin_id,
                    user_id=None,
                    titulo='Doação anónima',
                    mensagem=(
                        f'Recebida doação anónima de {doacao.quantia} AOA '
                        f'via {doacao.metodo_pagamento.value}'
                        + (
                            f' (ref: {doacao.referencia}).'
                            if doacao.referencia
                            else '.'
                        )
                        + ' Aguarda aprovação.'
                    ),
                    destinatario='ADMIN',
                    categoria=RoleCategoriaNotificacao.DOACAO,
                )
            )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            HTTPStatus.CONFLICT,
            detail='Referência ou ID de transação já existe.',
        )

    logger.info('Doação anónima %s criada (PENDING)', doacao.id)
    return {
        'msg': 'Doação enviada com sucesso, aguarde a aprovação do admin.',
        'doacao_id': str(doacao.id),
    }

# @finance.post('/quota', status_code=HTTPStatus.CREATED)
# # @limiter.limit('5/minute')
# async def criar_pagamento_quota(
#     request: Request,
#     quantia: Decimal,
#     metodo_pagamento: MetodoPagamentoEnum,
#     referencia: str | None,
#     id_transacao: str | None,
#     meses_pagar: int,
#     observacao: str | None,
#     session: Session,
#     current_user: Get_current_user,
# ):
#     if current_user.cadastrar_militante != CadastrarComo.MILITANTE:
#         raise HTTPException(
#             HTTPStatus.FORBIDDEN,
#             detail='Apenas militantes pagam quota.'
#         )

#     if meses_pagar < 1:
#         raise HTTPException(
#             HTTPStatus.BAD_REQUEST,
#             detail='A quantidade de meses a pagar deve ser de pelo menos 1 mês.'
#         )

#     get_referencia = referencia if referencia else current_user.telefone

#     try:
#         logger.info("Criando pagamento de quota para o usuário %s", current_user.id)
#         body = QuotaCreate(
#             quantia=quantia,
#             metodo_pagamento=metodo_pagamento,
#             referencia=get_referencia,
#             id_transacao=id_transacao,
#             meses_pagar=meses_pagar,
#             observacao=observacao,
#         )
#     except ValueError as e:
#         logger.error("Erro de validação ao criar pagamento de quota: %s", str(e))
#         raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e))

#     # 1. Bloqueia se houver algum pagamento PENDING
#     query_pendente = (
#         select(PagamentoQuota)
#         .where(
#             PagamentoQuota.user_id == current_user.id,
#             PagamentoQuota.status == QuotaStatusEnum.PENDING
#         )
#     )
#     if await session.scalar(query_pendente):
#         logger.warning("Usuário %s já possui um pagamento de quota pendente.", current_user.id)
#         raise HTTPException(
#             status_code=HTTPStatus.CONFLICT,
#             detail='Você já possui um pagamento de quota pendente.'
#         )

#     # 2. Descobre o ponto inicial com base na última quota APPROVED
#     query_ultima_quota = (
#         select(PagamentoQuota)
#         .where(
#             PagamentoQuota.user_id == current_user.id,
#             PagamentoQuota.status == QuotaStatusEnum.APPROVED
#         )
#         .order_by(PagamentoQuota.periodo.desc(), PagamentoQuota.id.desc())
#         .limit(1)
#     )
#     ultima_quota = await session.scalar(query_ultima_quota)

#     if ultima_quota and ultima_quota.periodo:
#         try:
#             # Pega o mês inicial da última quota
#             data_referencia = datetime.strptime(ultima_quota.periodo, "%Y-%m").date()
#             # O próximo pagamento deve começar no mês seguinte ao FIM do período anterior
#             # Fim do período anterior = periodo_inicio + meses_pagar
#             meses_a_adicionar = ultima_quota.meses_pagar if ultima_quota.meses_pagar else 1
#             data_inicio = data_referencia + relativedelta(months=meses_a_adicionar)
#         except Exception:
#             data_inicio = datetime.now(timezone.utc).date()
#     else:
#         # Se for o primeiro pagamento da história do utilizador
#         data_inicio = datetime.now(timezone.utc).date()

#     # Formata como "YYYY-MM" (Respeita o String(7) da sua coluna)
#     periodo_inicial_str = data_inicio.strftime('%Y-%m')

#     # 3. Calcula o valor total proporcional aos meses desejados
#     valor_total_quota = body.quantia * body.meses_pagar

#     pagamento = PagamentoQuota(
#         user_id=current_user.id,
#         quantia=valor_total_quota,
#         moeda='AOA',
#         meses_pagar=body.meses_pagar,  # Preenche a sua coluna da tabela
#         periodo=periodo_inicial_str,    # Salva apenas o mês de largada da cobrança
#         metodo_pagamento=body.metodo_pagamento,
#         referencia=body.referencia.strip() if body.referencia else None,
#         id_transacao=body.id_transacao.strip() if body.id_transacao else None,
#         observacao=body.observacao,
#         status=QuotaStatusEnum.PENDING,
#     )

#     try:
#         logger.info("Adicionando pagamento de quota à sessão para o usuário %s", current_user.id)
#         session.add(pagamento)
#         await session.flush()
#     except Exception as e:
#         await session.rollback()
#         logger.error("Erro no flush: %s", e)
#         raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail='Erro ao armazenar o pagamento de quota')

#     # Registo de histórico de movimentos
#     await registar_movimento(
#         session,
#         tipo=TipoMovimentoEnum.QUOTA,
#         origem_id=pagamento.id,
#         user_id=current_user.id,
#         quantia=pagamento.quantia,
#         moeda=pagamento.moeda,
#         acao=AcaoMovimentoEnum.CRIADA,
#         status_novo=QuotaStatusEnum.PENDING.value,
#         ator_id=current_user.id,
#         detalhe={'periodo_inicial': pagamento.periodo, 'meses_pagar': pagamento.meses_pagar},
#     )

#     # 4. Envio de Notificação para Administradores
#     query_admin_regional = (
#         select(User)
#         .join(AdminScope, AdminScope.user_id == User.id)
#         .where(
#             User.role_id == settings.ADMIN_ROLE_ID,
#             (AdminScope.municipio_id == current_user.municipio_id) | 
#             (AdminScope.provincia_id == current_user.provincia_id)
#         )
#         .limit(1)
#     )
#     admin_alvo = await session.scalar(query_admin_regional)
    
#     if not admin_alvo:
#         logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
#         query_admin_geral = select(User).where(User.role_id == settings.ADMIN_ROLE_ID).limit(1)
#         admin_alvo = await session.scalar(query_admin_geral)

#     notificacao_admin = Notification(
#         admin_id=admin_alvo.id,
#         user_id=current_user.id,
#         titulo='Pagamento de Quota',
#         mensagem=(
#             f'O militante {current_user.nome_completo} solicitou pagamento de '
#             f'{body.meses_pagar} meses a partir de {periodo_inicial_str}.'
#         ),
#         destinatario='ADMIN',
#         categoria=RoleCategoriaNotificacao.QUOTA,
#     )
    
#     session.add(notificacao_admin)
#     try:
#         await session.commit()
#         await session.refresh(pagamento)
#     except IntegrityError:
#         await session.rollback()
#         raise HTTPException(HTTPStatus.CONFLICT, detail='Referência ou ID de transação já existe.')

#     return {
#         "msg": "Pagamento de quota enviado com sucesso, aguarde a aprovação do admin.",
#     }




def _erro_integridade_quota(exc: IntegrityError, user_id) -> HTTPException:
    msg = str(getattr(exc, 'orig', exc))
    if QUOTA_PENDENTE_UQ in msg:
        logger.warning('Race condition contida pelo banco: quota PENDING duplicada (user %s)', user_id)
        return HTTPException(status_code=HTTPStatus.CONFLICT, detail=DETAIL_QUOTA_PENDENTE)
    if 'unique' in msg.lower() or 'duplicate' in msg.lower():
        logger.warning('Violação de unicidade em pagamento de quota (user %s): %s', user_id, msg)
        # [HARDENING] No modelo, só `id_transacao` tem unique=True (`referencia` não),
        #             por isso a mensagem já não menciona a referência.
        return HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='ID de transação já existe.',
        )
    # [HARDENING] Antes qualquer IntegrityError virava "referência já existe",
    #             mesmo sendo FK / NOT NULL. Agora só é dito quando é mesmo unicidade.
    logger.error('IntegrityError inesperado em pagamento de quota (user %s): %s', user_id, msg)
    return HTTPException(
        status_code=HTTPStatus.BAD_REQUEST,
        detail='Não foi possível registar o pagamento de quota.',
    )



@finance.post('/quota', status_code=HTTPStatus.CREATED)
@limiter.limit('5/minute')
async def criar_pagamento_quota(
    request: Request,
    quantia: Decimal,
    metodo_pagamento: MetodoPagamentoEnum,
    _captcha: Claudflare_turnfile,
    referencia: str | None,
    id_transacao: str | None,
    meses_pagar: int,
    observacao: str | None,
    session: Session,
    current_user: Get_current_user,
):
    user_id = current_user.id

    if current_user.cadastrar_militante != CadastrarComo.MILITANTE:
        raise HTTPException(
            HTTPStatus.FORBIDDEN,
            detail='Apenas militantes pagam quota.'
        )

    if meses_pagar < 1:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            detail='A quantidade de meses a pagar deve ser de pelo menos 1 mês.'
        )

    if meses_pagar > MAX_MESES_PAGAR:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            detail=f'A quantidade de meses a pagar não pode exceder {MAX_MESES_PAGAR}.'
        )

    if not quantia.is_finite() or quantia <= 0:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            detail='A quantia deve ser um valor positivo.'
        )
    get_referencia = referencia if referencia else current_user.telefone

    try:
        logger.info("Criando pagamento de quota para o usuário %s", current_user.id)
        body = QuotaCreate(
            quantia=quantia,
            metodo_pagamento=metodo_pagamento,
            referencia=get_referencia,
            id_transacao=id_transacao,
            meses_pagar=meses_pagar,
            observacao=observacao,
        )
    except ValueError as e:
        logger.error("Erro de validação ao criar pagamento de quota: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 1. Bloqueia se houver algum pagamento PENDING
    query_pendente = (
        select(PagamentoQuota.id)
        .where(
            PagamentoQuota.user_id == user_id,
            PagamentoQuota.status == QuotaStatusEnum.PENDING
        )
        .limit(1)
    )
    if await session.scalar(query_pendente) is not None:
        logger.warning("Usuário %s já possui um pagamento de quota pendente.", user_id)
        logger.warning("Usuário %s já possui um pagamento de quota pendente.", user_id)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=DETAIL_QUOTA_PENDENTE
        )

    # 2. Descobre o ponto inicial olhando DIRETAMENTE para a expiração do perfil
    data_atual = datetime.now(timezone.utc).date()

    if current_user.data_expiracao_quota:
       logger.info("Usuário %s tem data de expiração de quota: %s", user_id, current_user.data_expiracao_quota)
        # Em dia: começa no mês seguinte à expiração.
        # Expirado: força a regularização a partir do mês em atraso (mesma conta).
       data_inicio = current_user.data_expiracao_quota + relativedelta(months=1)
    else:
        # Se nunca pagou uma quota na vida, começa a contar a partir do mês atual
        data_inicio = data_atual

    # Formata como "YYYY-MM" para o limite String(7) da sua tabela
    periodo_inicial_str = data_inicio.strftime('%Y-%m')

    # 3. Calcula o valor total proporcional
    valor_bruto  = body.quantia * body.meses_pagar
    if valor_bruto >= Decimal('10000000000000'):  # 10^13 = limite de Numeric(15,2)
        logger.warning("Valor total da quota fora do intervalo permitido para o usuário %s: %s", user_id, valor_bruto)
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            detail='Valor total da quota fora do intervalo permitido.'
        )
    valor_total_quota = valor_bruto.quantize(Decimal('0.01'))

    if valor_total_quota <= 0:
        raise HTTPException(
            HTTPStatus.BAD_REQUEST,
            detail='Valor total da quota fora do intervalo permitido.'
        )
    
    pagamento = PagamentoQuota(
        user_id=user_id,
        quantia=valor_total_quota,
        moeda='AOA',
        meses_pagar=body.meses_pagar,
        periodo=periodo_inicial_str, 
        metodo_pagamento=body.metodo_pagamento,
        referencia=(body.referencia or '').strip() or None,
        id_transacao=(body.id_transacao or '').strip() or None,
        observacao=body.observacao,
        status=QuotaStatusEnum.PENDING,
    )

    try:
        logger.info("Adicionando pagamento de quota à sessão para o usuário %s", current_user.id)
        session.add(pagamento)
        await session.flush()
    except IntegrityError as e:
            logger.warning("IntegrityError ao criar pagamento de quota para o usuário %s: %s", user_id, e)
            await session.rollback()
            raise _erro_integridade_quota(e, user_id)
    except Exception as e:
        await session.rollback()
        # [HARDENING] logger.exception guarda o traceback; falha inesperada = 500 (era 400).
        logger.exception("Erro no flush ao criar pagamento de quota (user %s): %s", user_id, e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Erro ao armazenar o pagamento de quota'
       )
    pagamento_id = pagamento.id  # [HARDENING] guardado antes do commit (objecto expira)
    # Registo de histórico de movimentos
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
        detalhe={'periodo_inicial': pagamento.periodo, 'meses_pagar': pagamento.meses_pagar},
    )

    # 4. Envio de Notificação para Administradores
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

    if admin_alvo:
        notificacao_admin = Notification(
            admin_id=admin_alvo.id,
            user_id=current_user.id,
            titulo="Pagamento de Quota",
            mensagem=f"O militante {current_user.nome_completo} solicitou pagamento de {body.meses_pagar} meses iniciando em {periodo_inicial_str}.",
            destinatario="ADMIN",
            categoria=RoleCategoriaNotificacao.QUOTA
        )
    
        session.add(notificacao_admin)
    else:
        logger.error(
            "Nenhum administrador encontrado para notificar o pagamento de quota %s (user %s)",
            pagamento_id, user_id,
        )

    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise _erro_integridade_quota(e, user_id)
    except Exception as e:
        await session.rollback()
        logger.exception("Erro no commit do pagamento de quota (user %s): %s", user_id, e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Erro ao armazenar o pagamento de quota'
        )
    logger.info("Pagamento de quota %s finalizado com sucesso para o usuário %s", pagamento_id, user_id)
    return {
        "msg": "Pagamento de quota enviado com sucesso, aguarde a aprovação do admin.",
    }






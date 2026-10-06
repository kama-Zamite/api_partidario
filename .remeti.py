# project_part/core/jobs.py

import logging
from datetime import datetime, timezone, timedelta, date

# from sqlalchemy import select, and_, or_, Date 
from sqlalchemy import select, or_, Date, cast, exists, and_, extract

from project_part.core.distributed_lock import with_distributed_lock
from project_part.model.models import (
    User,
    PagamentoQuota,
    Notification,
    RoleCategoriaNotificacao,
    CadastrarComo,
    QuotaStatusEnum,
)
from project_part.services.email_service.job_emails import (
    enviar_email_ativar_quota_async,
    enviar_email_quota_vencida_async
)

logger = logging.getLogger(__name__)

LOCK_KEY_QUOTAS = 'lock:job:verificar_quotas_vencidas'
LOCK_TTL_SECONDS = 600


async def _verificar_e_notificar_quotas_impl(session_factory):
    hoje = datetime.now(timezone.utc).date()

    async with session_factory() as session:
        logger.info('Job mensal quotas — Executando validações para o dia: %s', hoje)

        # ── 1) Militantes em atraso (quota já expirou) ───────────
        query_atraso = select(User).where(
            User.ativo.is_(True),
            User.cadastrar_militante == CadastrarComo.MILITANTE,
            User.data_expiracao_quota.isnot(None),
            User.data_expiracao_quota < hoje,
            or_(
                User.notificado_quota_atraso_em.is_(None),
                and_(
                    extract('month', User.notificado_quota_atraso_em) != hoje.month,
                    extract('year', User.notificado_quota_atraso_em) == hoje.year
                ),
                extract('year', User.notificado_quota_atraso_em) < hoje.year
            ),
        )

        vencidos = (await session.scalars(query_atraso)).all()

        for user in vencidos:
            # Salvaguarda de memória para o mês civil corrente
            if user.notificado_quota_atraso_em and \
               user.notificado_quota_atraso_em.month == hoje.month and \
               user.notificado_quota_atraso_em.year == hoje.year:
                continue

            session.add(
                Notification(
                    user_id=user.id,
                    titulo='Quota em atraso',
                    mensagem=(
                        f'Olá {user.nome_completo}, a sua quota encontra-se vencida. '
                        f'Regularize o pagamento para manter os benefícios de militante ativos.'
                    ),
                    categoria=RoleCategoriaNotificacao.QUOTA,
                )
            )
            user.notificado_quota_atraso_em = hoje
            logger.info('Notificação atraso → %s', user.email)

            # ── DISPARO DO EMAIL DE QUOTA VENCIDA ──
            vencimento_formatado = user.data_expiracao_quota.strftime("%d/%m/%Y") if hasattr(user.data_expiracao_quota, "strftime") else str(user.data_expiracao_quota)
            await enviar_email_quota_vencida_async(
                nome_completo=user.nome_completo,
                email_destinatario=user.email,
                data_vencimento=vencimento_formatado
            )

        # ── 2) Novos militantes sem nunca ter quota (Otimizado sem N+1) ─────
        # limite_novos = hoje - timedelta(days=3)
        # limite_dt = datetime.combine(limite_novos, datetime.min.time(), tzinfo=timezone.utc)

        # # Subquery para verificar se o utilizador possui QUALQUER quota PENDING ou APPROVED
        # possui_quota_ativa_ou_pendente = exists().where(
        #     and_(
        #         PagamentoQuota.user_id == User.id,
        #         PagamentoQuota.status.in_([QuotaStatusEnum.PENDING, QuotaStatusEnum.APPROVED])
        #     )
        # )

        # query_novos = select(User).where(
        #     User.ativo.is_(True),
        #     User.cadastrar_militante == CadastrarComo.MILITANTE,
        #     User.data_expiracao_quota.is_(None),
        #     User.criado_em <= limite_dt,
        #     # Correção do cast nativo do SQLAlchemy
        #     User.notificado_quota_atraso_em.is_(None),
        #     # or_(
        #     #     and_(
        #     #         extract('month', User.notificado_quota_atraso_em) != hoje.month,
        #     #         extract('year', User.notificado_quota_atraso_em) == hoje.year
        #     #     ),
        #     #     extract('year', User.notificado_quota_atraso_em) < hoje.year
        #     # ),
        #     # Evita o loop N+1 trazendo apenas quem realmente não tem quotas no banco
        #     ~possui_quota_ativa_ou_pendente
        # )

        # novos = (await session.scalars(query_novos)).all()

        # for user in novos:
        #     # Salvaguarda de mês civil atual na memória
        #     if user.notificado_quota_atraso_em and \
        #        user.notificado_quota_atraso_em.month == hoje.month and \
        #        user.notificado_quota_atraso_em.year == hoje.year:
        #         continue

        #     session.add(
        #         Notification(
        #             user_id=user.id,
        #             titulo='Ative as suas Quotas',
        #             mensagem=(
        #                 f'Olá {user.nome_completo}! Efetue o pagamento da primeira quota '
        #                 f'para ativar os benefícios de militante.'
        #             ),
        #             categoria=RoleCategoriaNotificacao.QUOTA,
        #         )
        #     )
        #     user.notificado_quota_atraso_em = hoje
        #     logger.info('Notificação novo sem quota → %s', user.email)

        #     await enviar_email_ativar_quota_async(
        #         nome_completo=user.nome_completo,
        #         email_destinatario=user.email
        #     )
        try:
            from project_part.db.audit_helper import processar_auditoria_sessao
            await processar_auditoria_sessao(session)
            await session.commit()
            logger.info(
                'Job quotas concluído com sucesso. Processados: %s vencidos.',
                len(vencidos),
            )
        except Exception as e:
            await session.rollback()
            logger.error('Erro fatal no job de quotas: %s', e)
            raise



async def verificar_e_notificar_quotas_vencidas(session_factory, redis):
    async def _run():
        await _verificar_e_notificar_quotas_impl(session_factory)

    ran = await with_distributed_lock(
        redis,
        key=LOCK_KEY_QUOTAS,
        ttl_seconds=LOCK_TTL_SECONDS,
        coro_factory=_run,
    )
    if not ran:
        logger.info('Job quotas ignorado (lock Redis).')


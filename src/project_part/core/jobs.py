# project_part/core/jobs.py

import logging
from datetime import datetime, timezone, timedelta, date

from sqlalchemy import select, and_, or_

from project_part.core.distributed_lock import with_distributed_lock
from project_part.model.models import (
    User,
    PagamentoQuota,
    Notification,
    RoleCategoriaNotificacao,
    CadastrarComo,
    QuotaStatusEnum,
)
logger = logging.getLogger(__name__)

LOCK_KEY_QUOTAS = 'lock:job:verificar_quotas_vencidas'
LOCK_TTL_SECONDS = 600


async def _verificar_e_notificar_quotas_impl(session_factory):
    hoje = datetime.now(timezone.utc).date()

    async with session_factory() as session:
        # ── 1) Militantes em atraso (quota já expirou) ───────────
        # Critérios:
        # - data_expiracao_quota < hoje  (está vencida)
        # - ainda não notificados depois desta expiração
        #   (notificado_quota_atraso_em IS NULL
        #    OR notificado_quota_atraso_em < data_expiracao_quota
        #    OR notificado no mês civil anterior — opcional)
        logger.info('Job mensal quotas (dia 10) — em atraso até %s', hoje)

        query_atraso = select(User).where(
            User.ativo.is_(True),
            User.cadastrar_militante == CadastrarComo.MILITANTE,
            User.data_expiracao_quota.isnot(None),
            User.data_expiracao_quota < hoje,
            or_(
                User.notificado_quota_atraso_em.is_(None),
                User.notificado_quota_atraso_em < User.data_expiracao_quota,
            ),
        )

        vencidos = (await session.scalars(query_atraso)).all()

        for user in vencidos:
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
            # marca para não repetir no próximo dia 10 enquanto a expiração não mudar
            user.notificado_quota_atraso_em = hoje
            logger.info('Notificação atraso → %s', user.email)

        # ── 2) Novos militantes sem nunca ter quota aprovada ─────
        limite_novos = hoje - timedelta(days=3)
        limite_dt = datetime.combine(
            limite_novos, datetime.min.time(), tzinfo=timezone.utc
        )

        novos = (
            await session.scalars(
                select(User).where(
                    User.ativo.is_(True),
                    User.cadastrar_militante == CadastrarComo.MILITANTE,
                    User.data_expiracao_quota.is_(None),
                    User.criado_em <= limite_dt,
                    or_(
                        User.notificado_quota_atraso_em.is_(None),
                        # reutiliza a flag: só 1 aviso de “ative a quota”
                        User.notificado_quota_atraso_em < User.criado_em.cast(type_=None),  # evite se complicar
                    ),
                )
            )
        ).all()

        for user in novos:
            # se já tiver flag de notificação recente no mesmo mês, salta
            if user.notificado_quota_atraso_em and user.notificado_quota_atraso_em.month == hoje.month and user.notificado_quota_atraso_em.year == hoje.year:
                continue

            tem_pendente = await session.scalar(
                select(PagamentoQuota.id).where(
                    PagamentoQuota.user_id == user.id,
                    PagamentoQuota.status == QuotaStatusEnum.PENDING,
                ).limit(1)
            )
            if tem_pendente:
                continue

            tem_aprovada = await session.scalar(
                select(PagamentoQuota.id).where(
                    PagamentoQuota.user_id == user.id,
                    PagamentoQuota.status == QuotaStatusEnum.APPROVED,
                ).limit(1)
            )
            if tem_aprovada:
                continue

            session.add(
                Notification(
                    user_id=user.id,
                    titulo='Ative as suas Quotas',
                    mensagem=(
                        f'Olá {user.nome_completo}! Efetue o pagamento da primeira quota '
                        f'para ativar os benefícios de militante.'
                    ),
                    categoria=RoleCategoriaNotificacao.QUOTA,
                )
            )
            user.notificado_quota_atraso_em = hoje
            logger.info('Notificação novo sem quota → %s', user.email)

        try:
            await session.commit()
            logger.info(
                'Job quotas concluído: %s em atraso, processados novos',
                len(vencidos),
            )
        except Exception as e:
            await session.rollback()
            logger.error('Erro no job de quotas: %s', e)
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
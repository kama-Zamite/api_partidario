# project_part/core/jobs.py
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from project_part.model.models import User, PagamentoQuota, Notification
from project_part.model.models import RoleCategoriaNotificacao, QuotaStatusEnum

logger = logging.getLogger(__name__)

async def verificar_e_notificar_quotas_vencidas(session_factory):
    """
    Roda todas as noites para verificar contas vencidas e novos membros sem quotas.
    """
    hoje = datetime.now(timezone.utc).date()
    ontem = hoje - timedelta(days=1)
    
    async with session_factory() as session:
        # --- CENÁRIO 1: A QUOTA VENCEU ONTEM ---
        logger.info("A iniciar verificação de quotas que venceram ontem (%s)...", ontem)
        query_vencidos = select(User).where(
            User.ativo == True,
            User.data_expiracao_quota == ontem
        )
        result_vencidos = await session.scalars(query_vencidos)
        militantes_vencidos = result_vencidos.all()

        for user in militantes_vencidos:
            notificacao = Notification(
                user_id=user.id,
                titulo="Quota Expirada",
                mensagem=f"Olá {user.nome_completo}, a sua validade financeira de quotas expirou em {ontem.strftime('%d/%m/%Y')}. Regularize a sua situação para manter os seus benefícios ativos.",
                categoria=RoleCategoriaNotificacao.QUOTA
            )
            session.add(notificacao)
            logger.info("Notificação de quota vencida gerada para: %s", user.email)

        # --- CENÁRIO 2: NOVOS INSCRITOS SEM PAGAMENTO ---
        # Filtra utilizadores criados há mais de 3 dias (exemplo) que NUNCA pagaram nenhuma quota
        limite_novos = hoje - timedelta(days=3)
        logger.info("A verificar novos inscritos sem quotas registados antes de %s...", limite_novos)
        
        # Seleciona utilizadores sem data de expiração e criados recentemente
        # (Ajuste o nome do campo 'criado_em' conforme o seu modelo User)
        query_novos = select(User).where(
            User.ativo == True,
            User.data_expiracao_quota == None,
            User.criado_em <= limite_novos 
        )
        result_novos = await session.scalars(query_novos)
        novos_membros = result_novos.all()

        for user in novos_membros:
            # Opcional: Verifica se ele já não tem pelo menos uma quota PENDENTE para não chatear o user
            query_tem_pendente = select(PagamentoQuota).where(
                PagamentoQuota.user_id == user.id,
                PagamentoQuota.status == QuotaStatusEnum.PENDING
            )
            if await session.scalar(query_tem_pendente):
                continue

            notificacao_boas_vindas = Notification(
                user_id=user.id,
                titulo="Bem-vindo! Ative as suas Quotas",
                mensagem=f"Olá {user.nome_completo}! Como novo militante, lembre-se de efetuar o pagamento da sua primeira quota para ativar a emissão do seu cartão de militante.",
                categoria=RoleCategoriaNotificacao.QUOTA
            )
            session.add(notificacao_boas_vindas)
            logger.info("Notificação de boas-vindas/quota enviada para novo inscrito: %s", user.email)

        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Erro ao rodar job de notificações de quota: %s", e)

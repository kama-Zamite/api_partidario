from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from typing import Annotated, Optional
import logging
from project_part.model.models import User, Notification, RoleCategoriaNotificacao
from project_part.db.session import get_session



Session = Annotated[AsyncSession, Depends(get_session)]

logger = logging.getLogger(__name__)



async def disparar_notificacao_usuario(
    session: Session,
    user_destinatario: User,
    titulo: str,
    corpo: str,
    destinatario_tipo,
    categoria: RoleCategoriaNotificacao,  # O Enum que corrigimos antes
    criado_as: Optional[datetime] = None
) -> Optional[Notification]:
    """
    Tenta criar uma notificação no banco de dados apenas se o utilizador 
    tiver o toggle correspondente ativado no seu painel de preferências.
    """
    
    # 1. Se as notificações gerais estiverem desativadas, bloqueia TUDO imediatamente
    if not getattr(user_destinatario, "notificacoes_gerais", True):
        logger.info("Notificação bloqueada: %s desativou as Notificações Gerais.", user_destinatario.email)
        return None

    # 2. Mapeamento das regras de negócio com base nos Enums e as colunas da imagem
    # Ajuste as chaves do Enum 'RoleCategoriaNotificacao' conforme o seu arquivo real
    if categoria == RoleCategoriaNotificacao.COMUNICADO and not getattr(user_destinatario, "comunicados_oficiais", True):
        logger.info("Envio cancelado por preferência do usuário para: Comunicados Oficiais")
        return None
        
    if categoria == RoleCategoriaNotificacao.EVENTO and not getattr(user_destinatario, "eventos_mobilizacoes", True):
        logger.info("Envio cancelado por preferência do usuário para: Eventos e Mobilizações")
        return None
        
    if categoria == RoleCategoriaNotificacao.QUOTA and not getattr(user_destinatario, "contribuicoes_quota", True):
        logger.info("Envio cancelado por preferência do usuário para: Contribuições e Quotas")
        return None
        
    if categoria == RoleCategoriaNotificacao.NOTICIA and not getattr(user_destinatario, "noticias_partido", True):
        logger.info("Envio cancelado por preferência do usuário para: Notícias do Partido")
        return None

    # 3. Se passou por todos os filtros, o utilizador quer receber. Instancia o modelo corrigido:
    nova_notificacao = Notification(
        user_id=user_destinatario.id,
        titulo=titulo,
        mensagem=corpo,
        categoria=categoria,
        criado_as=criado_as,
        destinatario=destinatario_tipo, 
        # O 'criado_as' será preenchido automaticamente pelo 'server_default=func.now()' do Postgres
    )
    try:
        session.add(nova_notificacao)
        await session.flush() # Sincroniza o ID na sessão assíncrona
        logger.info("Notificação de %s criada com sucesso para %s.", categoria, user_destinatario.email)
        return nova_notificacao
    except Exception as e:
        logger.error("Erro ao persistir notificação: %s", str(e))
        return None

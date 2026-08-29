import uuid
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import attributes
from sqlalchemy import select

from project_part.core.context import (
    client_ip_ctx,
    current_user_id_ctx,
    user_agent_ctx,
)
from project_part.model.models import AuditLog, User  # Ajuste os seus imports

logger = logging.getLogger(__name__)

# Lista global e estrita de chaves confidenciais para mascarar em conformidade com a privacidade
CAMPOS_SENSIVEIS = {
    "email", "nif", "password", "senha", "telefone", "telemovel", 
    "nome_completo", "nome", "name", "militante_numero"
}

def obter_dados_objeto(instance, estado='novo', partilha_autorizada: bool = True):
    """Extrai mapeamentos de colunas para dicionários estruturados JSONB aplicando anonimização"""
    res = {}
    mapper = instance.__mapper__
    for attr in mapper.column_attrs:
        hist = attributes.get_history(instance, attr.key)
        
        # 1. Extração bruta do valor baseado no estado temporal do objeto
        if estado == 'ultimo':
            valor = str(hist.deleted[0]) if hist.deleted else str(getattr(instance, attr.key))
        else:
            valor = str(getattr(instance, attr.key))
            
        # 2. 🚀 APLICAÇÃO DA HIPÓTESE FALSE: Mascara o dado se o utilizador não autorizou a partilha
        if not partilha_autorizada and attr.key.lower() in CAMPOS_SENSIVEIS:
            res[attr.key] = "[OCULTADO POR PRIVACIDADE]"
        else:
            res[attr.key] = valor
            
    return res


async def processar_auditoria_sessao(session: AsyncSession):
    """Varre a sessão assíncrona gerando os logs de auditoria anonimizados se necessário antes de persistir"""
    logs_para_salvar = []
    
    # 1. Recupera o ID do utilizador corrente através da variável de contexto
    user_id_str = current_user_id_ctx.get()
    usuario_id_final = uuid.UUID(user_id_str) if user_id_str else None
    
    # 2. DETERMINAÇÃO DO CONSENTIMENTO (Padrão de Segurança Privada)
    partilha_autorizada = False
    if usuario_id_final:
        # Tenta verificar se o objeto do utilizador atual já está carregado na memória da própria sessão
        user_em_memoria = session.get_loaded_instance(User, (usuario_id_final,))
        if user_em_memoria:
            partilha_autorizada = getattr(user_em_memoria, "partilha_dados", False)
        else:
            # Caso não esteja na memória, faz uma busca rápida e direta no banco antes do flush
            user_banco = await session.scalar(select(User).where(User.id == usuario_id_final))
            partilha_autorizada = getattr(user_banco, "partilha_dados", False) if user_banco else False

    # 3. EXTRAÇÃO DAS METRICS DE REDE E DISPOSITIVO
    ip_original = client_ip_ctx.get()
    agent_original = user_agent_ctx.get()

    # Aplica as restrições nas variáveis de ambiente globais caso o consentimento seja falso
    ip_final = ip_original if partilha_autorizada else "0.0.0.0"
    user_agent_final = agent_original if partilha_autorizada else "Ocultado por privacidade"
    usuario_id_log = usuario_id_final if partilha_autorizada else None

    # 4. VARREDURA DOS ITENS NOVOS (CREATE)
    for obj in session.new:
        if isinstance(obj, AuditLog):
            continue
        logs_para_salvar.append(
            AuditLog(
                accao='CREATE',
                entidade=obj.__tablename__,
                entidade_id=str(getattr(obj, 'id', 'N/A')),
                ultimo_valores=None,
                novo_valores=obter_dados_objeto(obj, 'novo', partilha_autorizada),
                ip_endereco=ip_final,
                user_agent=user_agent_final,
                usuario_id=usuario_id_log,
            )
        )

    # 5. VARREDURA DOS ITENS ALTERADOS (UPDATE)
    for obj in session.dirty:
        if isinstance(obj, AuditLog):
            continue
        logs_para_salvar.append(
            AuditLog(
                accao='UPDATE',
                entidade=obj.__tablename__,
                entidade_id=str(getattr(obj, 'id', 'N/A')),
                ultimo_valores=obter_dados_objeto(obj, 'ultimo', partilha_autorizada),
                novo_valores=obter_dados_objeto(obj, 'novo', partilha_autorizada),
                ip_endereco=ip_final,
                user_agent=user_agent_final,
                usuario_id=usuario_id_log,
            )
        )

    # 6. VARREDURA DOS ITENS REMOVIDOS (DELETE)
    for obj in session.deleted:
        if isinstance(obj, AuditLog):
            continue
        logs_para_salvar.append(
            AuditLog(
                accao='DELETE',
                entidade=obj.__tablename__,
                entidade_id=str(getattr(obj, 'id', 'N/A')),
                ultimo_valores=obter_dados_objeto(obj, 'ultimo', partilha_autorizada),
                novo_valores=None,
                ip_endereco=ip_final,
                user_agent=user_agent_final,
                usuario_id=usuario_id_log,
            )
        )

    # Injeta os logs gerados de forma assíncrona na sessão corrente
    if logs_para_salvar:
        session.add_all(logs_para_salvar)
        logger.info("%s logs de auditoria estruturados e injetados na sessão.", len(logs_para_salvar))
























# import uuid

# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy.orm import attributes

# from project_part.core.context import (
#     client_ip_ctx,
#     current_user_id_ctx,
#     user_agent_ctx,
# )
# from project_part.model.models import AuditLog


# def obter_dados_objeto(instance, estado='novo'):
#     """Extrai mapeamentos de colunas para dicionários estruturados JSONB"""
#     res = {}
#     mapper = instance.__mapper__
#     for attr in mapper.column_attrs:
#         hist = attributes.get_history(instance, attr.key)
#         if estado == 'ultimo':
#             res[attr.key] = str(hist.deleted[0]) if hist.deleted else str(getattr(instance, attr.key))
#         else:
#             res[attr.key] = str(getattr(instance, attr.key))
#     return res


# async def processar_auditoria_sessao(session: AsyncSession):
#     """Varre a sessão assíncrona gerando os logs de auditoria antes de persistir"""
#     logs_para_salvar = []

#     # 1. Itens novos (CREATE)
#     for obj in session.new:
#         if isinstance(obj, AuditLog):
#             continue
#         logs_para_salvar.append(
#             AuditLog(
#                 accao='CREATE',
#                 entidade=obj.__tablename__,
#                 entidade_id=str(getattr(obj, 'id', 'N/A')),
#                 ultimo_valores=None,
#                 novo_valores=obter_dados_objeto(obj, 'novo'),
#                 ip_endereco=client_ip_ctx.get(),
#                 user_agent=user_agent_ctx.get(),
#                 usuario_id=uuid.UUID(current_user_id_ctx.get()) if current_user_id_ctx.get() else None,
#             )
#         )

#     # 2. Itens alterados (UPDATE)
#     for obj in session.dirty:
#         if isinstance(obj, AuditLog):
#             continue
#         logs_para_salvar.append(
#             AuditLog(
#                 accao='UPDATE',
#                 entidade=obj.__tablename__,
#                 entidade_id=str(getattr(obj, 'id', 'N/A')),
#                 ultimo_valores=obter_dados_objeto(obj, 'ultimo'),
#                 novo_valores=obter_dados_objeto(obj, 'novo'),
#                 ip_endereco=client_ip_ctx.get(),
#                 user_agent=user_agent_ctx.get(),
#                 usuario_id=uuid.UUID(current_user_id_ctx.get()) if current_user_id_ctx.get() else None,
#             )
#         )

#     # 3. Itens removidos (DELETE)
#     for obj in session.deleted:
#         if isinstance(obj, AuditLog):
#             continue
#         logs_para_salvar.append(
#             AuditLog(
#                 accao='DELETE',
#                 entidade=obj.__tablename__,
#                 entidade_id=str(getattr(obj, 'id', 'N/A')),
#                 ultimo_valores=obter_dados_objeto(obj, 'ultimo'),
#                 novo_valores=None,
#                 ip_endereco=client_ip_ctx.get(),
#                 user_agent=user_agent_ctx.get(),
#                 usuario_id=uuid.UUID(current_user_id_ctx.get()) if current_user_id_ctx.get() else None,
#             )
#         )

#     # Injeta os logs gerados de forma assíncrona na sessão corrente
#     if logs_para_salvar:
#         session.add_all(logs_para_salvar)

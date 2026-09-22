import json
from decimal import Decimal
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
)
from typing import Annotated
from project_part.db.session import get_session
from fastapi.responses import StreamingResponse
from project_part.core.rate_limit import limiter
from project_part.core.secury import Get_current_user
from project_part.model.models import (
    User,
    Doacao,
    PagamentoQuota,
    DonationStatusEnum,
    QuotaStatusEnum,
)
from project_part.api.privacy.schemas import (
    PartilharDados,
    CookiesPersonalizacao
)
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import logging
from datetime import datetime, timezone
from typing import Any, Optional    
import io


logger = logging.getLogger(__name__)
# Inicialize o seu router de privacidade
Session = Annotated[AsyncSession, Depends(get_session)]

privacy = APIRouter(prefix="/privacy", tags=["Privacidade"])

# @privacy.post('/solicitar-dados', summary='Descarregar todos os dados do utilizador')

# async def descarregar_dados_utilizador(
#     request: Request,
#     session: Session,
#     current_user: Get_current_user  # Garanta que o utilizador está autenticado
# ):
#     """
#         Recolhe todas as informações que o sistema possui sobre o utilizador 
#         e gera um ficheiro JSON para download imediato.
#     """
#     logger.info('Utilizador %s solicitou a descarga dos seus dados pessoais.', current_user.id)
#     filtros = [Doacao.user_id == current_user.id, Doacao.status == DonationStatusEnum.APPROVED]

#     logger.info('Buscando dados do utilizador %s na base de dados.', current_user.email)
#     query = (select(User).where(User.id == current_user.id).options(
#         selectinload(User.scope),
#         selectinload(User.municipio),
#         selectinload(User.provincia),
#         selectinload(User.role),
#         ))
#     result = await session.scalar(query)
#     if not result:
#         logger.warning('Nenhum registo encontrado para o utilizador %s.', current_user.id)
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail='Nenhum registo encontrado para o utilizador.'
#         )

#     logger.info('Buscando pelos financeiros do usuario %s', current_user.nome_completo)

#     count_q = (
#             select(func.count(Doacao.id))
#             .join(User, User.id == Doacao.user_id)
#             .where(*filtros)
#         )

#     q_quotas = select(func.coalesce(func.sum(PagamentoQuota.quantia), 0)).where(
#         PagamentoQuota.status == QuotaStatusEnum.APPROVED
#     )

#     q_quotas = (
#             q_quotas.join(User, User.id == PagamentoQuota.user_id)
#             .where(User.id == current_user.id)
#         )

#     total_quota = await session.scalar(q_quotas) or 0
#     # count_q = select(func.count(Doacao.id)).where(*filtros) if filtros else select(func.count(Doacao.id))
    
#     total = await session.scalar(count_q) or 0

#     try:
#         # 1. Reunir os dados básicos do utilizador (Tabela Users)
#         dados_pessoais = {
#             "nome_completo": result.nome_completo,
#             "email": result.email,
#             "nif": result.nif,
#             "militante_numero": result.militante_numero,
#             "genero": result.genero,
#             "estado_civil": result.estado_civil,
#             "data_nascimento": result.data_nascimento.isoformat() if result.data_nascimento else None,
#             "telefone": result.telefone,
#             "status": result.ativo,
#             "cadastrado_como": result.cadastrar_militante,
#             "ja_foi_militante_em_outro_partido": result.foi_militante,
#             "provincia": result.provincia.nome_provincia if result.provincia else None,
#             "municipio": result.municipio.nome_municipio if result.municipio else None,
#             "criado_em": result.criado_em.isoformat() if result.criado_em else None,
#             "dados_financeiros": {
#                 "doacoes_feitas": total,
#                 "pagamentos_quotas": total_quota,
#                 # "ultima_doacao": result.doacoes if result.ultima_doacao else None,
#                 # "proximo_pagamento_quota": result.pagamentos_quota. if result.pagamentos_quota else None,
#             }
#         }

#         # 2. Reunir registos de outras tabelas vinculadas (Exemplo: Solicitações de Cartão)
#         # Ajuste as queries abaixo de acordo com os seus relacionamentos reais do SQLAlchemy
#         # resultado_cartao = await session.scalars(select(SolicitacaoCartao).where(SolicitacaoCartao.user_id == current_user.id))
#         # solicitacoes_cartao = [c.to_dict() for c in resultado_cartao.all()]

#         # 3. Montar o pacote completo de dados (Estrutura do Ficheiro)
#         dados_finais = {
#             "unita_plataforma_digital": {
#                 "exportado_as": datetime.now(timezone.utc).isoformat(),
#                 "dados_perfil": dados_pessoais,
#             }
#         }

#         # 4. Converter o dicionário para uma string JSON formatada
#         json_string = json.dumps(dados_finais, indent=4, ensure_ascii=False)
        
#         # 5. Criar um fluxo de bytes em memória (Stream) para evitar salvar o ficheiro no disco do servidor
#         file_stream = io.BytesIO(json_string.encode('utf-8'))

#         # 6. Configurar o cabeçalho para forçar o navegador a descarregar o ficheiro
#         headers = {
#             'Content-Disposition': f'attachment; filename="meus_dados_unita_{current_user.id}.json"'
#         }

#         return StreamingResponse(file_stream, media_type='application/json', headers=headers)

#     except Exception as e:
#         logger.error('Erro ao compilar os dados do utilizador %s: %s', current_user.id, str(e))
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail='Erro interno ao gerar o pacote de dados para download.'
#         )


@privacy.post('/solicitar-dados', summary='Descarregar todos os dados do utilizador')
@limiter.limit("1/minute, 2/hour, 4/day")  # Limite de taxa para evitar abuso
async def descarregar_dados_utilizador(
    request: Request,
    session: Session,
    current_user: Get_current_user,
):
    """
    Recolhe as informações do utilizador e gera um ficheiro JSON para download.
    """
    logger.info('Utilizador %s solicitou a descarga dos seus dados pessoais.', current_user.id)

    # -------------------------------------------------
    # 1. Dados básicos do utilizador
    # -------------------------------------------------
    logger.info('Buscando dados do utilizador %s na base de dados.', current_user.email)

    query = (
        select(User)
        .where(User.id == current_user.id)
        .options(
            selectinload(User.scope),
            selectinload(User.municipio),
            selectinload(User.provincia),
            selectinload(User.role),
        )
    )
    result = await session.scalar(query)

    if not result:
        logger.warning('Nenhum registo encontrado para o utilizador %s.', current_user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Nenhum registo encontrado para o utilizador.'
        )

    # -------------------------------------------------
    # 2. Resumo financeiro - Doações
    # -------------------------------------------------
    logger.info('Buscando dados financeiros do utilizador %s', current_user.nome_completo)

    # Total e quantidade de doações aprovadas
    total_doacoes = await session.scalar(
        select(func.coalesce(func.sum(Doacao.quantia), 0))
        .where(
            Doacao.user_id == current_user.id,
            Doacao.status == DonationStatusEnum.APPROVED,
        )
    ) or Decimal("0")

    qtd_doacoes = await session.scalar(
        select(func.count(Doacao.id))
        .where(
            Doacao.user_id == current_user.id,
            Doacao.status == DonationStatusEnum.APPROVED,
        )
    ) or 0

    # Última doação
    ultima_doacao = await session.scalar(
        select(Doacao)
        .where(
            Doacao.user_id == current_user.id,
            Doacao.status == DonationStatusEnum.APPROVED,
        )
        .order_by(Doacao.data_doacao.desc())
        .limit(1)
    )

    # -------------------------------------------------
    # 3. Resumo financeiro - Quotas
    # -------------------------------------------------
    total_quotas = await session.scalar(
        select(func.coalesce(func.sum(PagamentoQuota.quantia), 0))
        .where(
            PagamentoQuota.user_id == current_user.id,
            PagamentoQuota.status == QuotaStatusEnum.APPROVED,
        )
    ) or Decimal("0")

    qtd_quotas = await session.scalar(
        select(func.count(PagamentoQuota.id))
        .where(
            PagamentoQuota.user_id == current_user.id,
            PagamentoQuota.status == QuotaStatusEnum.APPROVED,
        )
    ) or 0

    # Último pagamento de quota
    ultimo_pagamento_quota = await session.scalar(
        select(PagamentoQuota)
        .where(
            PagamentoQuota.user_id == current_user.id,
            PagamentoQuota.status == QuotaStatusEnum.APPROVED,
        )
        .order_by(PagamentoQuota.data_pagamento.desc())
        .limit(1)
    )

    # -------------------------------------------------
    # 4. Montar o pacote de dados
    # -------------------------------------------------
    try:
        dados_pessoais = {
            "nome_completo": result.nome_completo,
            "email": result.email,
            "nif": result.nif,
            "militante_numero": result.militante_numero,
            "genero": result.genero,
            "estado_civil": result.estado_civil,
            "data_nascimento": result.data_nascimento.isoformat() if result.data_nascimento else None,
            "telefone": result.telefone,
            "status": result.ativo,
            "cadastrado_como": result.cadastrar_militante,
            "ja_foi_militante_em_outro_partido": result.foi_militante,
            "provincia": result.provincia.nome_provincia if result.provincia else None,
            "municipio": result.municipio.nome_municipio if result.municipio else None,
            "criado_em": result.criado_em.isoformat() if result.criado_em else None,
        }

        dados_financeiros = {
            "doacoes": {
                "total": float(total_doacoes),
                "quantidade": qtd_doacoes,
                "ultima_doacao": {
                    "quantia": float(ultima_doacao.quantia) if ultima_doacao else None,
                    "data": ultima_doacao.data_doacao.isoformat() if ultima_doacao and ultima_doacao.data_doacao else None,
                    "referencia": ultima_doacao.referencia if ultima_doacao else None,
                } if ultima_doacao else None,
            },
            "pagamentos_quota": {
                "total": float(total_quotas),
                "quantidade": qtd_quotas,
                "ultimo_pagamento": {
                    "quantia": float(ultimo_pagamento_quota.quantia) if ultimo_pagamento_quota else None,
                    "periodo": ultimo_pagamento_quota.periodo if ultimo_pagamento_quota else None,
                    "data": ultimo_pagamento_quota.data_pagamento.isoformat() if ultimo_pagamento_quota and ultimo_pagamento_quota.data_pagamento else None,
                    "referencia": ultimo_pagamento_quota.referencia if ultimo_pagamento_quota else None,
                } if ultimo_pagamento_quota else None,
                "data_expiracao_quota": result.data_expiracao_quota.isoformat() if result.data_expiracao_quota else None,
            },
        }

        dados_finais = {
            "unita_plataforma_digital": {
                "exportado_as": datetime.now(timezone.utc).isoformat(),
                "dados_perfil": dados_pessoais,
                "dados_financeiros": dados_financeiros,
            }
        }

        json_string = json.dumps(dados_finais, indent=4, ensure_ascii=False)
        file_stream = io.BytesIO(json_string.encode('utf-8'))

        headers = {
            'Content-Disposition': f'attachment; filename="meus_dados_unita_{current_user.id}.json"'
        }

        return StreamingResponse(
            file_stream,
            media_type='application/json',
            headers=headers,
        )

    except Exception as e:
        logger.error('Erro ao compilar os dados do utilizador %s: %s', current_user.id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno ao gerar o pacote de dados para download.'
        )

@privacy.patch('/partilhar-dados', summary='Atualizar definições de privacidade')
async def partilhar_dados(
    dados: PartilharDados,
    session: Session,
    current_user: Get_current_user
):
    """
    Atualiza o estado dos interruptores (toggles) de consentimento e cookies 
    do utilizador autenticado na base de dados.
    """
    logger.info('Utilizador %s solicitou atualização das configurações de privacidade.', current_user.id)

    try:
        if dados.partilha_dados is not None:
            current_user.partilha_dados = dados.partilha_dados
            
        await session.commit()
        
        # ADICIONE ESTA LINHA: Garante que estamos a ler o que foi gravado de facto
        await session.refresh(current_user)
        logger.info("Partilha de dados do usuario %s atualizado para: %s", current_user.email, current_user.partilha_dados)
        return {
            "detail": "Configurações de privacidade updated.",
            "configuracoes": {
                "partilha_dados": current_user.partilha_dados
            }
        }

    except Exception as e:
        await session.rollback()
        logger.error('Erro ao atualizar privacidade do utilizador %s: %s', current_user.id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno ao salvar as preferências de privacidade.'
        )
    

@privacy.patch('/cookies-personalizado', summary='Atualizar definições de privacidade')
async def atualizar_privacidade(
    dados: CookiesPersonalizacao,
    session: Session,
    current_user: Get_current_user
):
    """
    Atualiza o estado dos interruptores (toggles) de consentimento e cookies 
    do utilizador autenticado na base de dados.
    """
    logger.info('Utilizador %s solicitou atualização das configurações de privacidade.', current_user.id)

    try:
        if dados.cookies_personalizacao is not None:
            current_user.cookies_personalizacao = dados.cookies_personalizacao

        await session.commit()
        
        # ADICIONE ESTA LINHA: Garante que estamos a ler o que foi gravado de facto
        await session.refresh(current_user)
        logger.info("Cookies de personalização do usuario %s atualizado para: %s", current_user.email, current_user.cookies_personalizacao)
        return {
            "detail": "Configurações de privacidade updated.",
            "configuracoes": {
                "cookies_personalizacao": current_user.cookies_personalizacao
            }
        }

    except Exception as e:
        await session.rollback()
        logger.error('Erro ao atualizar privacidade do utilizador %s: %s', current_user.id, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno ao salvar as preferências de privacidade.'
        )
    

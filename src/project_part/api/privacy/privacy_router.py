import json
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
from project_part.core.secury import Get_current_user
from project_part.model.models import User
from project_part.api.privacy.schemas import (
    PartilharDados,
    CookiesPersonalizacao
)
from sqlalchemy import select
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

@privacy.post('/solicitar-dados', summary='Descarregar todos os dados do utilizador')

async def descarregar_dados_utilizador(
    request: Request,
    session: Session,
    current_user: Get_current_user  # Garanta que o utilizador está autenticado
):
    """
    Recolhe todas as informações que o sistema possui sobre o utilizador 
    e gera um ficheiro JSON para download imediato.
    """
    logger.info('Utilizador %s solicitou a descarga dos seus dados pessoais.', current_user.id)


    logger.info('Buscando dados do utilizador %s na base de dados.', current_user.email)
    query = (select(User).where(User.id == current_user.id).options(
        selectinload(User.scope),
        selectinload(User.municipio),
        selectinload(User.provincia),
        selectinload(User.role)
        ))
    result = await session.scalar(query)
    if not result:
        logger.warning('Nenhum registo encontrado para o utilizador %s.', current_user.id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Nenhum registo encontrado para o utilizador.'
        )

    try:
        # 1. Reunir os dados básicos do utilizador (Tabela Users)
        dados_pessoais = {
            "nome_completo": result.nome_completo,
            "email": result.email,
            "nif": result.nif,
            "militante_numero": result.militante_numero,
            "genero": result.genero,
            "data_nascimento": result.data_nascimento.isoformat() if result.data_nascimento else None,
            "telefone": result.telefone,
            "criado_em": result.criado_em.isoformat() if result.criado_em else None
        }

        # 2. Reunir registos de outras tabelas vinculadas (Exemplo: Solicitações de Cartão)
        # Ajuste as queries abaixo de acordo com os seus relacionamentos reais do SQLAlchemy
        # resultado_cartao = await session.scalars(select(SolicitacaoCartao).where(SolicitacaoCartao.user_id == current_user.id))
        # solicitacoes_cartao = [c.to_dict() for c in resultado_cartao.all()]

        # 3. Montar o pacote completo de dados (Estrutura do Ficheiro)
        dados_finais = {
            "unita_plataforma_digital": {
                "exportado_as": datetime.now(timezone.utc).isoformat(),
                "dados_perfil": dados_pessoais,
            }
        }

        # 4. Converter o dicionário para uma string JSON formatada
        json_string = json.dumps(dados_finais, indent=4, ensure_ascii=False)
        
        # 5. Criar um fluxo de bytes em memória (Stream) para evitar salvar o ficheiro no disco do servidor
        file_stream = io.BytesIO(json_string.encode('utf-8'))

        # 6. Configurar o cabeçalho para forçar o navegador a descarregar o ficheiro
        headers = {
            'Content-Disposition': f'attachment; filename="meus_dados_unita_{current_user.id}.json"'
        }

        return StreamingResponse(file_stream, media_type='application/json', headers=headers)

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
    

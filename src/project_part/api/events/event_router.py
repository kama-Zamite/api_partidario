import logging
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    Query,
)
from pydantic import ValidationError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from project_part.core.cloudinary_config import (
    apagar_imagem_evento_cloudinary,
    upload_imagem_geral,
)
from project_part.core.rate_limit import limiter
from project_part.core.secury import (
    Get_current_user,
    garante_escopo_territorial,
    verificar_permissao_global_pais,
)
from project_part.db.cache import get_redis
from project_part.db.session import get_session
from project_part.model.models import (
    AdminScope,
    Event,
    EventStatusEnum,
    Municipio,
    Provincia,
    EventoCategoriaEnum,
    User,
    Notification,
    RoleCategoriaNotificacao,
)

from .schemas import (
    CreateEvent,
    EventResponse,
    LimitEvent,
    UpgradeEvent,
    EventosPaginadosResponse,
)

logger = logging.getLogger(__name__)
Redis = Annotated[AsyncRedis, Depends(get_redis)]
Session = Annotated[AsyncSession, Depends(get_session)]
Paginacao = Annotated[LimitEvent, Depends()]
ScopeValid = Annotated[AdminScope, Depends(garante_escopo_territorial)]

event = APIRouter(prefix='/event', tags=['Events'])

CACHE_KEY_LISTA = 'v1:eventos:lista'
ALLOWED_EXTENSIONS = ['.jpg', '.jpeg']
FILE_SIZE_LIMIT = 5 * 1024 * 1024  # 5 MB


# @event.post('/categories/create', status_code=HTTPStatus.CREATED)
# @limiter.limit('3/minute')
# async def criar_categoria(
#     request: Request, schemas: CreateCategoria, session: Session, current_user: Get_current_user, scope: ScopeValid
# ):
#     logger.info('Criando categoria de Eventos: %s por %s', schemas.name, current_user.email)

#     verificar_permissao_global_pais(scope, current_user)

#     nova_categoria = EventoCategoria(name=schemas.name)
#     try:
#         session.add(nova_categoria)
#         await session.commit()
#         return {'msg': 'Categoria criada com sucesso!'}
#     except IntegrityError as e:
#         await session.rollback()
#         logger.error('Erro de integridade ao criar categoria: %s', str(e.orig))
#         raise HTTPException(status_code=HTTPStatus.CONFLICT, detail='Já existe uma categoria cadastrada com este nome.')


@event.post('/create', status_code=HTTPStatus.CREATED)
@limiter.limit('3/minute')
async def criar_evento(
    request: Request,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
    titulo: str = Form(..., max_length=200),
    descricao: str = Form(...),
    localizacao: str = Form(max_length=255),
    data_inicio: datetime = Form(...),
    # data_fim: datetime = Form(...),
    nome_categoria: EventoCategoriaEnum = Form(...),
    nome_provincia: str = Form(...),
    nome_municipio: str = Form(...),
    max_participantes: int | None = Form(None, gt=0),
    image_event: UploadFile = File(..., description='Imagem do evento (jpg, jpeg)'),
):

    try:
        dados_valido = CreateEvent(
            titulo=titulo,
            descricao=descricao,
            localizacao=localizacao,
            data_inicio=data_inicio,
            # data_fim=data_fim,
            categoria=nome_categoria,
            nome_provincia=nome_provincia,
            nome_municipio=nome_municipio,
            max_participantes=max_participantes,
        )
    except ValidationError as e:
        logger.error('Erro de validação ao criar evento: %s', str(e))
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,  # Mudado para 422 (padrão do FastAPI para falhas de validação)
            detail=e.errors(include_url=False, include_context=False),
        )

    logger.info('Buscando a província: %s', dados_valido.nome_provincia)
    provincia_banco = await session.scalar(
        select(Provincia).where(Provincia.nome_provincia == dados_valido.nome_provincia)
    )
    if not provincia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')

    logger.info('Buscando o município: %s', dados_valido.nome_municipio)
    municipio_banco = await session.scalar(
        select(Municipio).where(
            Municipio.nome_municipio == dados_valido.nome_municipio,
            Municipio.id_provincia == provincia_banco.id,
        )
    )
    if not municipio_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'O município "{dados_valido.nome_municipio}" não pertence à província "{dados_valido.nome_provincia}"',
        )

    if scope.provincia_id and provincia_banco.id != scope.provincia_id:
        logger.warning('Admin %s fora da sua província permitida.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode criar eventos na sua província.'
        )

    # if scope.municipio_id and municipio_banco.id != scope.municipio_id:
    #     logger.warning('Admin %s fora do seu município permitido.', current_user.id)
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode criar eventos no seu município.'
    #     )

    evento = Event(
        titulo=dados_valido.titulo,
        descricao=dados_valido.descricao,
        localizacao=dados_valido.localizacao,
        data_inicio=dados_valido.data_inicio,
        categoria=nome_categoria,
        provincia_id=provincia_banco.id,
        municipio_id=municipio_banco.id,
        max_participantes=dados_valido.max_participantes,
        status= EventStatusEnum.PUBLICADO,
        criado_por=current_user.id,
        image_url=None,
    )

    try:
        session.add(evento)
        await session.flush()

        if image_event:
            extensao = image_event.filename.split('.')[-1].lower()
            if extensao not in {'jpg', 'jpeg'}:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail='Formato de imagem inválido. Use apenas PNG, JPG, JPEG ou WEBP.',
                )

            conteudo_byte = await image_event.read()
            if len(conteudo_byte) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST, detail='A foto de perfil não pode ser maior que 5MB.'
                )

            try:
                url_secure = await upload_imagem_geral(
                    file_bytes=conteudo_byte,
                    identificador=str(evento.id),
                    pasta_alvo='atividades_partido',
                    prefixo_arquivo='event',
                )
                evento.image_url = url_secure
            except Exception as e:
                logger.error('Falha ao subir imagem para o Cloudinary: %s', e)
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail='Falha ao salvar imagem de perfil no serviço de nuvem.',
                )
            finally:
                await image_event.close()


            query_destinatarios = (
                select(User.id)
                .where(
                    User.ativo.is_(True),
                    User.notificacoes_gerais.is_(True),
                    User.eventos_mobilizacoes.is_(True)
                )
            )  
            resultado_ids = await session.execute(query_destinatarios)
            lista_ids = resultado_ids.scalars().all()
            if lista_ids:
                logger.info("A gerar notificações em lote para %s utilizadores autorizados.", len(lista_ids))
            
                notificacoes_em_lote = [
                    Notification(
                        user_id=uid,
                        titulo=f"Novo Evento: {evento.titulo}",
                        mensagem=f"Foi agendado um novo evento na sua região. Participe!",
                        categoria=RoleCategoriaNotificacao.EVENTOS,  # O seu Enum corrigido
                        criado_as=datetime.now(timezone.utc),
                        destinatario=None,

                    )
                    for uid in lista_ids
                ]
                session.add_all(notificacoes_em_lote)

        await session.commit()
        await caches.delete(CACHE_KEY_LISTA)
        logger.info('Evento [%s] criado com sucesso por %s.', dados_valido.titulo, current_user.email)
        return {'msg': 'Evento criado com sucesso!', 'evento_id': str(evento.id), 'image_url': evento.image_url}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao criar evento: [%s]', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Já existe um evento cadastrado com esses dados, conflitantes (ex: mesmo título).',
        )
    except Exception as e:
        await session.rollback()
        logger.critical('Erro inesperado na criação do evento: %s', e)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno no servidor.')


@event.get('/current_user/list/', status_code=HTTPStatus.OK, response_model=EventosPaginadosResponse) # <-- Atualize o schema aqui
async def listar_eventos(
    response: Response,
    session: Session,
    caches: Redis,
    pagin: Paginacao,
    current_user: Get_current_user,
    nome_provincia: str | None = Query(None),
    type: str | None = Query(None),
):
    # 1. Iniciamos as queries base (uma para os dados e outra para a contagem)
    query = select(Event).options(selectinload(Event.provincia), selectinload(Event.municipio)).order_by(Event.criado_as.desc())
    count_query = select(func.count()).select_from(Event) # Query limpa apenas para contar

    # 2. Filtro de Província
    if not nome_provincia and current_user:
        if current_user.cookies_personalizacao and hasattr(current_user, "provincia_id") and current_user.provincia_id:
            logger.info("Cookies ativos: Personalizando eventos para a província do utilizador.")
            query = query.where(Event.provincia_id == current_user.provincia_id)
            count_query = count_query.where(Event.provincia_id == current_user.provincia_id)

        # HIPÓTESE 2: Se for FALSE, o bloco acima é ignorado e ele recebe eventos de TODAS as províncias
        else:
            logger.info("Cookies inativos ou sem província: Listando todos os eventos globalmente.")
 
        logger.info('Filtrando pela província: %s', nome_provincia)
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == nome_provincia)
        )

     # 2. Se o utilizador pesquisou uma província específica na caixa de busca, ela tem prioridade máxima
    if nome_provincia:
        provincia_banco = await session.scalar(select(Provincia).where(Provincia.nome_provincia == nome_provincia))
        if not provincia_banco:
            logger.warning('Província não encontrada')
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada') 
        logger.info("Buscar eventos da provincia %s", provincia_banco)
        query = query.where(Event.provincia_id == provincia_banco.id)
        count_query = count_query.where(Event.provincia_id == provincia_banco.id)

    # 3. Filtro de Categoria (type)
    if type:
        logger.info('Filtrando pela categoria: %s', type)
        query = query.where(Event.categoria == type)
        count_query = count_query.where(Event.categoria == type)

    # 4. Executa a contagem TOTAL antes de aplicar a paginação
    total_eventos = await session.scalar(count_query) or 0

    # 5. Aplica a paginação APENAS na query que traz os dados dos eventos
    query = query.limit(pagin.limit).offset(pagin.skip)
    resultado = await session.scalars(query)
    eventos = resultado.all()

    # 6. Validação
    if not eventos:
        logger.warning('Nenhum evento encontrado.')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhum evento encontrado no sistema para estes critérios.',
        )
    # 7. Retorna a nova estrutura com o total e a lista
    return {
        "total": total_eventos,
        "eventos": eventos
    }




@event.get('/list', status_code=HTTPStatus.OK, response_model=EventosPaginadosResponse) # <-- Atualize o schema aqui
async def listar_eventos(
    response: Response,
    session: Session,
    caches: Redis,
    pagin: Paginacao,
):
    # 1. Iniciamos as queries base (uma para os dados e outra para a contagem)
    query = select(Event).options(selectinload(Event.provincia), selectinload(Event.municipio)).order_by(Event.criado_as.desc())
    count_query = select(func.count()).select_from(Event) # Query limpa apenas para contar

    # 4. Executa a contagem TOTAL antes de aplicar a paginação
    total_eventos = await session.scalar(count_query) or 0

    # 5. Aplica a paginação APENAS na query que traz os dados dos eventos
    query = query.limit(pagin.limit).offset(pagin.skip)
    resultado = await session.scalars(query)
    eventos = resultado.all()

    # 6. Validação
    if not eventos:
        logger.warning('Nenhum evento encontrado.')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhum evento encontrado no sistema para estes critérios.',
        )

    # 7. Retorna a nova estrutura com o total e a lista
    return {
        "total": total_eventos,
        "eventos": eventos
    }



@event.get('/get/{id_event}', status_code=HTTPStatus.OK, response_model=EventResponse)
async def obter_evento(id_event: uuid.UUID, session: Session):
    """Endpoint para obter os detalhes de um evento específico pelo seu ID."""
    evento_banco = await session.scalar(select(Event).where(Event.id == id_event))
    if not evento_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Evento não encontrado')

    return evento_banco


@event.put('/upgrade/{id_event}', status_code=HTTPStatus.OK)
@limiter.limit('2/minute')
async def atualizar_evento(
    request: Request,
    schemas: UpgradeEvent,
    id_event: uuid.UUID,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):

    evento_banco = await session.scalar(select(Event).where(Event.id == id_event))
    if not evento_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Evento não encontrado')

    if scope.provincia_id and scope.provincia_id != evento_banco.provincia_id:
        logger.warning('Acesso negado: Você não gerencia o território deste evento.')
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território deste evento.'
        )

    provincia_banco = await session.scalar(select(Provincia).where(Provincia.nome_provincia == schemas.nome_provincia))

    if not provincia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')

    if scope.provincia_id and provincia_banco.id != scope.provincia_id:
        logger.warning('Admin %s esta a tentar atualizar dados fora da provincia permitida.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode criar eventos na sua provincia.'
        )

    municipio_banco = await session.scalar(
        select(Municipio).where(
            Municipio.nome_municipio == schemas.nome_municipio,
            Municipio.id_provincia == provincia_banco.id,
        )
    )

    if not municipio_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'O município "{schemas.nome_municipio}" não pertence à província "{schemas.nome_provincia}"',
        )

    if scope.municipio_id and municipio_banco.id != scope.municipio_id:
        logger.warning('Admin %s esta a tentar atualizar dados fora do seu município permitido.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode criar eventos no seu município.'
        )

    evento_banco.titulo = schemas.titulo
    evento_banco.descricao = schemas.descricao
    evento_banco.localizacao = schemas.localizacao
    evento_banco.data_inicio = schemas.data_inicio
    evento_banco.data_fim = schemas.data_fim
    evento_banco.provincia_id = provincia_banco.id
    evento_banco.municipio_id = municipio_banco.id
    evento_banco.max_participantes = schemas.max_participantes
    evento_banco.status = schemas.status

    try:
        await session.commit()
        await caches.delete(CACHE_KEY_LISTA)
        logger.info('Evento [%s] atualizado com sucesso por %s.', schemas.titulo, current_user.email)
        return {'msg': 'Evento atualizado com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao atualizar evento: [%s]', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Dados conflitantes ao atualizar o evento.',
        )


@event.delete('/delete/{id_event}', status_code=HTTPStatus.OK)
@limiter.limit('1/minute')
async def deletar_evento(
    request: Request,
    id_event: uuid.UUID,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):

    evento_banco = await session.scalar(select(Event).where(Event.id == id_event))
    if not evento_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Evento não encontrado')

    if scope.provincia_id and scope.provincia_id != evento_banco.provincia_id:
        logger.warning('Admin %s esta a tentar deletar dados fora da provincia permitida.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode deletar eventos na sua provincia.'
        )

    if scope.municipio_id and scope.municipio_id != evento_banco.municipio_id:
        logger.warning('Admin %s esta a tentar deletar dados fora do seu município permitido.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você só pode deletar eventos no seu município.'
        )

    imagem_evento_para_apagar = evento_banco.image_url
    try:
        await session.delete(evento_banco)
        await session.commit()
        logger.info('Evento %s deletado com sucesso.', id_event)
    except Exception as e:
        await session.rollback()
        logger.error('Erro ao deletar o evento %s: %s', id_event, str(e))
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Não foi possível deletar o evento devido a dependências ativas no banco.',
        )

    if imagem_evento_para_apagar:
        await apagar_imagem_evento_cloudinary(imagem_evento_para_apagar)

    await caches.delete(CACHE_KEY_LISTA)
    return {'msg': 'Evento deletado com sucesso!'}

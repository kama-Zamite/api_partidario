import logging
import re
import secrets
import unicodedata
import uuid
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Response,
    Request,
    UploadFile,
)
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from project_part.core.cloudinary_config import (
    apagar_imagem_noticia_cloudinary,
    upload_imagem_geral,
)
from project_part.core.setting import settings
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
    Municipio,
    Noticia,
    NoticiaCategoria,
    NoticiasStatusEnum,
    Provincia,
)

from .schemas import (
    CategoriaResponse,
    CreateCategoria,
    LimitNoticia,
    NoticiaResponse,
    UgradeStatusNoticia,
    UpgradeCategoria,
    UpgradeNoticia,
)

logger = logging.getLogger(__name__)


Redis = Annotated[AsyncRedis, Depends(get_redis)]
Session = Annotated[AsyncSession, Depends(get_session)]
Paginacao = Annotated[LimitNoticia, Depends()]
ScopeValid = Annotated[AdminScope, Depends(garante_escopo_territorial)]
FormatprimitiveInt = Annotated[int, Path(ge=1, description='ID deve ser um inteiro positivo')]

news_router = APIRouter(prefix='/news', tags=['News & Categories'])


CACHE_KEY_NOTICIAS = 'v1:noticias:lista'
CACHE_TTL_NOTICIAS = 3600 

ALLOWED_EXTENSIONS = {'jpg', 'jpeg'}
MAX_FILE_SIZE = 50 * 1024 * 1024


def gerar_slug_automatico(titulo: str) -> str:
    """
    Gera um slug a partir do título fornecido.
    Remove acentos, converte para minúsculas, substitui espaços por hífens e remove caracteres especiais.
    """
    texto = titulo.lower()
    texto_normalizado = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-zA-Z0-9]', '-', texto_normalizado)
    slug_limpo = re.sub(r'-+', '-', slug).strip('-')
    return slug_limpo


async def gerar_slug_unico(slug_base: str, session: Session) -> str:
    """
    Gera um slug único baseado no slug_base fornecido.
    Se o slug_base já existir no banco de dados, adiciona um sufixo numérico para torná-lo único.
    """
    query = select(Noticia).where(Noticia.slug == slug_base)
    resultado = await session.scalar(query)
    if not resultado:
        return slug_base

    sufixo_aleatorio = secrets.token_hex(2)
    slug_unico = f'{slug_base}-{sufixo_aleatorio}'
    return slug_unico


@news_router.post('/categories/create', status_code=HTTPStatus.CREATED)
@limiter.limit('2/minute')
async def criar_categoria(
    request: Request,
    schemas: CreateCategoria,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    logger.info('Criando categoria de notícia: %s por %s', schemas.name, current_user.email)

    verificar_permissao_global_pais(scope, current_user)

    nova_categoria = NoticiaCategoria(name=schemas.name)
    try:
        session.add(nova_categoria)
        await session.commit()
        await caches.delete(CACHE_KEY_CATEGORIAS)
        return {'msg': 'Categoria criada com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao criar categoria: %s', str(e.orig))
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail='Já existe uma categoria cadastrada com este nome.')


# @news_router.get('/categories/list', status_code=HTTPStatus.OK, response_model=List[CategoriaResponse])
# async def listar_categorias(response: Response, session: Session, caches: Redis, current_user: Get_current_user):
#     try:
#         cache_salvo = await caches.get(CACHE_KEY_CATEGORIAS)
#         if cache_salvo:
#             response.headers['X-Cache-Hit'] = 'true'
#             return json.loads(cache_salvo)
#     except Exception as err:
#         logger.error("Falha ao ler cache de categorias: %s", str(err))

#     query = select(NoticiaCategoria).options(selectinload(NoticiaCategoria.noticias))
#     query = query.order_by(NoticiaCategoria.name.asc())
#     resultado = await session.scalars(query)
#     categorias = resultado.all()
#     if not categorias:
#         logger.warning('Nenhuma categoria cadastrada no banco de dados.')
#         raise HTTPException(
#             status_code=HTTPStatus.NOT_FOUND,
#             detail='Nenhuma categoria encontrada no sistema.',
#         )

#     adapter = TypeAdapter(List[CategoriaResponse])
#     dados_serializados = adapter.dump_python(categorias, mode='json')

#     try:
#         await caches.setex(CACHE_KEY_CATEGORIAS, 3600, json.dumps(dados_serializados))
#         response.headers['X-Cache-Hit'] = 'false'
#     except Exception as err:
#         logger.error("Falha ao salvar cache de categorias: %s", str(err))

#     return dados_serializados


@news_router.post('/create', status_code=HTTPStatus.CREATED)
@limiter.limit('3/minute')
async def criar_noticia(
    request: Request,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
    titulo: str = Form(..., min_length=10),
    subtitulo: Optional[str] = Form(None, min_length=20, max_length=255),
    lead: Optional[str] = Form(None),
    corpo: str = Form(min_length=20),
    image_news: Optional[UploadFile] = File(None, description='Foto de perfil opcional (JPEG/JPG, max 5MB)'),
    categoria_id: int = Form(gt=0),
    nome_provincia: Optional[str] = Form(None, min_length=4),
    nome_municipio: Optional[str] = Form(None, min_length=4),
    status: NoticiasStatusEnum = Form(default=NoticiasStatusEnum.RASCUNHO),
):
    """
    Publica uma nova notícia vinculando de forma geográfica e assíncrona a imagem à pasta noticias_portal no Cloudinary.
    """
    pid = None
    mid = None

    slug_inicial = gerar_slug_automatico(titulo)
    slug_gerado = await gerar_slug_unico(slug_inicial, session)

    try:
        dados_validos = UpgradeNoticia(
            titulo=titulo,
            slug=slug_gerado,
            subtitulo=subtitulo,
            lead=lead,
            corpo=corpo,
            categoria_id=categoria_id,
            nome_provincia=nome_provincia,
            nome_municipio=nome_municipio,
            status=status,
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY, detail=e.errors(include_url=False, include_context=False)
        )

    categoria_banco = await session.scalar(
        select(NoticiaCategoria).where(NoticiaCategoria.id == dados_validos.categoria_id)
    )
    if not categoria_banco:
        logger.warning('Categoria [%d] nao foi encontrada.', dados_validos.categoria_id)
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Categoria nao encontrada')

    if scope.provincia_id or scope.municipio_id:
        if not dados_validos.nome_provincia or not dados_validos.nome_municipio:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Administradores territoriais precisam informar obrigatoriamente a província e o município da notícia.',
            )

    if dados_validos.nome_provincia:
        logger.info('Buscando a província da notícia: %s', dados_validos.nome_provincia)
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == dados_validos.nome_provincia)
        )
        if not provincia_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província informada não encontrada')

        pid = provincia_banco.id

        if scope.provincia_id and pid != scope.provincia_id:
            logger.warning(
                'Admin provincial %s impedido de criar em %s.', current_user.id, dados_validos.nome_provincia
            )
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Acesso negado: Você só pode criar notícias vinculadas à sua província permitida.',
            )

        logger.info('Buscando o município da notícia: %s', dados_validos.nome_municipio)
        municipio_banco = await session.scalar(
            select(Municipio).where(
                Municipio.nome_municipio == dados_validos.nome_municipio, Municipio.id_provincia == pid
            )
        )
        if not municipio_banco:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'O município "{dados_validos.nome_municipio}" não pertence à província "{dados_validos.nome_provincia}".',
            )

        mid = municipio_banco.id

        # if scope.municipio_id and mid != scope.municipio_id:
        #     logger.warning('Admin municipal %s impedido de criar em %s.', current_user.id, dados_validos.nome_municipio)
        #     raise HTTPException(
        #         status_code=HTTPStatus.FORBIDDEN,
        #         detail='Acesso negado: Você só pode criar notícias vinculadas ao seu município.',
        #     )

    nova_noticia = Noticia(
        titulo=dados_validos.titulo,
        slug=dados_validos.slug,
        subtitulo=dados_validos.subtitulo,
        lead=dados_validos.lead,
        corpo=dados_validos.corpo,
        image_url=None,
        categoria_id=dados_validos.categoria_id,
        autor_id=current_user.id,
        provincia_id=pid,
        municipio_id=mid,
        status=dados_validos.status,
    )

    try:
        session.add(nova_noticia)
        await session.flush()

        if image_news:
            extensao = image_news.filename.split('.')[-1].lower()
            if extensao not in {'jpg', 'jpeg'}:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail='Formato de imagem inválido. Use apenas PNG, JPG, JPEG ou WEBP.',
                )

            conteudo_byte = await image_news.read()
            if len(conteudo_byte) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST, detail='A foto de perfil não pode ser maior que 5MB.'
                )

            try:
                url_secure = await upload_imagem_geral(
                    file_bytes=conteudo_byte,
                    identificador=str(nova_noticia.id),
                    pasta_alvo='noticias_portal',
                    prefixo_arquivo='news',
                )
                nova_noticia.image_url = url_secure
            except Exception as e:
                logger.error('Falha ao subir imagem para o Cloudinary: %s', e)
                raise HTTPException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    detail='Falha ao salvar imagem de perfil no serviço de nuvem.',
                )
            finally:
                await image_news.close()

        await session.commit()
        await caches.delete(CACHE_KEY_NOTICIAS)
        logger.info('Notícia [%s] publicada com sucesso por %s.', dados_validos.titulo, current_user.email)
        return {
            'msg': 'Noticia criado com sucesso com validações de segurança!',
            'noticia_id': str(nova_noticia.id),
            'image_url': nova_noticia.image_url,
        }
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao criar notícia: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Erro de integridade. Verifique se o slug já existe ou se a amarração do banco está corrompida.',
        )


# @news_router.get('/list', status_code=HTTPStatus.OK)
# async def listar_noticias(response: Response, session: Session, caches: Redis, pagin: Paginacao):
#     """
#     Endpoint para listar notícias com paginação.
#     - **limit**: Número máximo de notícias a serem retornadas (padrão: 10).
#     - **skip**: Número de notícias a serem ignoradas (padrão: 0).
#     Retorna uma lista de notícias com base nos parâmetros fornecidos.
#     """
#     chave_cache = f"{CACHE_KEY_NOTICIAS}:lm:{pagin.limit}:sk:{pagin.skip}"

#     try:
#         cache_salvo = await caches.get(chave_cache)
#         if cache_salvo:
#             response.headers['X-Cache-Hit'] = 'true'
#             return json.loads(cache_salvo)
#     except Exception as err:
#         logger.error("Falha ao ler cache de notícias: %s", str(err))


#     query = select(
#             Noticia
#         ).options(
#             selectinload(Noticia.provincia),
#             selectinload(Noticia.municipio)
#         ).order_by(
#             Noticia.creado_as.desc()
#         ).limit(
#             pagin.limit
#         ).offset(
#             pagin.skip
#         )


#     resultado = await session.scalars(query)
#     noticias = resultado.all()

#     if not noticias:
#         raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Nenhuma notícia encontrada no sistema.')

#     adapter = TypeAdapter(List[NoticiaResponse])
#     dados_serializados = adapter.dump_python(noticias, mode='json')

#     try:
#         await caches.setex(chave_cache, 60, json.dumps(dados_serializados))
#         response.headers['X-Cache-Hit'] = 'false'
#     except Exception as err:
#         logger.error("Falha ao salvar cache de notícias: %s", str(err))

#     return dados_serializados

@news_router.get(
    '/list',
    status_code=HTTPStatus.OK,
    response_model=List[NoticiaResponse],
)
async def listar_noticias(
    response: Response,
    session: Session,
    redes: Redis,
    pagin: Paginacao,
):
    """
    Endpoint de alta performance para listar notícias com paginação.
    Utiliza cache Redis com chave parametrizada por skip/limit.
    """
    cache_key = f"{CACHE_KEY_NOTICIAS}:skip={pagin.skip}:limit={pagin.limit}"
    response.headers['X-Cache-Hit'] = 'false'

    # ── 1. Tenta ler do cache ──────────────────────────────────────────────
    try:
        cached = await redes.get(cache_key)
        if cached:
            response.headers['X-Cache-Hit'] = 'true'
            logger.info("Cache de notícias [%s] encontrado e retornado.", cache_key)
            return TypeAdapter(List[NoticiaResponse]).validate_python(
                json.loads(cached)
            )
    except Exception as err:
        logger.error("Falha ao ler cache de notícias [%s]: %s", cache_key, err)

    # ── 2. Busca no banco ──────────────────────────────────────────────────
    query = (
        select(Noticia)
        .options(
            selectinload(Noticia.provincia),
            selectinload(Noticia.municipio),
            selectinload(Noticia.categoria),
        )
        .order_by(Noticia.publicado_as.desc())
        .limit(pagin.limit)
        .offset(pagin.skip)
    )

    result = await session.execute(query)
    noticias = result.scalars().all()

    if not noticias:
        return []

    # ── 3. Serializa e grava no cache ──────────────────────────────────────
    try:
        # 1. Converte ORM → Pydantic (com from_attributes=True)
        noticias_response = TypeAdapter(List[NoticiaResponse]).validate_python(noticias)

        # 2. Gera dicts JSON-serializáveis
        payload = TypeAdapter(List[NoticiaResponse]).dump_python(
            noticias_response, mode='json'
        )

        await redes.set(
            cache_key,
            json.dumps(payload),
            ex=CACHE_TTL_NOTICIAS,
        )
    except Exception as err:
        logger.error("Falha ao gravar cache de notícias [%s]: %s", cache_key, err)
    logger.info("Notícias [%d] carregadas do banco e cache atualizado.", len(noticias))
    return noticias

@news_router.get('/{id_news}', status_code=HTTPStatus.OK, response_model=NoticiaResponse)
async def obter_noticia(id_news: int, session: Session):
    """ "
    Endpoint para obter os detalhes de uma notícia específica por ID.
    Retorna os detalhes da notícia solicitada ou um erro 404 se não for encontrada.
    """
    noticia_banco = await session.scalar(select(Noticia).where(Noticia.id == id_news))
    if not noticia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Notícia não encontrada')

    adapter = TypeAdapter(NoticiaResponse)
    return adapter.dump_python(noticia_banco, mode='json')


@news_router.patch('/{id_news}/status', status_code=HTTPStatus.OK)
@limiter.limit('1/minute')
async def atualizar_status_noticia(
    request: Request,
    id_news: int,
    status: UgradeStatusNoticia,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    noticia_banco = await session.scalar(select(Noticia).where(Noticia.id == id_news))
    if not noticia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Notícia não encontrada')

    if scope.provincia_id and scope.provincia_id != noticia_banco.provincia_id:
        logger.warning('Admin %s bloqueado de atualizar status de notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )
    if scope.municipio_id and scope.municipio_id != noticia_banco.municipio_id:
        logger.warning('Admin %s bloqueado de atualizar status de notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )

    noticia_banco.status = status.nome
    noticia_banco.atualizado_as = datetime.now(timezone.utc())

    try:
        await session.commit()
        await caches.delete(CACHE_KEY_NOTICIAS)
        logger.info(
            'Status da notícia [%s] atualizado para [%s] por %s.', noticia_banco.titulo, status.nome, current_user.email
        )
        return {'msg': 'Status da notícia atualizado com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao atualizar status da notícia: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Erro de integridade ao atualizar o status da notícia.',
        )


@news_router.put('/{id_news}', status_code=HTTPStatus.OK)
@limiter.limit('1/minute')
async def atualizar_noticia_completa(
    request: Request,
    id_news: int,
    schemas: UpgradeNoticia,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """Endpoint para atualizar completamente os detalhes de uma notícia específica.
    Verifica se a notícia existe, se o administrador tem permissão para atualizar a notícia com base no território e se as novas amarrações de província/município são válidas.
    Se todas as validações passarem, atualiza os detalhes da notícia e retorna uma mensagem de sucesso. Caso contrário, retorna o erro apropriado.
    """
    noticia_banco = await session.scalar(select(Noticia).where(Noticia.id == id_news))
    if not noticia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Notícia não encontrada')

    if scope.provincia_id and scope.provincia_id != noticia_banco.provincia_id:
        logger.warning('Admin %s bloqueado de atualizar notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )
    if scope.municipio_id and scope.municipio_id != noticia_banco.municipio_id:
        logger.warning('Admin %s bloqueado de atualizar notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )

    noticia_banco.titulo = schemas.titulo
    noticia_banco.slug = schemas.slug
    noticia_banco.subtitulo = schemas.subtitulo
    noticia_banco.lead = schemas.lead
    noticia_banco.corpo = schemas.corpo
    noticia_banco.image_url = schemas.image_url
    noticia_banco.categoria_id = schemas.categoria_id
    noticia_banco.status = schemas.status
    noticia_banco.atualizado_as = datetime.now(timezone.utc())

    pid = None
    if schemas.nome_provincia:
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == schemas.nome_provincia)
        )
        if not provincia_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província informada não encontrada')

        pid = provincia_banco.id

        if scope.provincia_id and pid != scope.provincia_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Acesso negado: Nova província informada está fora da sua zona permitida.',
            )
    mid = None
    if schemas.nome_municipio:
        municipio_banco = await session.scalar(
            select(Municipio).where(Municipio.nome_municipio == schemas.nome_municipio, Municipio.id_provincia == pid)
        )
        if not municipio_banco:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'O município "{schemas.nome_municipio}" não pertence à província "{schemas.nome_provincia}".',
            )

        mid = municipio_banco.id

        if scope.municipio_id and mid != scope.municipio_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Acesso negado: Novo município informado está fora da sua zona permitida.',
            )
        noticia_banco.municipio_id = mid
    noticia_banco.provincia_id = pid
    try:
        await session.commit()
        await caches.delete(CACHE_KEY_NOTICIAS)
        logger.info('Notícia [%s] modificada com sucesso por %s.', schemas.titulo, current_user.email)
        return {'msg': 'Notícia atualizada com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao atualizar notícia: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Conflito de dados ao atualizar a notícia. Verifique unicidade de campos como o slug.',
        )


@news_router.delete('/{id_news}', status_code=HTTPStatus.OK)
@limiter.limit('2/minute')
async def eliminar_noticia(
    request: Request,
    id_news: uuid.UUID,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """Endpoint para deletar uma notícia específica.
    Verifica se a notícia existe e se o administrador tem permissão para deletar a notícia com base no território.
    Se todas as validações passarem, deleta a notícia e retorna uma mensagem de sucesso. Caso contrário, retorna o erro apropriado.
    """
    noticia_banco = await session.scalar(select(Noticia).where(Noticia.id == id_news))
    if not noticia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Notícia não encontrada')

    if scope.provincia_id and scope.provincia_id != noticia_banco.provincia_id:
        logger.warning('Admin %s bloqueado de deletar notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )
    if scope.municipio_id and scope.municipio_id != noticia_banco.municipio_id:
        logger.warning('Admin %s bloqueado de deletar notícia de outro território.', current_user.id)
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado: Você não gerencia o território desta notícia.'
        )

    imagem_para_apagar = noticia_banco.image_url
    try:
        await session.delete(noticia_banco)
        await session.commit()
        logger.info('Notícia [%s] deletada com sucesso por %s.', noticia_banco.titulo, current_user.email)
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao deletar a notícia: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Erro de integridade ao deletar a notícia.',
        )
    except Exception as e:
        await session.rollback()
        logger.critical('Erro catastrófico ao deletar a notícia: %s', str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento no servidor.',
        )
    if imagem_para_apagar:
        await apagar_imagem_noticia_cloudinary(imagem_para_apagar)

    await caches.delete(CACHE_KEY_NOTICIAS)
    return {'msg': 'Notícia deletada com sucesso!'}

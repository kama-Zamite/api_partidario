import json
import logging
import uuid
from http import HTTPStatus
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import TypeAdapter
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from project_part.core.secury import (
    Get_current_user,
    garante_escopo_territorial,
    verificar_permissao_global_pais,
)
from project_part.db.cache import get_redis
from project_part.db.session import get_session
from project_part.model.models import AdminScope, Municipio, Provincia

from .schemas import (
    CreateMunicipio,
    CreateProvincia,
    DeleteMunicipio,
    FindProvincia,
    ResponseProvincia,
    UpgradeMunicipio,
)

Session = Annotated[AsyncSession, Depends(get_session)]
Redis = Annotated[AsyncRedis, Depends(get_redis)]

ScopeValid = Annotated[AdminScope, Depends(garante_escopo_territorial)]

logger = logging.getLogger(__name__)
provincia = APIRouter(prefix='/provincia', tags=['Provincia & Municipio'])

CACHE_KEY_PROVINCIAS = 'v2:provincia:listar'


@provincia.post('/create', status_code=HTTPStatus.CREATED, response_model=ResponseProvincia)
async def create_provincia(
    schemas: CreateProvincia, session: Session, redis: Redis,
    # current_user: Get_current_user, scope: ScopeValid
):

    # verificar_permissao_global_pais(scope, current_user)

    nova_provincia = Provincia(nome_provincia=schemas.nome_provincia)

    try:
        session.add(nova_provincia)
        await session.commit()

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Cache de listagem de províncias invalidado.')

        await session.refresh(nova_provincia)
        return {
            'id': nova_provincia.id,
            'nome_provincia': nova_provincia.nome_provincia,
            'municipio': [],
        }
    except IntegrityError:
        await session.rollback()
        logger.error('Falha ao cadastrar província: Nome [%s] duplicado.', schemas.nome_provincia)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Erro na solicitação: Esta província já está cadastrada no sistema.',
        )


@provincia.post('/municipio/create', status_code=HTTPStatus.CREATED)
async def criar_municipio(
    schemas: CreateMunicipio, session: Session, redis: Redis,
    # current_user: Get_current_user, scope: ScopeValid
):
    # verificar_permissao_global_pais(scope, current_user)

    logger.info('Buscando província vinculada no PostgreSQL: %s', schemas.nome_provincia)
    pegar_provincia = await session.scalar(select(Provincia).where(Provincia.nome_provincia == schemas.nome_provincia))

    if not pegar_provincia:
        logger.warning('Província informada não existe: %s', schemas.nome_provincia)
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província informada não encontrada.')

    novo_municipio = Municipio(
        nome_municipio=schemas.nome_municipio,
        id_provincia=pegar_provincia.id,
    )

    try:
        session.add(novo_municipio)
        await session.commit()

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Município %s cadastrado com sucesso e caches limpos.', schemas.nome_municipio)
        return {'msg': 'Município criado com sucesso!'}
    except IntegrityError:
        await session.rollback()
        logger.error('Erro de integridade: Município [%s] já existe nesta província.', schemas.nome_municipio)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail=f'O município "{schemas.nome_municipio}" já está cadastrado nesta província.',
        )


@provincia.get('/list', status_code=HTTPStatus.OK, response_model=List[ResponseProvincia])
async def listar_provincias(response: Response, session: Session, redis: Redis, current_user: Get_current_user):
    try:
        provincia_salva = await redis.get(CACHE_KEY_PROVINCIAS)
        if provincia_salva:
            response.headers['X-Cache-Hit'] = 'true'
            return json.loads(provincia_salva)
    except Exception as e:
        logger.error('Falha ao ler cache do Redis: %s', str(e))

    logger.info('Buscando dados geográficos direto no PostgreSQL...')
    resultado = await session.scalars(select(Provincia).options(selectinload(Provincia.municipio)))
    provincias_all = resultado.all()

    if not provincias_all:
        logger.warning('Nenhuma província cadastrada no banco de dados.')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhuma província encontrada no sistema.',
        )

    try:
        adaptador = TypeAdapter(List[ResponseProvincia])
        dados_serializados = adaptador.dump_python(provincias_all, mode='json')
        await redis.setex(CACHE_KEY_PROVINCIAS, 43200, json.dumps(dados_serializados))
        logger.info('Cache de províncias renovado com sucesso.')
    except Exception as e:
        logger.error('Não foi possível salvar os caches no Redis: %s', str(e))

    response.headers['X-Cache-Hit'] = 'false'
    return provincias_all


@provincia.put('/upgrade/{id_provincia}', status_code=HTTPStatus.OK, response_model=ResponseProvincia)
async def atualizar_provincia(
    id_provincia: uuid.UUID,
    schemas: FindProvincia,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    verificar_permissao_global_pais(scope, current_user)

    up_provincia = await session.scalar(
        select(Provincia).where(Provincia.id == id_provincia).options(selectinload(Provincia.municipio))
    )

    if not up_provincia:
        logger.warning('Província %s não encontrada para atualização.', id_provincia)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Província não encontrada.',
        )

    up_provincia.nome_provincia = schemas.novo_nome
    try:
        session.add(up_provincia)
        await session.commit()
        await session.refresh(up_provincia)

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Província [%s] atualizada com sucesso e cache limpo.', up_provincia.nome_provincia)

        return up_provincia
    except IntegrityError:
        await session.rollback()
        logger.error('Falha ao atualizar província: Nome [%s] já existe.', schemas.novo_nome)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Erro: Já existe uma província cadastrada com este nome.',
        )


@provincia.delete('/delete/{id_provincia}', status_code=HTTPStatus.OK)
async def eliminar_provincia(
    id_provincia: uuid.UUID, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):
    verificar_permissao_global_pais(scope, current_user)

    del_provincia = await session.scalar(select(Provincia).where(Provincia.id == id_provincia))

    if not del_provincia:
        logger.warning('Província %s não encontrada para exclusão.', id_provincia)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Província não encontrada.',
        )

    try:
        await session.delete(del_provincia)
        await session.commit()

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Província %s e seus municípios vinculados foram excluídos com sucesso.', id_provincia)
        return {'msg': 'Província deletada com sucesso!'}
    except IntegrityError:
        await session.rollback()
        logger.error('Erro de integridade ao deletar província %s. Existem restrições ativas.', id_provincia)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Não é possível deletar esta província pois ela possui dependências ativas no sistema.',
        )


@provincia.put('/municipio/upgrade/{id_municipio}', status_code=HTTPStatus.OK)
async def atualizar_municipio(
    id_municipio: uuid.UUID,
    schemas: UpgradeMunicipio,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    verificar_permissao_global_pais(scope, current_user)

    logger.info('Buscando a província informada: %s', schemas.nome_provincia)
    provincia_banco = await session.scalar(select(Provincia).where(Provincia.nome_provincia == schemas.nome_provincia))

    if not provincia_banco:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província informada não encontrada.')

    logger.info('Buscando o município pelo ID: %s', id_municipio)
    municipio_atualizar = await session.scalar(select(Municipio).where(Municipio.id == id_municipio))

    if not municipio_atualizar:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Município não encontrado no sistema.',
        )

    municipio_atualizar.nome_municipio = schemas.novo_nome_municipio
    municipio_atualizar.id_provincia = provincia_banco.id

    try:
        session.add(municipio_atualizar)
        await session.commit()

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Município %s atualizado com sucesso.', id_municipio)

        return {
            'msg': f'Município atualizado para "{schemas.novo_nome_municipio}" na província de {schemas.nome_provincia} com sucesso!'
        }
    except IntegrityError:
        await session.rollback()
        logger.error('Erro de integridade: Nome [%s] já existe na província.', schemas.novo_nome_municipio)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='Já existe um município cadastrado com este nome dentro da província indicada.',
        )


@provincia.delete('/municipio/delete/{id_municipio}', status_code=HTTPStatus.OK)
async def eliminar_municipio(
    id_municipio: uuid.UUID,
    schemas: DeleteMunicipio,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):

    verificar_permissao_global_pais(scope, current_user)

    logger.info('Buscando município %s direto na tabela...', id_municipio)
    deletar_municipio = await session.scalar(select(Municipio).where(Municipio.id == id_municipio))

    if not deletar_municipio:
        logger.warning('Município %s não encontrado no sistema.', id_municipio)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Município não encontrado no sistema.',
        )

    try:
        await session.delete(deletar_municipio)
        await session.commit()

        await redis.delete(CACHE_KEY_PROVINCIAS)
        logger.info('Município deletado com sucesso e cache geral invalidado.')

        return {'msg': 'Município deletado com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao deletar município: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Não foi possível deletar o município devido a dependências ou registros vinculados (ex: eventos ativos).',
        )


@provincia.get('/list/{id_provincia}', status_code=HTTPStatus.OK, response_model=ResponseProvincia)
async def lista_provincia(
    id_provincia: uuid.UUID, response: Response, session: Session, redis: Redis, current_user: Get_current_user
):

    chave_cache_provincia = f'v2:provincia:{id_provincia}:detalhe'

    try:
        provincia_salva = await redis.get(chave_cache_provincia)
        if provincia_salva:
            response.headers['X-Cache-Hit'] = 'true'
            logger.info('Dados da província vindos do Redis.')
            return json.loads(provincia_salva)
    except Exception as e:
        logger.error('Falha ao ler cache individual do Redis: %s', str(e))

    logger.info('Buscando dados da província %s no PostgreSQL...', id_provincia)
    provincia_banco = await session.scalar(
        select(Provincia).where(Provincia.id == id_provincia).options(selectinload(Provincia.municipios))
    )

    if not provincia_banco:
        logger.warning('Província %s não encontrada.', id_provincia)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Província não encontrada no sistema.',
        )

    try:
        adaptador = TypeAdapter(ResponseProvincia)
        dados_serializados = adaptador.dump_python(provincia_banco, mode='json')

        await redis.setex(chave_cache_provincia, 3600, json.dumps(dados_serializados))

        logger.info('Cache individual da província guardado com sucesso!')
        response.headers['X-Cache-Hit'] = 'false'
        return dados_serializados
    except Exception as e:
        logger.error('Não foi possível guardar o cache individual no Redis: %s', str(e))

    response.headers['X-Cache-Hit'] = 'false'
    return provincia_banco

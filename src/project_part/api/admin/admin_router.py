import asyncio
import io
import json
import logging
import secrets
import uuid
from datetime import (
    datetime,
    timezone,
    timedelta,
    date
)
from http import HTTPStatus
from typing import Annotated, List, Optional
from calendar import month_abbr
import qrcode
from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Response,
    Path,
)
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import func, select, extract, or_, case
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from project_part.core.cloudinary_config import upload_imagem_geral
from project_part.core.secury import (
    Get_current_user,
    garante_escopo_territorial,
    verificar_permissao_global_pais,
)
from project_part.db.cache import get_redis
from project_part.db.session import get_session
from project_part.model.models import (
    AdminScope,
    AuditLog,
    CadastrarComo,
    CartaoMilitante,
    Municipio,
    Notification,
    Provincia,
    Role,
    SolicitacaoCartao,
    SolicitacaoMilitancia,
    MensagemSuporte,
    StatusSolicitacao,
    User,
    Genero,
)

from .schemas import (
    CreateAdminScope,
    PaginatedAuditLogs,
    ResponseAdminScope,
    NotificationResponse,
    NotificationListResponse,
    MensagensSuportePaginadasResponse,
    RegistrosRecentes,
    CardSolicitante,
    ValidarFilterSimpatizante,
    DistribuicaoGenero,
    )

logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]
Redis = Annotated[AsyncRedis, Depends(get_redis)]
ScopeValid = Annotated[AdminScope, Depends(garante_escopo_territorial)]

admin = APIRouter(prefix='/admin', tags=['Admin Management'])


@admin.post('/set-scope', status_code=HTTPStatus.CREATED)
async def criar_scope(
    schema: CreateAdminScope, session: Session, redis: Redis,
    #   current_user: Get_current_user, scope: ScopeValid
):
    """
    Define ou atualiza o escopo geográfico de atuação de um administrador.
    Apenas administradores de nível superior podem delegar permissões regionais.
    """
    provincia_banco = None
    municipio_banco = None

    if schema.nome_provincia:
        logger.info('A procurar a província: %s', schema.nome_provincia)
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == schema.nome_provincia)
        )
        if not provincia_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')

    if schema.nome_municipio:
        if not provincia_banco:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST, detail='Para indicar um município, informe também a província.'
            )

        logger.info('A procurar o município: %s dentro da província %s', schema.nome_municipio, schema.nome_provincia)
        municipio_banco = await session.scalar(
            select(Municipio).where(
                Municipio.nome_municipio == schema.nome_municipio,
                Municipio.id_provincia == provincia_banco.id,
            )
        )
        if not municipio_banco:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'O município "{schema.nome_municipio}" não pertence à província "{schema.nome_provincia}"',
            )

    # if scope.municipio_id is not None:
    #     logger.info('Admins municipais não podem delegar novos escopos.')
    #     raise HTTPException(
    #         status_code=HTTPStatus.FORBIDDEN, detail='Admins municipais não podem delegar novos escopos.'
    #     )
    # if scope.provincia_id is not None:
    #     if provincia_banco and provincia_banco.id != scope.provincia_id:
    #         logger.info('Você só pode delegar escopos dentro da sua província.')
    #         raise HTTPException(
    #             status_code=HTTPStatus.FORBIDDEN, detail='Você só pode delegar escopos dentro da sua província.'
    #         )

    logger.info('Buscar usuario: "%s" no banco de dados..', schema.email)
    user_base = await session.scalar(select(User).where(User.email == schema.email))

    if not user_base:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=f'Usuário: {schema.email} não encontrado!')

    target_role_name = await session.scalar(select(Role.nome).where(Role.id == user_base.role_id))
    if target_role_name != 'admin':
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="O usuário alvo precisa ser um 'admin' antes de receber um escopo.",
        )

    scopo_existente = await session.scalar(select(AdminScope).where(AdminScope.user_id == user_base.id))

    id_provincia_final = provincia_banco.id if provincia_banco else None
    id_municipio_final = municipio_banco.id if municipio_banco else None

    if scopo_existente:
        logger.info('Atualizar o scope do usuario %s', schema.email)
        scopo_existente.provincia_id = id_provincia_final
        scopo_existente.municipio_id = id_municipio_final
        scopo_existente.user = user_base
        novo_escopo = scopo_existente
    else:
        logger.info('adicionando scope ao user %s', schema.email)
        novo_escopo = AdminScope(
            provincia_id=id_provincia_final, municipio_id=id_municipio_final, user_id=user_base.id, user=user_base
        )

    try:
        session.add(novo_escopo)
        await session.commit()

        await redis.incr('v1:admin:scope:versao')
        await redis.incr('v1:usuarios:lista:versao')

        return {'msg': 'Escopo administrativo configurado com sucesso!'}
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao salvar escopo: %s', str(e.orig))
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail='Erro de integridade no banco de dados')


@admin.get(
    '/scope/list',
    status_code=HTTPStatus.OK,
    response_model=list[ResponseAdminScope],
)
async def listar_admin_scope(
    response: Response,
    session: Session,
    redis: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """
    Lista os escopos geográficos cadastrados.
    Admins regionais só visualizam os escopos
    pertencentes à sua própria área geográfica.
    """

    try:
        versao_cache = await redis.get(
            'v1:admin:scope:versao'
        ) or b'1'

        versao_cache = (
            versao_cache.decode('utf-8')
            if isinstance(versao_cache, bytes)
            else str(versao_cache)
        )

    except Exception as e:
        logger.error(
            'Falha ao ler versão do cache: %s',
            e,
        )
        versao_cache = 'fallback'

    cache_key = (
        f'v1:admin:scope:list:'
        f'{current_user.id}:v:{versao_cache}'
    )

    # ---------------------------------------------------------
    # Redis
    # ---------------------------------------------------------

    try:
        scope_save = await redis.get(cache_key)

        if scope_save:
            response.headers['X-Caches-lock'] = (
                'Dados vindo do Redis'
            )

            return json.loads(scope_save)

    except Exception as e:
        logger.error(
            'Erro na solicitação dos dados do Redis: %s',
            e,
        )

    # ---------------------------------------------------------
    # PostgreSQL
    # ---------------------------------------------------------

    query = (
        select(AdminScope)
        .options(
            selectinload(AdminScope.user),
            selectinload(AdminScope.provincia),
            selectinload(AdminScope.municipio),
        )
    )

    if scope.provincia_id is not None:
        query = query.where(
            AdminScope.provincia_id == scope.provincia_id
        )

    if scope.municipio_id is not None:
        query = query.where(
            AdminScope.municipio_id == scope.municipio_id
        )

    scope_base = await session.scalars(query)
    scope_all = scope_base.all()

    if not scope_all:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail='Nenhum escopo encontrado nesta região.',
        )

    # ---------------------------------------------------------
    # Conversão
    # ---------------------------------------------------------

    resultado = []

    for admin_scope in scope_all:

        usuario = admin_scope.user

        resultado.append(
            ResponseAdminScope(
                user_id=admin_scope.user_id,

                nome_completo=usuario.nome_completo,
                email=usuario.email,
                data_nascimento=usuario.data_nascimento,
                militante_numero=usuario.militante_numero,
                telefone=usuario.telefone,
                genero=usuario.genero,
                estado_civil=usuario.estado_civil,
                foi_militante=usuario.foi_militante,

                # Se não existir relacionamento,
                # retorna None em vez de provocar AttributeError.
                nome_provincia=(
                    admin_scope.provincia.nome_provincia
                    if admin_scope.provincia is not None
                    else None
                ),

                nome_municipio=(
                    admin_scope.municipio.nome_municipio
                    if admin_scope.municipio is not None
                    else None
                ),

                ativo=usuario.ativo,
            )
        )

    # ---------------------------------------------------------
    # Redis
    # ---------------------------------------------------------

    try:
        list_json_string = json.dumps(
            [
                item.model_dump(mode='json')
                for item in resultado
            ]
        )

        await redis.set(
            cache_key,
            list_json_string,
            ex=60,
        )

    except Exception as e:
        logger.error(
            'Não foi possível guardar o cache no Redis: %s',
            e,
        )

    response.headers['X-Caches-lock'] = (
        'Dados vindo do PostgreSQL'
    )

    return resultado



@admin.get('/militantes-registrados', status_code=HTTPStatus.OK)
async def militantes_registrados(
    scope: ScopeValid,
    current_user: Get_current_user,
    session: Session
):
    """
    Retorna o total de militantes cadastrados.
    1. Superadmin → retorna o total de militantes cadastrados em todo o país.
    2. Admin Provincial → retorna o total de militantes cadastrados na sua província.
    3. Admin Municipal → acesso negado (não pode acessar totais). 
    """
    logger.info(
        "Validar permissão do usuário %s para acessar o total de militantes registrados",
        current_user.id
    )

    if scope.municipio_id is not None:
        logger.warning(
            "Acesso negado: Usuário %s (município) não tem permissão",
            current_user.id
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Acesso negado: Você não tem permissão para acessar o total de militantes registrados."
        )

    logger.info("Buscando total de militantes na base de dados")

    query = select(func.count(User.id)).where(
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.MILITANTE
    )

    if scope.provincia_id is not None:
        logger.info("Filtrando por província %s", scope.provincia_id)
        query = query.where(User.provincia_id == scope.provincia_id)

    total = await session.scalar(query)

    return {
        'total': total or 0
    }


@admin.get('/simpatizantes-registrados', status_code=HTTPStatus.OK)
async def simpatizantes_registrados(
    scope: ScopeValid,
    current_user: Get_current_user,
    session: Session
):
    """
    Retorna o total de militantes cadastrados.
    1. Superadmin → retorna o total de militantes cadastrados em todo o país.
    2. Admin Provincial → retorna o total de militantes cadastrados na sua província.
    3. Admin Municipal → acesso negado (não pode acessar totais). 
    """
    logger.info(
        "Validar permissão do usuário %s para acessar o total de militantes registrados",
        current_user.id
    )

    if scope.municipio_id is not None:
        logger.warning(
            "Acesso negado: Usuário %s (município) não tem permissão",
            current_user.id
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Acesso negado: Você não tem permissão para acessar o total de militantes registrados."
        )

    logger.info("Buscando total de militantes na base de dados")

    query = select(func.count(User.id)).where(
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.SIMPATIZANTE
    )

    if scope.provincia_id is not None:
        logger.info("Filtrando por província %s", scope.provincia_id)
        query = query.where(User.provincia_id == scope.provincia_id)

    total = await session.scalar(query)

    return {
        'total': total or 0
    }



@admin.get('/militantes-registrados/nos-ultimos-dias', status_code=HTTPStatus.OK)
async def ultimos_militantes_resgistrados(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """
    Retorna o total de militantes registrados nos últimos 7 dias.
    1. Superadmin → retorna o total de militantes registrados em todo o país.
    2. Admin Provincial → retorna o total de militantes registrados na sua província.
    3. Admin Municipal → acesso negado (não pode acessar totais).
    """

    logger.info(
        "Validar permissão do usuário %s para acessar o total de militantes registrados nos últimos dias",
        current_user.id
    )

    if scope.municipio_id is not None:
        logger.warning(
            "Acesso negado: Usuário %s (município) não tem permissão",
            current_user.id
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Acesso negado: Você não tem permissão para acessar o total de militantes registrados."
        )

    logger.info("Buscando total de militantes na base de dados")

    query = select(func.count(User.id)).where(
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.MILITANTE,
        User.criado_em >= datetime.now(timezone.utc) - timedelta(days=7)
    )

    if scope.provincia_id is not None:
        logger.info("Filtrando por província %s", scope.provincia_id)
        query = query.where(User.provincia_id == scope.provincia_id)

    total = await session.scalar(query)

    return {
        'total': total or 0
    }


@admin.get("/militantes-provincia", status_code=HTTPStatus.OK)
async def militantes_por_provincia(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
):
    """
    Retorna o total de militantes cadastrados, agrupados por província ou município,
    dependendo do nível de acesso do administrador.
    1. Superadmin → agrupa por província.
    2. Admin Provincial → agrupa por município da sua província.
    3. Admin Municipal → acesso negado (não pode acessar totais). 
    """
    logger.info(
        "Usuário %s tentando acessar total de militantes",
        current_user.id
    )

    # Admin de município não pode acessar
    if scope.municipio_id is not None:
        logger.warning(
            "Acesso negado: Usuário %s (município) tentou acessar totais",
            current_user.id
        )
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Acesso negado: Você não tem permissão para acessar esses dados."
        )

    # ======================
    # SUPERADMIN → agrupa por PROVÍNCIA
    # ======================
    if scope.provincia_id is None:
        logger.info("Superadmin buscando totais por província")

        query = (
            select(
                Provincia.nome_provincia.label("nome"),
                func.count(User.id).label("total")
            )
            .join(User, User.provincia_id == Provincia.id)
            .where(
                User.ativo.is_(True),
                User.cadastrar_militante == CadastrarComo.MILITANTE
            )
            .group_by(Provincia.nome_provincia)
            .order_by(func.count(User.id).desc())
        )

        result = await session.execute(query)

        return [
            {
                "provincia": nome,
                "total": total
            }
            for nome, total in result.all()
        ]

    # ======================
    # ADMIN PROVINCIAL → agrupa por MUNICÍPIO da sua província
    # ======================
    logger.info(
        "Admin provincial %s buscando totais por município da província %s",
        current_user.id,
        scope.provincia_id
    )

    query = (
        select(
            Municipio.nome_municipio.label("nome"),
            func.count(User.id).label("total")
        )
        .join(User, User.municipio_id == Municipio.id)
        .where(
            User.ativo.is_(True),
            User.cadastrar_militante == CadastrarComo.MILITANTE,
            Municipio.id_provincia == scope.provincia_id   # só municípios da sua província
        )
        .group_by(Municipio.nome_municipio)
        .order_by(func.count(User.id).desc())
    )

    result = await session.execute(query)

    return [
        {
            "municipio": nome,
            "total": total
        }
        for nome, total in result.all()
    ]

@admin.get("/evolucao-militantes", status_code=HTTPStatus.OK)
async def evolucao_militantes(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    ano: int = Query(None, description="Ano para filtrar (padrão: ano atual)"),
):
    """
    Retorna a evolução mensal do número de militantes cadastrados ao longo do ano especificado.
    Se nenhum ano for fornecido, o padrão será o ano atual. 
    """
    logger.info(
        "Usuário %s tentando acessar evolução de militantes do ano %s",
        current_user.id,
        ano or "atual"
    )

    # Admin de município não pode
    if scope.municipio_id is not None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail="Acesso negado: Você não tem permissão para acessar esses dados."
        )

    ano_atual = date.today().year
    ano_consulta = ano or ano_atual

    # Não permite consultar anos futuros
    if ano_consulta > ano_atual:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Não é possível consultar anos futuros."
        )

    # Query base
    query = (
        select(
            extract("month", User.criado_em).label("mes"),
            func.count(User.id).label("total")
        )
        .where(
            User.ativo.is_(True),
            User.cadastrar_militante == CadastrarComo.MILITANTE,
            extract("year", User.criado_em) == ano_consulta
        )
        .group_by(extract("month", User.criado_em))
        .order_by(extract("month", User.criado_em))
    )

    # Se for Admin Provincial → filtra só a província dele
    if scope.provincia_id is not None:
        query = query.where(User.provincia_id == scope.provincia_id)

    result = await session.execute(query)
    dados_mes = {int(mes): total for mes, total in result.all()}

    # Nomes dos meses em português
    meses_pt = {
        1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr",
        5: "Mai", 6: "Jun", 7: "Jul", 8: "Ago",
        9: "Set", 10: "Out", 11: "Nov", 12: "Dez"
    }

    # Define até qual mês mostrar
    if ano_consulta == ano_atual:
        ultimo_mes = date.today().month
    else:
        ultimo_mes = 12  # anos anteriores mostram o ano inteiro

    # Monta a lista acumulada
    evolucao = []
    acumulado = 0

    for mes in range(1, ultimo_mes + 1):
        total_mes = dados_mes.get(mes, 0)
        acumulado += total_mes

        evolucao.append({
            "mes": meses_pt[mes],
            "total": acumulado
        })

    return {
        "ano": ano_consulta,
        "dados": evolucao
    }




@admin.get(
    '/registros-recentes',
    status_code=HTTPStatus.OK,
    response_model=RegistrosRecentes,
)
# @limiter.limit('30/minute')
async def registros_militantes_recentes(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    nome_provincia: str | None = Query(None, description='Filtrar por nome da província (só Superadmin)'),
    nome_municipio: str | None = Query(None, description='Filtrar por nome do município'),
    email: str | None = Query(None, description='Filtrar por email exato'),
    nif: str | None = Query(None, description='Filtrar por NIF exato'),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    """
    Lista militantes com filtros opcionais.

    - Superadmin: pode filtrar por província, município, email, nif
    - Admin Provincial: só município (da sua província), email, nif
    - Admin Municipal: acesso negado
    - Sem filtros: retorna todos (respeitando o escopo do admin)
    """
    logger.info(
        'Usuário %s listando militantes (provincia=%s, municipio=%s, email=%s, nif=%s)',
        current_user.id,
        nome_provincia,
        nome_municipio,
        email,
        nif,
    )

    if scope.municipio_id is not None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você não tem permissão para acessar estes registros.',
        )

    if scope.provincia_id is not None and nome_provincia is not None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Admin provincial não pode filtrar por outra província.',
        )

    # ---- Província ----
    provincia_id_filtro = None
    if nome_provincia:
        nome_provincia = nome_provincia.strip().title()
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == nome_provincia)
        )
        if not provincia_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')
        provincia_id_filtro = provincia_banco.id

    # ---- Município ----
    municipio_id_filtro = None
    if nome_municipio:
        nome_municipio = nome_municipio.strip().title()
        query_municipio = select(Municipio).where(Municipio.nome_municipio == nome_municipio)

        if provincia_id_filtro is not None:
            query_municipio = query_municipio.where(Municipio.id_provincia == provincia_id_filtro)

        if scope.provincia_id is not None:
            query_municipio = query_municipio.where(Municipio.id_provincia == scope.provincia_id)

        municipio_banco = await session.scalar(query_municipio)
        if not municipio_banco:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'Município "{nome_municipio}" não encontrado ou não pertence à província informada.',
            )
        municipio_id_filtro = municipio_banco.id

    # ---- Filtros ----
    filtros = [
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.MILITANTE,
        User.deletado_em.is_(None),  # se usar soft delete; remova se não tiver
    ]

    if scope.provincia_id is not None:
        filtros.append(User.provincia_id == scope.provincia_id)

    if provincia_id_filtro is not None:
        filtros.append(User.provincia_id == provincia_id_filtro)

    if municipio_id_filtro is not None:
        filtros.append(User.municipio_id == municipio_id_filtro)

    if email:
        filtros.append(User.email == email.lower().strip())

    if nif:
        filtros.append(User.nif == nif.upper().strip())

    # Contagem
    total = await session.scalar(select(func.count(User.id)).where(*filtros)) or 0

    # Dados
    query = (
        select(User)
        .where(*filtros)
        .options(
            selectinload(User.provincia),
            selectinload(User.municipio),
            selectinload(User.role),
        )
        .order_by(User.criado_em.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    registros = result.scalars().all()

    return {
        'total': total,
        'results': registros,
    }




@admin.get(
    '/registros-recentes/simpatizante',
    status_code=HTTPStatus.OK,
    response_model=RegistrosRecentes,
)
# @limiter.limit('30/minute')
async def registros_simpatizantes_recentes(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    nome_provincia: str | None = Query(None, description='Filtrar por nome da província (só Superadmin)'),
    nome_municipio: str | None = Query(None, description='Filtrar por nome do município'),
    email: str | None = Query(None, description='Filtrar por email exato'),
    nif: str | None = Query(None, description='Filtrar por NIF exato'),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    """
    Lista simpatizantes com filtros opcionais.

    - Superadmin: pode filtrar por província, município, email, nif
    - Admin Provincial: só município (da sua província), email, nif
    - Admin Municipal: acesso negado
    - Sem filtros: retorna todos (respeitando o escopo do admin)
    """
    logger.info(
        'Usuário %s listando simpatizantes (provincia=%s, municipio=%s, email=%s, nif=%s)',
        current_user.id,
        nome_provincia,
        nome_municipio,
        email,
        nif,
    )

    # Admin municipal não pode
    if scope.municipio_id is not None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Você não tem permissão para acessar estes registros.',
        )

    # Admin provincial não pode filtrar por província
    if scope.provincia_id is not None and nome_provincia is not None:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN,
            detail='Acesso negado: Admin provincial não pode filtrar por outra província.',
        )

    # ---- Resolve província (se informada) ----
    provincia_id_filtro = None
    if nome_provincia:
        nome_provincia = nome_provincia.strip().title()
        provincia_banco = await session.scalar(
            select(Provincia).where(Provincia.nome_provincia == nome_provincia)
        )
        if not provincia_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada')
        provincia_id_filtro = provincia_banco.id

    # ---- Resolve município (se informado) ----
    municipio_id_filtro = None
    if nome_municipio:
        nome_municipio = nome_municipio.strip().title()
        query_municipio = select(Municipio).where(Municipio.nome_municipio == nome_municipio)

        # Se superadmin filtrou província, o município tem que pertencer a ela
        if provincia_id_filtro is not None:
            query_municipio = query_municipio.where(Municipio.id_provincia == provincia_id_filtro)

        # Se for admin provincial, o município tem que ser da província dele
        if scope.provincia_id is not None:
            query_municipio = query_municipio.where(Municipio.id_provincia == scope.provincia_id)

        municipio_banco = await session.scalar(query_municipio)
        if not municipio_banco:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=f'Município "{nome_municipio}" não encontrado ou não pertence à província informada.',
            )
        municipio_id_filtro = municipio_banco.id

    # ---- Query base ----
    filtros = [
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.SIMPATIZANTE,  # confirme o valor do enum
    ]

    # Escopo automático do admin provincial
    if scope.provincia_id is not None:
        filtros.append(User.provincia_id == scope.provincia_id)

    # Filtros opcionais
    if provincia_id_filtro is not None:
        filtros.append(User.provincia_id == provincia_id_filtro)

    if municipio_id_filtro is not None:
        filtros.append(User.municipio_id == municipio_id_filtro)

    if email:
        filtros.append(User.email == email.lower().strip())

    if nif:
        filtros.append(User.nif == nif.upper().strip())

    # Contagem total
    count_query = select(func.count(User.id)).where(*filtros)
    total = await session.scalar(count_query) or 0

    # Dados paginados
    query = (
        select(User)
        .where(*filtros)
        .options(
            selectinload(User.provincia),
            selectinload(User.municipio),
            selectinload(User.role),
        )
        .order_by(User.criado_em.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    registros = result.scalars().all()

    return {
        'total': total,
        'results': registros,
    }



# @admin.get(
#     '/militantes/distribuicao_genero',
#     status_code=HTTPStatus.OK,
#     response_model=DistribuicaoGenero,
# )
# # @limiter.limit('30/minute')
# async def distribuicao_genero(
#     response: Response,
#     session: Session,
#     caches: Redis,
#     current_user: Get_current_user,
#     scope: ScopeValid,
# ):
#     """Retorna a distribuição de gênero dos militantes (para o gráfico donut)."""

#     try:
#         versao_cache = (await caches.get('v1:usuarios:lista:versao')) or b'1'
#         versao_cache = versao_cache.decode('utf-8') if isinstance(versao_cache, bytes) else str(versao_cache)
#     except Exception as e:
#         logger.error('Falha ao ler versão do cache no Redis: %s', e)
#         versao_cache = 'fallback'

#     scope_key = (
#         f'mun:{scope.municipio_id}' if scope.municipio_id
#         else f'prov:{scope.provincia_id}' if scope.provincia_id
#         else 'all'
#     )
#     cache_key = f'v1:militantes:distribuicao_genero:{scope_key}:v:{versao_cache}'

#     # Cache
#     try:
#         cached = await caches.get(cache_key)
#         if cached:
#             response.headers['X-Cache'] = 'HIT'
#             data = cached.decode('utf-8') if isinstance(cached, bytes) else cached
#             return DistribuicaoGenero.model_validate_json(data)
#     except Exception as e:
#         logger.warning('Falha ao ler cache: %s', e)

#     logger.info('Buscando distribuição de gênero no PostgreSQL (scope=%s)', scope_key)

#     count_query = select(
#         func.count(User.id).label('total'),
#         func.sum(case((User.genero == Genero.HOMEM, 1), else_=0)).label('masculino'),
#         func.sum(case((User.genero == Genero.MULHER, 1), else_=0)).label('feminino'),
#     ).where(
#         User.ativo.is_(True),
#         User.cadastrar_militante == CadastrarComo.MILITANTE,
#     )

#     if scope.municipio_id is not None:
#         count_query = count_query.where(User.municipio_id == scope.municipio_id)
#     elif scope.provincia_id is not None:
#         count_query = count_query.where(User.provincia_id == scope.provincia_id)

#     counts = (await session.execute(count_query)).one()

#     total = counts.total or 0
#     masculino = int(counts.masculino or 0)
#     feminino = int(counts.feminino or 0)

#     if total > 0:
#         percentual_masculino = round((masculino / total) * 100, 1)
#         percentual_feminino = round((feminino / total) * 100, 1)
#     else:
#         percentual_masculino = 0.0
#         percentual_feminino = 0.0

#     resposta = DistribuicaoGenero(
#         total=total,
#         masculino=masculino,
#         feminino=feminino,
#         percentual_masculino=percentual_masculino,
#         percentual_feminino=percentual_feminino,
#     )

#     try:
#         await caches.set(cache_key, resposta.model_dump_json(), ex=60)
#     except Exception as e:
#         logger.error('Não foi possível guardar o cache: %s', e)

#     response.headers['X-Cache'] = 'MISS'
#     return resposta




@admin.get(
    '/militantes/distribuicao_genero',
    status_code=HTTPStatus.OK,
    response_model=DistribuicaoGenero,
)
# @limiter.limit('30/minute')
async def distribuicao_genero(
    response: Response,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    scope: ScopeValid,
    provincia_id: int | None = Query(None, description='Filtrar por província (só Superadmin)'),
    municipio_id: int | None = Query(None, description='Filtrar por município'),
):
    """
    Distribuição de gênero dos militantes.

    - Superadmin: opcional provincia_id / municipio_id; sem filtro = país inteiro
    - Admin Provincial: opcional municipio_id da sua província; sem filtro = toda a província
    - Admin Municipal: sempre só o seu município
    """
    logger.info(
        'Usuário %s pedindo distribuição de gênero (provincia_id=%s, municipio_id=%s)',
        current_user.id,
        provincia_id,
        municipio_id,
    )

    # ---------- Autorização + resolução do filtro real ----------
    filtro_provincia_id: int | None = None
    filtro_municipio_id: int | None = None

    # Admin Municipal → preso ao seu município
    if scope.municipio_id is not None:
        if provincia_id is not None or municipio_id is not None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Acesso negado: Admin municipal não pode usar filtros de território.',
            )
        filtro_municipio_id = scope.municipio_id

    # Admin Provincial → só a sua província; pode filtrar município
    elif scope.provincia_id is not None:
        logger.info('Admin provincial %s, província %s', current_user.id, scope.provincia_id)
        if provincia_id is not None and provincia_id != scope.provincia_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Acesso negado: Você só pode consultar a sua província.',
            )
        filtro_provincia_id = scope.provincia_id

        if municipio_id is not None:
            logger.info('Admin provincial %s filtrando município %s', current_user.id, municipio_id)
            municipio = await session.scalar(
                select(Municipio).where(
                    Municipio.id == municipio_id,
                    Municipio.id_provincia == scope.provincia_id,
                )
            )
            if not municipio:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail='Município não encontrado ou não pertence à sua província.',
                )
            filtro_municipio_id = municipio_id

    # Superadmin → livre
    else:
        logger.info('Superadmin %s acessando todos os dados', current_user.id)
        if provincia_id is not None:
            logger.info('Superadmin %s filtrando província %s', current_user.id, provincia_id)
            provincia = await session.scalar(
                select(Provincia).where(Provincia.id == provincia_id)
            )
            if not provincia:
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail=f'Província {provincia_id} não encontrada.',
                )
            filtro_provincia_id = provincia_id
            logger.info('Superadmin %s filtrando município %s', current_user.id, municipio_id)

        if municipio_id is not None:
            logger.info('Superadmin %s filtrando município %s', current_user.id, municipio_id)
            query_mun = select(Municipio).where(Municipio.id == municipio_id)
            if filtro_provincia_id is not None:
                query_mun = query_mun.where(Municipio.id_provincia == filtro_provincia_id)

            municipio = await session.scalar(query_mun)
            if not municipio:
                logger.warning('Município %s não encontrado ou não pertence à província %s', municipio_id, filtro_provincia_id)
                raise HTTPException(
                    status_code=HTTPStatus.NOT_FOUND,
                    detail='Município não encontrado ou não pertence à província informada.',
                )
            filtro_municipio_id = municipio_id
            # Garante consistência: município define a província
            filtro_provincia_id = municipio.id_provincia

    # ---------- Cache ----------
    try:
        versao_cache = (await caches.get('v1:usuarios:lista:versao')) or b'1'
        versao_cache = (
            versao_cache.decode('utf-8')
            if isinstance(versao_cache, bytes)
            else str(versao_cache)
        )
    except Exception as e:
        logger.error('Falha ao ler versão do cache: %s', e)
        versao_cache = 'fallback'

    scope_key = (
        f'mun:{filtro_municipio_id}' if filtro_municipio_id is not None
        else f'prov:{filtro_provincia_id}' if filtro_provincia_id is not None
        else 'all'
    )
    cache_key = f'v1:militantes:distribuicao_genero:{scope_key}:v:{versao_cache}'

    try:
        cached = await caches.get(cache_key)
        if cached:
            response.headers['X-Cache'] = 'HIT'
            data = cached.decode('utf-8') if isinstance(cached, bytes) else cached
            return DistribuicaoGenero.model_validate_json(data)
    except Exception as e:
        logger.warning('Falha ao ler cache: %s', e)

    # ---------- Query ----------
    logger.info('Distribuição de gênero no PostgreSQL (%s)', scope_key)

    filtros = [
        User.ativo.is_(True),
        User.cadastrar_militante == CadastrarComo.MILITANTE,
    ]
    if filtro_municipio_id is not None:
        filtros.append(User.municipio_id == filtro_municipio_id)
    elif filtro_provincia_id is not None:
        filtros.append(User.provincia_id == filtro_provincia_id)

    count_query = select(
        func.count(User.id).label('total'),
        func.count().filter(User.genero == Genero.HOMEM).label('masculino'),
        func.count().filter(User.genero == Genero.MULHER).label('feminino'),
    ).where(*filtros)

    counts = (await session.execute(count_query)).one()

    total = counts.total or 0
    masculino = int(counts.masculino or 0)
    feminino = int(counts.feminino or 0)

    if total > 0:
        percentual_masculino = round((masculino / total) * 100, 1)
        percentual_feminino = round((feminino / total) * 100, 1)
    else:
        percentual_masculino = 0.0
        percentual_feminino = 0.0

    if masculino + feminino != total:
        logger.warning(
            'Género incompleto (%s): total=%s masculino=%s feminino=%s',
            scope_key, total, masculino, feminino,
        )

    resposta = DistribuicaoGenero(
        total=total,
        masculino=masculino,
        feminino=feminino,
        percentual_masculino=percentual_masculino,
        percentual_feminino=percentual_feminino,
    )

    try:
        await caches.set(cache_key, resposta.model_dump_json(), ex=60)
    except Exception as e:
        logger.error('Não foi possível guardar o cache: %s', e)

    response.headers['X-Cache'] = 'MISS'
    return resposta







@admin.get('/audoitLog', response_model=PaginatedAuditLogs)
async def listar_logs_auditoria(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    accao: Optional[str] = Query(None, description='Filtrar por acção: CREATE, UPDATE, DELETE'),
    entidade: Optional[str] = Query(None, description='Filtrar por tabela: users, noticias, etc.'),
    usuario_id: Optional[uuid.UUID] = Query(None, description='Filtrar acções de um utilizador específico'),
):
    verificar_permissao_global_pais(scope, current_user)
    # 1. Construir a query base com filtros opcionais
    query = select(AuditLog)

    if accao:
        query = query.where(AuditLog.accao == accao.upper())
    if entidade:
        query = query.where(AuditLog.entidade == entidade.lower())
    if usuario_id is not None:
        query = query.where(AuditLog.usuario_id == usuario_id)

    # 2. Contar o total de registros com os mesmos filtros aplicados
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # 3. Aplicar ordenação (mais recentes primeiro) e paginação
    offset = (page - 1) * limit
    query = query.order_by(AuditLog.criado_as.desc()).offset(offset).limit(limit)

    # 4. Executar a busca dos registros
    result = await session.execute(query)
    logs = result.scalars().all()

    return {'total': total, 'page': page, 'limit': limit, 'results': logs}




@admin.get('/notificacoes/suporte', status_code=HTTPStatus.OK, response_model=MensagensSuportePaginadasResponse)
async def listar_notificacoes_suporte(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    limit: int = Query(default=10, le=50, description='Número de notificações por página'),
    offset: int = Query(default=0, ge=0, description='Número de registros a pular (offset)'),
):

    """
    Retorna a lista de notificações de suporte destinadas ao Administrador logado,
    ordenadas das mais recentes para as mais antigas.
    """

    logger.info('Administrador %s listando suas notificações de suporte...', current_user.id)
    query = (
        select(MensagemSuporte)
        .where(MensagemSuporte.admin_id == current_user.id)
        .order_by(MensagemSuporte.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    notificacoes = result.scalars().all()

    if not notificacoes:
        logger.info("Nenhuma notificação de suporte encontrada para o usuário %s", current_user.id)
        return {
                'total': 0, 
                'results': []
                }

    return {
        'results': notificacoes
    }




@admin.get('/notificacoes/solicitacoes-cartao', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes_cartao(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    limit: int = Query(default=10, le=50, description='Número de notificações por página'),
    offset: int = Query(default=0, ge=0, description='Número de registros a pular (offset)'),
):
    """
    Retorna a lista de notificações destinadas ao Administrador logado,
    ordenadas das mais recentes para as mais antigas.
    """
    logger.info('Administrador %s listando suas notificações...', current_user.id)

    # CORREÇÃO CRUCIAL: O Admin deve buscar onde o admin_id é igual ao id dele!

    query = (
        select(Notification)
        .options(joinedload(Notification.solicitante))
        .where(Notification.admin_id == current_user.id,
               Notification.destinatario == 'ADMIN',
               Notification.categoria == 'SOLICITACAO_CARTAO'
               )
        .order_by(Notification.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    notificacoes = result.scalars().all()

    # CORREÇÃO CRUCIAL: Ajustado o contador para usar as mesmas regras de filtro do admin
    query_nao_lidas = select(func.count(Notification.id)).where(
        Notification.admin_id == current_user.id, Notification.destinatario == 'ADMIN', Notification.lido_as.is_(None)
    )
    total_nao_lidas = await session.scalar(query_nao_lidas) or 0

    return {
    'total': total_nao_lidas, 
    'results': notificacoes}




@admin.get(
    '/solicitante-cartao',
    status_code=HTTPStatus.OK,
    response_model=CardSolicitante
)
async def listar_solicitante_cartao(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    limit: int = Query(default=10, le=50, description='Número de registros por página'),
    offset: int = Query(default=0, ge=0, description='Número de registros a pular'),
):
    logger.info('Administrador %s listando solicitações de cartão...', current_user.id)

    query = (
        select(SolicitacaoCartao)
        .join(User, User.id == SolicitacaoCartao.user_id)
        .options(
            selectinload(SolicitacaoCartao.user).selectinload(User.municipio),
            selectinload(SolicitacaoCartao.user).selectinload(User.provincia),
        )
        .order_by(SolicitacaoCartao.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )

    # Filtro por escopo
    if scope.municipio_id is not None:
        query = query.where(User.municipio_id == scope.municipio_id)
    elif scope.provincia_id is not None:
        query = query.where(User.provincia_id == scope.provincia_id)

    result = await session.execute(query)
    solicitacoes = result.scalars().all()

    # Contagem total
    count_query = (
        select(func.count(SolicitacaoCartao.id))
        .join(User, User.id == SolicitacaoCartao.user_id)
    )

    if scope.municipio_id is not None:
        count_query = count_query.where(User.municipio_id == scope.municipio_id)
    elif scope.provincia_id is not None:
        count_query = count_query.where(User.provincia_id == scope.provincia_id)

    total = await session.scalar(count_query) or 0

    results = []
    for s in solicitacoes:
        user = s.user
        results.append({
            "id": s.id,
            "numero_cartao": user.militante_numero or "",          # schema exige str
            "nome_militante": user.nome_completo,
            "data_emissao": s.criado_as,                           # usando a data da solicitação
            "data_nascimento": user.data_nascimento,
            "activo": user.ativo,
            "estado_civil": user.estado_civil,
            "municipio": user.municipio,                           # o validator extrai o nome
            "provincia": user.provincia,                           # o validator extrai o nome
        })

    return {
        "total": total,
        "results": results
    }



@admin.get('/notificacoes/dashboard', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes_dashboard(
    session: Session,
    current_user: Get_current_user,
        limit: int = Query(
        default=10,
        le=50,
        description="Número de notificações por página"
    ),
    offset: int = Query(
        default=0,
        ge=0,
        le=10000,
        description="Número de registros a pular (offset)"
    )
):
    """
    Retorna a lista de notificações do usuário logado de forma paginada,
    conforme o seu tipo de cadastro (Militante ou Simpatizante).
    """
    logger.info("Usuário %s listando notificações...", current_user.id)


    # 1. Constrói os filtros base (reutilizáveis e seguros)
    filtros = [Notification.user_id == current_user.id]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    total_query = (
        select(func.count(Notification.id))
        .where(*filtros, Notification.lido_as.is_(None))
    )
    total = await session.scalar(total_query) or 0
    # 2. Consulta Principal (Ordenação e Paginação aplicadas no fim)
    query = (
        select(Notification)
        .options(joinedload(Notification.solicitante))
        .where(*filtros)
        .order_by(Notification.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)

    notificacoes = result.scalars().all()

    if not notificacoes:
        logger.info("Nenhuma notificação encontrada para o usuário %s", current_user.id)
        

    # 4. Consulta do Contador (Usa os mesmos filtros dinâmicos de forma consistente)
    return {
        "total": total,
        "results": notificacoes
    }
    

@admin.get('/notificacoes', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    limit: int = Query(default=10, le=50, description='Número de notificações por página'),
    offset: int = Query(default=0, ge=0, description='Número de registros a pular (offset)'),
):
    """
    Retorna a lista de notificações destinadas ao Administrador logado,
    ordenadas das mais recentes para as mais antigas.
    """
    logger.info('Administrador %s listando suas notificações...', current_user.id)

    # CORREÇÃO CRUCIAL: O Admin deve buscar onde o admin_id é igual ao id dele!
    query = (
        select(Notification)
        .options(joinedload(Notification.solicitante))
        .where(Notification.admin_id == current_user.id, Notification.destinatario == 'ADMIN')
        .order_by(Notification.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    notificacoes = result.scalars().all()

    # CORREÇÃO CRUCIAL: Ajustado o contador para usar as mesmas regras de filtro do admin
    query_nao_lidas = select(func.count(Notification.id)).where(
        Notification.admin_id == current_user.id, Notification.destinatario == 'ADMIN', Notification.lido_as.is_(None)
    )
    total_nao_lidas = await session.scalar(query_nao_lidas) or 0

    return {
    'total': total_nao_lidas, 
    'results': notificacoes}


@admin.get('/notificacoes/lidas', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes_lidas(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    limit: int = Query(default=10, le=50, description='Número de notificações por página'),
    offset: int = Query(default=0, ge=0, description='Número de registros a pular (offset)'),
):
    """
    Retorna a lista de notificações destinadas ao Administrador logado,
    ordenadas das mais recentes para as mais antigas.
    """
    logger.info('Administrador %s listando suas notificações...', current_user.id)

    # CORREÇÃO CRUCIAL: O Admin deve buscar onde o admin_id é igual ao id dele!
    query = (
        select(Notification)
        .options(joinedload(Notification.solicitante))
        .where(Notification.admin_id == current_user.id,
               Notification.destinatario == 'ADMIN',
               Notification.lido_as.is_not(None)
               )
        .order_by(Notification.criado_as.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(query)
    notificacoes = result.scalars().all()

    if not notificacoes:
        logger.info("Nenhuma notificação encontrada para o usuário %s", current_user.id)
        return {
                'total': 0, 
                'results': []
                }

    # CORREÇÃO CRUCIAL: Ajustado o contador para usar as mesmas regras de filtro do admin
    query_lidas = select(func.count(Notification.id)).where(
        Notification.admin_id == current_user.id, Notification.destinatario == 'ADMIN', Notification.lido_as.is_not(None)

    )
    total_lidas = await session.scalar(query_lidas) or 0

    # return {'total_lidas': total_lidas, 'notificacoes': notificacoes}
    return {
        'total': total_lidas, 
        'results': notificacoes
        }
    


@admin.patch(
    '/notificacoes/{id_notificacao}/ler',
    status_code=HTTPStatus.OK,
    response_model=NotificationResponse
)
async def marcar_como_lida(
    response: Response,
    id_notificacao: uuid.UUID,
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid
):
    """
    Marca uma notificação do administrador como lida.
    Garante que o usuário só possa alterar notificações próprias.
    """

    logger.info(
        "Usuário %s tentando marcar notificação %s como lida",
        current_user.id,
        id_notificacao
    )


    filtros = [Notification.user_id == current_user.id, Notification.id == id_notificacao]

    query = (
            select(Notification)
            .options(joinedload(Notification.solicitante))
            .where(*filtros)
        )
    
    notificacao = await session.scalar(
        query
    )

    if notificacao is None:
        logger.warning(
            "Notificação %s não pertence ao usuário %s",
            id_notificacao,
            current_user.id
        )

        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Notificação não encontrada."
        )

    if notificacao.lido_as is None:
        notificacao.lido_as = datetime.now(timezone.utc)

        try:
            await session.commit()
            logger.info(
                "Notificação %s marcada como lida pelo usuário %s", 
                id_notificacao,
                current_user.id
            )
        except SQLAlchemyError:
            await session.rollback()

            logger.exception(
                "Erro ao marcar notificação %s como lida",
                id_notificacao
            )

            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail="Erro ao atualizar a notificação."
            )

    return notificacao



@admin.get('/scope/{scope_id}', status_code=HTTPStatus.OK, response_model=ResponseAdminScope)
async def obter_escopo_por_id(scope_id: uuid.UUID, session: Session, current_user: Get_current_user, scope: ScopeValid):
    """
    Retorna os detalhes de um escopo de administração específico por ID.
    Garante que admins regionais não auditem escopos fora de sua jurisdição.
    """
    verificar_permissao_global_pais(scope, current_user)
    if not current_user.scope:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail='Permissão negada.')

    query = select(AdminScope).where(AdminScope.id == scope_id).options(selectinload(AdminScope.user))
    scope_target = await session.scalar(query)

    if not scope_target:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Escopo administrativo não encontrado.')

    if current_user.scope.municipio_id is not None and scope_target.municipio_id != current_user.scope.municipio_id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado a este escopo.')
    elif current_user.scope.provincia_id is not None and scope_target.provincia_id != current_user.scope.provincia_id:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail='Acesso negado a este escopo.')

    return scope_target


@admin.delete('/scope/{scope_id}', status_code=HTTPStatus.OK)
async def remover_escopo_administrativo(
    scope_id: uuid.UUID, session: Session, redis: Redis, current_user: Get_current_user, scope: ScopeValid
):
    """Remove definitivamente o registro de escopo de um usuário (Revogação de Poderes).
    Bloqueia concorrência e restringe a ação com base na hierarquia regional.
    """
    verificar_permissao_global_pais(scope, current_user)
    query = select(AdminScope).where(AdminScope.id == scope_id).with_for_update()
    scope_to_delete = await session.scalar(query)
    if not scope_to_delete:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Escopo não encontrado.')

    if scope.municipio_id is not None:
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail='Admins municipais não podem revogar escopos.')
    elif scope.provincia_id is not None:
        if scope_to_delete.provincia_id != scope.provincia_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Você só pode revogar escopos da sua própria província.'
            )

        if scope_to_delete.municipio_id is None:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail='Um Admin Provincial não pode revogar o escopo de outro Admin Provincial.',
            )

        try:
            await session.delete(scope_to_delete)
            await session.commit()
            await redis.incr('v1:admin:scope:versao')
            await redis.incr('v1:usuarios:lista:versao')
            logger.info(f'Escopo administrativo {scope_id} revogado com sucesso pelo Admin {current_user.id}.')
            return {'msg': 'Escopo administrativo revogado e removido com sucesso!'}
        except Exception as e:
            await session.rollback()
            logger.error(f'Falha crítica ao deletar escopo {scope_id}: {str(e)}')
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Não foi possível revogar o escopo.'
            )


@admin.put('/role/militante-upgrade/{id_militante}', status_code=HTTPStatus.OK)
async def upgrade_role_user(
    id_militante: uuid.UUID,
    session: Session,
    # current_user: Get_current_user,
    # scope: ScopeValid,
    role_nome: str = Form(..., max_length=15, description='Nome do novo role a ser atribuído ao usuário'),
):
    """ """
    query = select(User).where(User.id == id_militante)
    usuario_banco = await session.scalar(query)
    if not usuario_banco:
        logger.warning('Nenhum usuário com id: [%s] ativo foi encontrado!', id_militante)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f'Nenhum usuário com id: [{id_militante}] ativo foi encontrado!'
        )
    role_banco = await session.scalar(select(Role).where(Role.nome == role_nome))
    if not role_banco:
        logger.warning('Nenhum role com nome: [%s] ativo foi encontrado!', role_nome)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f'Nenhum role com nome: [{role_nome}] ativo foi encontrado!'
        )

    if role_nome == 'simpatizante':
        usuario_banco.cadastrar_militante = CadastrarComo.SIMPATIZANTE
    else:
        usuario_banco.cadastrar_militante = CadastrarComo.MILITANTE


    usuario_banco.role_id = role_banco.id

    try:
        session.add(usuario_banco)
        await session.commit()
        await session.refresh(usuario_banco)
        return {'msg': f'Role ${usuario_banco.email} do Usuário atualizado com sucesso! para ${usuario_banco.role_id}'}

    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao atualizar role do usuário: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, detail='O e-mail informado já está sendo utilizado por outro usuário.'
        )
    except Exception as e:
        await session.rollback()
        logger.error('Erro desconhecido na atualização do role do usuário: %s', str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Não foi possível processar a atualização o role do usuario.',
        )


@admin.post('/card/militante/{id_militante}/aprovado', status_code=HTTPStatus.OK)
async def militante_card(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    id_militante: uuid.UUID,
    # backgroundTasks: BackgroundTasks,
    observacao: str | None = Form(None, min_length=5, description='Observações opcionais sobre a emissão do cartão'),
):
    logger.info('pesquisar user: %s no banco de dados...', id_militante)

    query = select(User).where(User.id == id_militante)
    usuario_banco = await session.scalar(query)

    if not usuario_banco:
        logger.warning('Nenhum usuário com id: [%s] ativo foi encontrado!', id_militante)
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f'Nenhum usuário com id: [{id_militante}] ativo foi encontrado!'
        )

    logger.info('Busca a solicitação pendente deste usuário para garantir o fluxo correto')
    solicitacao = await session.scalar(
        select(SolicitacaoCartao).where(
            SolicitacaoCartao.user_id == id_militante, SolicitacaoCartao.status == StatusSolicitacao.PENDENTE
        )
    )
    if not solicitacao:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Nenhuma solicitação pendente encontrada para este usuário.'
        )

    if not usuario_banco.militante_numero:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Operação rejeitada. O usuário precisa primeiro ter um número de militante atribuído.',
        )

    agora = datetime.now(timezone.utc)
    query_cartao_ativo = select(CartaoMilitante).where(
        CartaoMilitante.user_id == usuario_banco.id, CartaoMilitante.activo == True
    )
    cartao_ativo_existente = await session.scalar(query_cartao_ativo)

    if cartao_ativo_existente:
        logger.warning('Operação rejeitada. Usuário %s já possui um cartão ativo.', usuario_banco.id)
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f'Operação rejeitada. Este usuário já possui um cartão ativo (Nº {cartao_ativo_existente.numero_cartao}).',
        )

    if scope.provincia_id is not None:
        if usuario_banco.provincia_id != scope.provincia_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
            )
    elif scope.municipio_id is not None:
        if usuario_banco.municipio_id != scope.municipio_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
            )

    # # Define data de expiração (5 anos)
    # data_expire_card = agora + timedelta(days=365*5)

    # # Loop seguro do Número do Cartão
    # tentativas = 0
    # while tentativas < 5:
    #     prefix = ''.join(secrets.choice('0123456789') for _ in range(3))
    #     first_card_number = ''.join(secrets.choice('0123456789') for _ in range(3))
    #     middle_card_number = ''.join(secrets.choice('0123456789') for _ in range(3))
    #     last_card_number = ''.join(secrets.choice('0123456789') for _ in range(2))
    #     numero_cartao = f'{prefix}.{first_card_number}.{middle_card_number}-{last_card_number}'

    #     card_exists = await session.scalar(select(CartaoMilitante).where(CartaoMilitante.numero_cartao == numero_cartao))
    #     if not card_exists:
    #         break
    #     tentativas += 1
    # else:
    #     logger.error("Falha crítica: Excedeu o limite de tentativas para gerar um número de cartão único.")
    #     raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Erro de infraestrutura ao gerar número de cartão.")

    # Loop seguro do QR Code com limite
    tentativas = 0
    while tentativas < 5:
        qr_code = secrets.token_urlsafe()
        qr_exists = await session.scalar(select(CartaoMilitante).where(CartaoMilitante.qr_code_assinatura == qr_code))
        if not qr_exists:
            break
        tentativas += 1

    # Montagem do Payload do QR Code
    payload_qr = (
        f'Nome Completo: {usuario_banco.nome_completo}\n'
        f'Data de Nascimento: {usuario_banco.data_nascimento}\n'
        f'Email: {usuario_banco.email}\n'
        f'NIF: {usuario_banco.nif}\n'
        f'Numero de Militante: {usuario_banco.militante_numero}\n'
        f'Data de emissao: {agora}'
    )

    def criar_imagem_qrcode(dados_payload: str) -> bytes:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(dados_payload)
        qr.make(fit=True)
        imagem = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        imagem.save(buffer, format='PNG')
        return buffer.getvalue()

    logger.info('A iniciar a geração da imagem do QR Code...')
    qr_code_bytes = await asyncio.to_thread(criar_imagem_qrcode, payload_qr)

    # Atualiza o status da solicitação existente
    solicitacao.status = StatusSolicitacao.APROVADO
    solicitacao.observacao = observacao  # Salva a observação se houver

    card_militante = CartaoMilitante(
        nome_completo=usuario_banco.nome_completo,
        militante_numero=usuario_banco.militante_numero,
        image_url=usuario_banco.image_url,
        provincia_id=usuario_banco.provincia_id,
        municipio_id=usuario_banco.municipio_id,
        gerado_por=current_user.id,
        user_id=usuario_banco.id,
        qr_code_assinatura=qr_code,
        url_qrcode='pendente',
    )

    nova_notificacao = Notification(
        user_id=usuario_banco.id,
        titulo='Cartão Digital Emitido!',
        mensagem=f'Olá {usuario_banco.nome_completo}, o seu cartão de militante de número {usuario_banco.militante_numero} foi gerado com sucesso pelo administrador!',
    )

    session.add(solicitacao)
    session.add(card_militante)
    session.add(nova_notificacao)

    try:
        await session.commit()
        await session.refresh(card_militante)

        logger.info('Banco gravado com sucesso. Iniciando upload para o Cloudinary...')
        url_imagem_qrcode = await upload_imagem_geral(
            file_bytes=qr_code_bytes, identificador=qr_code, pasta_alvo='sqcode', prefixo_arquivo='qr'
        )

        card_militante.url_qrcode = url_imagem_qrcode
        await session.commit()

        # backgroundTasks.add_task(
        #     enviar_resposta_solicitacao_cartao_militante,
        #     email_destino=usuario_banco.email,
        #     nome_militante=usuario_banco.nome_completo,
        #     numero_militante=usuario_banco.militante_numero,
        #     status_pedido="Aprovado",
        #     observacoes=observacao
        # )

        logger.info('Cartao do usuário %s finalizado com sucesso.', usuario_banco.id)
        return card_militante

    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro crítico de integridade ao criar cartão do usuário %s: %s', id_militante, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno ao processar a criação do cartão.'
        )


@admin.post('/card/militante/{id_militante}/rejeitar', status_code=HTTPStatus.OK)
async def rejeitar_militante_card(
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid,
    id_militante: uuid.UUID,
    # backgroundTasks: BackgroundTasks,
    observacao: str = Form(
        ..., min_length=5, description='Descrever detalhadamente a irregularidade ou motivo da rejeição'
    ),
):
    logger.info('A processar rejeição da solicitação para o utilizador: %s...', id_militante)

    query = select(User).where(User.id == id_militante)
    usuario_banco = await session.scalar(query)

    if not usuario_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=f'Nenhum usuário com id: [{id_militante}] ativo foi encontrado!'
        )

    # Procura a solicitação pendente
    solicitacao = await session.scalar(
        select(SolicitacaoCartao).where(
            SolicitacaoCartao.user_id == id_militante, SolicitacaoCartao.status == StatusSolicitacao.PENDENTE
        )
    )
    if not solicitacao:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Nenhuma solicitação pendente encontrada para este usuário.'
        )

    # Validação de Escopo Regional (Garante que administradores regionais só rejeitam da sua área)
    if scope.provincia_id is not None:
        if usuario_banco.provincia_id != scope.provincia_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
            )
    elif scope.municipio_id is not None:
        if usuario_banco.municipio_id != scope.municipio_id:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
            )

    # 1. Atualiza o estado da solicitação existente para REJEITADO e grava o motivo
    solicitacao.status = StatusSolicitacao.REJEITADO
    solicitacao.observacao = observacao

    # 2. Cria a notificação de rejeição para a tabela interna
    nova_notificacao = Notification(
        user_id=usuario_banco.id,
        titulo='Solicitação de Cartão Rejeitada',
        mensagem=f'Olá {usuario_banco.nome_completo}, a sua solicitação de cartão foi recusada. Motivo: {observacao}',
        destinatario='MILITANTE',
    )

    session.add(solicitacao)
    session.add(nova_notificacao)

    try:
        await session.commit()

        # 3. Dispara o e-mail dinâmico. O Jinja2 vai ler "Rejeitado" e pintar a tabela de Vermelho automaticamente!
        # backgroundTasks.add_task(
        #     enviar_resposta_solicitacao_cartao_militante,
        #     email_destino=usuario_banco.email,
        #     nome_militante=usuario_banco.nome_completo,
        #     numero_militante=usuario_banco.militante_numero or "Não Atribuído",
        #     status_pedido="Rejeitado", # Passa o estado dinâmico correto para o template
        #     observacoes=observacao
        # )

        logger.info('Solicitação do utilizador %s rejeitada e e-mail agendado.', usuario_banco.id)
        return {'msg': 'Solicitação rejeitada com sucesso e utilizador notificado.'}

    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro ao rejeitar solicitação do usuário %s: %s', id_militante, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno ao processar a rejeição.'
        )


# @admin.post('/solicitacao/militancia/aprovado', status_code=HTTPStatus.OK)
# async def aprovacao_solicitacao_militancia(
#     session: Session,
#     current_user: Get_current_user,
#     scope: ScopeValid,
#     # backgroundTasks: BackgroundTasks,
#     observacao: str | None = Form(None, min_length=5, description='Observações opcionais sobre a emissão do cartão'),
# ):
    # logger.info('pesquisar user: %s no banco de dados...', current_user.email)


    # if current_user.cadastrar_militante != 'SIMPATIZANTE':
    #     raise HTTPException(
    #         status_code=HTTPStatus.BAD_REQUEST, detail=f'Usuario {current_user.email} precisar ser simpatizante'
    #     )

    # logger.info('Busca a solicitação pendente deste usuário para garantir o fluxo correto')
    # solicitacao = await session.scalar(
    #     select(SolicitacaoMilitancia).where(
    #         SolicitacaoMilitancia.user_id == current_user.id, SolicitacaoMilitancia.status == StatusSolicitacao.PENDENTE
    #     )
    # )
    # if not solicitacao:
    #     raise HTTPException(
    #         status_code=HTTPStatus.BAD_REQUEST, detail='Nenhuma solicitação pendente encontrada para este usuário.'
    #     )

    # # if not usuario_banco.militante_numero:
    # #     raise HTTPException(
    # #         status_code=HTTPStatus.BAD_REQUEST,
    # #         detail="Operação rejeitada. O usuário precisa primeiro ter um número de militante atribuído."
    # #     )

    # # agora = datetime.now(timezone.utc)

    # # if scope.provincia_id is not None:
    # #     if usuario_banco.provincia_id != scope.provincia_id:
    # #         raise HTTPException(
    # #             status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
    # #         )
    # # elif scope.municipio_id is not None:
    # #     if usuario_banco.municipio_id != scope.municipio_id:
    # #         raise HTTPException(
    # #             status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
    # #         )

    # tentativas = 0

    # if not current_user.militante_numero:
    #     while tentativas < 5:
    #         ano_atual = datetime.now(timezone.utc).year
    #         chave_aleatoria = secrets.token_hex(3)[:6].upper()
    #         militante_numero = f'UNITA.{ano_atual}-{chave_aleatoria}'
    #         numero_exists = await session.scalar(select(User).where(User.militante_numero == militante_numero))
    #         if not numero_exists:
    #             break
    #         tentativas += 1
    #     else:
    #         logger.error('Falha crítica: Excedeu o limite de tentativas para gerar um número de cartão único.')
    #         raise HTTPException(
    #             status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro de infraestrutura ao gerar número de cartão.'
    #         )

    # solicitacao.status = StatusSolicitacao.APROVADO
    # solicitacao.observacao = observacao
    # current_user.cadastrar_militante = CadastrarComo.MILITANTE
    # current_user.militante_numero = militante_numero

    # nova_notificacao = Notification(
    #     user_id=current_user.id,
    #     titulo='Solicitacao de Militancia aprovado!',
    #     mensagem=f'Olá {current_user.nome_completo}, o sua solicitacao de militancia foi aprovada com sucesso!',
    #     destinatario="MILITANTE",
    # )


    # try:
    #     session.add(solicitacao)
    #     session.add(nova_notificacao)

    #     await session.commit()

    #     # backgroundTasks.add_task(
    #     #     enviar_resposta_solicitacao_militancia,
    #     #     email_destino=usuario_banco.email,
    #     #     nome_simpatizante=usuario_banco.nome_completo,
    #     #     status_pedido="Aprovado",
    #     #     observacoes=observacao
    #     # )

    #     logger.info('Solicitacao de militancia  do usuario %s finalizado com sucesso.', current_user.email)
    #     return {'msg': f'Solicitacao de militancia  do usuario {current_user.email} finalizado com sucesso.'}

    # except IntegrityError as e:
    #     await session.rollback()
    #     logger.error('Erro crítico de integridade ao aprovar a militancia do usuário %s: %s', current_user.email, str(e))
    #     raise HTTPException(
    #         status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno ao processar a aprovacao de militancia.'
    #     )


# @admin.post('/solicitacao/militancia/{id_militante}/rejeitar', status_code=HTTPStatus.OK)
# async def rejeitar_solicitacao_militancia(
#     session: Session,
#     current_user: Get_current_user,
#     scope: ScopeValid,
#     id_militante: uuid.UUID,
#     # backgroundTasks: BackgroundTasks,
#     observacao: str = Form(
#         ..., min_length=5, description='Descrever detalhadamente a irregularidade ou motivo da rejeição'
#     ),
# ):
#     logger.info('A processar rejeição da solicitação para o utilizador: %s...', id_militante)

#     query = select(User).where(User.id == id_militante)
#     usuario_banco = await session.scalar(query)

#     if not usuario_banco:
#         raise HTTPException(
#             status_code=HTTPStatus.NOT_FOUND, detail=f'Nenhum usuário com id: [{id_militante}] ativo foi encontrado!'
#         )

#     # Procura a solicitação pendente
#     solicitacao = await session.scalar(
#         select(SolicitacaoMilitancia).where(
#             SolicitacaoMilitancia.user_id == id_militante, SolicitacaoMilitancia.status == StatusSolicitacao.PENDENTE
#         )
#     )
#     if not solicitacao:
#         raise HTTPException(
#             status_code=HTTPStatus.BAD_REQUEST, detail='Nenhuma solicitação pendente encontrada para este usuário.'
#         )

#     if scope.provincia_id is not None:
#         if usuario_banco.provincia_id != scope.provincia_id:
#             raise HTTPException(
#                 status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
#             )
#     elif scope.municipio_id is not None:
#         if usuario_banco.municipio_id != scope.municipio_id:
#             raise HTTPException(
#                 status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
#             )

#     solicitacao.status = StatusSolicitacao.REJEITADO
#     solicitacao.observacao = observacao

#     destinatario_tipo = None
#     if usuario_banco.cadastrar_militante == CadastrarComo.MILITANTE:
#         destinatario_tipo = "MILITANTE"
#     elif usuario_banco.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
#         destinatario_tipo = "SIMPATIZANTE"

#     # print(destinatario_tipo)

#     nova_notificacao = Notification(
#         user_id=usuario_banco.id,
#         titulo='Solicitação de  militancia Rejeitada',
#         mensagem=f'Olá {usuario_banco.nome_completo}, a sua solicitação de militancia foi recusada. Motivo: {observacao}',
#         destinatario=destinatario_tipo,
#     )

#     session.add(solicitacao)
#     session.add(nova_notificacao)

#     try:
#         await session.commit()

#         # backgroundTasks.add_task(
#         #     enviar_resposta_solicitacao_militancia,
#         #     email_destino=usuario_banco.email,
#         #     nome_simpatizante=usuario_banco.nome_completo,
#         #     status_pedido="Rejeitado",
#         #     observacoes=observacao
#         # )

#         logger.info('Solicitação do utilizador %s rejeitada e e-mail agendado.', usuario_banco.id)
#         return {'msg': 'Solicitação rejeitada com sucesso e utilizador notificado.'}

#     except IntegrityError as e:
#         await session.rollback()
#         logger.error('Erro ao rejeitar solicitação do usuário %s: %s', id_militante, str(e))
#         raise HTTPException(
#             status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno ao processar a rejeição.'
#         )


# militancia

import json
import logging
import io
import base64
import time
from jwt import PyJWTError, decode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError
import cloudinary.uploader
import filetype 
import asyncio
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, List, Dict
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    Request,
    Query,
    File,
    UploadFile,
    status,
    Form,
    BackgroundTasks,
    Cookie,

)
import secrets
import uuid
from datetime import datetime, timezone, date
# from slowapi import (
#     Limiter,
#     _rate_limit_exceeded_handler
# )
# from slowapi.errors import RateLimitExceeded
from pydantic import TypeAdapter, model_validator, ValidationError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import func, or_, select, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from project_part.core.secury import (
    hash_password,
    verify_password,
    Get_current_user,
    garante_escopo_territorial,
    create_token,
    create_refresh_token,
    gerar_e_registar_refresh_token
    )
from project_part.db import session
from project_part.db.cache import get_redis
from project_part.db.session import get_session
from project_part.core.rate_limit import limiter
from project_part.core.setting import settings
from project_part.core.cloudinary_config import (
    compensar_upload_orfao,
    upload_imagem_geral,
    apagar_foto_perfil_cloudinary,
    compensar_upload_orfao
)
from project_part.api.auth.util import set_auth_cookies
from project_part.services.claudflare_turnfile import verificar_turnstile
from project_part.services.email_service.solicitacao_cartao_militante import enviar_email_solicitacao_cartao_militante
from project_part.services.email_service.solicitacao_militancia import enviar_email_solicitacao_militancia
from project_part.services.email_service.confirmar_email_cadastro_user import enviar_email_confirmacao_cadastro_user_async
from project_part.services.email_service.email_cadastro_realizado_sucesso import email_sucesso_cadastro_async
from project_part.model.models import (
    Municipio,
    Provincia,
    Role,
    User,
    AdminScope,
    EstadoCivil,
    CartaoMilitante,
    SolicitacaoCartao,
    Notification,
    StatusSolicitacao,
    Genero,
    SolicitacaoMilitancia,
    CadastrarComo,
    RoleCategoriaNotificacao,
    UserRefreshToken,
)

from .schemas import (
    UserBase,
    ListarUser,
    UpgradeUser,
    UpgradePassWord,
    LimitUser,
    ListarUserBase,
    CardBase,
    ConfirmarEmailSchema,
    NotificationResponse,
    NotificationListResponse,
    DeleteUser,
)

logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]
Redis = Annotated[AsyncRedis, Depends(get_redis)]
Paginacao = Annotated[LimitUser, Depends()]
Claudflare_turnfile = Annotated[bool, Depends(verificar_turnstile)]
ScopeValid =  Annotated[AdminScope, Depends(garante_escopo_territorial)]

user = APIRouter(prefix='/user', tags=['User'])



FILE_READ_TIMEOUT_SECONDS = 30.0
MAX_FILE_SIZE = 5 * 1024 * 1024
admin_id = 1
ROLE_MILITANTE_ID = 2
ROLE_SIMPATIZANTE_ID = 3

ALLOWED_EXTENSIONS = {"jpg", "jpeg"}
ALLOWED_CONTENT_TYPES = {
    "image/jpg",
    "image/jpeg"
}
Image.MAX_IMAGE_PIXELS = 4194304
MAX_WIDTH = 2048
MAX_HEIGHT = 2048
PASTA_ALVO = "perfis_usuarios"
PREFIXO_ARQUIVO = "avatar"



@user.post('/create', status_code=HTTPStatus.CREATED)
@limiter.limit("3/minute; 100/day")
async def create_user(
    request: Request,
    response: Response,
    caches: Redis,
    session: Session,
    backgroundTasks: BackgroundTasks,
    # _captcha: Claudflare_turnfile,
    nome_completo: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirmar_password: str = Form(...),
    data_nascimento: date = Form(...),
    nif: str = Form(...),
    telefone: str = Form(...),
    militante_numero: str | None = Form(None),
    genero: Genero = Form(default=Genero.HOMEM),
    foi_militante: bool = Form(default=False),
    cadastrar_militante: CadastrarComo = Form(default=CadastrarComo.MILITANTE),
    estado_civil: EstadoCivil = Form(default=EstadoCivil.SOLTEIRO),
    nome_provincia: str = Form(...),
    nome_municipio: str = Form(...),
    foto_perfil: UploadFile = File(..., description="Foto de perfil obrigatória (JPEG/JPG, max 5MB)"),
):
    """
    Cadastra um novo usuário no sistema aplicando validações estritas de negócio (NIF, Maioridade, Telefone).
    Executa upload assíncrono para o Cloudinary e invalida caches do Redis em O(1).
    """

    # --- 1. Validação do arquivo: extensão, timeout, tamanho e conteúdo real (magic bytes) ---
    if not foto_perfil.filename:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="A foto de perfil é obrigatória."
        )

    extensao = foto_perfil.filename.split(".")[-1].lower()
    if extensao not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Formato de imagem inválido. Use apenas JPG, JPEG."
        )

    async def _ler_arquivo_com_limite() -> bytes:
        buffer = bytearray()
        while True:
            chunk = await foto_perfil.read(1024 * 1024)  # 1MB por vez
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="A foto de perfil não pode ser maior que 5MB."
                )
        return bytes(buffer)

    try:
        conteudo_bytes = await asyncio.wait_for(
            _ler_arquivo_com_limite(),
            timeout=FILE_READ_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("Timeout ao receber upload de foto de perfil (filename=%s).", foto_perfil.filename)
        raise HTTPException(
            status_code=HTTPStatus.REQUEST_TIMEOUT,
            detail="Tempo excedido ao receber o arquivo. Tente novamente com uma conexão mais estável."
        )
    except HTTPException:
        raise
    finally:
        await foto_perfil.close()

    if len(conteudo_bytes) == 0:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="A foto de perfil enviada está vazia."
        )

    kind = filetype.guess(conteudo_bytes)
    if kind is None or kind.mime not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="O conteúdo do arquivo não corresponde a uma imagem válida."
        )

    # --- 2. Regras de negócio sobre militante ---
    num_militante_final = None

    if militante_numero and cadastrar_militante == CadastrarComo.SIMPATIZANTE:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="O simpatizante nao deve ter número de militante."
        )

    if cadastrar_militante == CadastrarComo.MILITANTE:
        tentativas = 0
        while tentativas < 5:
            ano_atual = datetime.now(timezone.utc).year
            chave_aleatoria = secrets.token_hex(3).upper()
            num_militante_final = f'UNITA.{ano_atual}-{chave_aleatoria}'

            numero_exists = await session.scalar(
                select(User.id).where(User.militante_numero == num_militante_final)
            )
            if not numero_exists:
                break
            tentativas += 1
        else:
            logger.error("Falha crítica: Excedeu o limite de tentativas para gerar um número de cartão único.")
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail="Erro de infraestrutura ao gerar número de cartão."
            )

    #Gerar codigo de verificacao de email
    secret_number = secrets.randbelow(900000) + 100000  # Gera um número de 6 dígitos entre 100000 e 999999

    #enviar email
    # try:
    #     await enviar_email_confirmacao_cadastro_user_async(email_destino=email, secret_number=secret_number, nome_completo=nome_completo)
    #     logger.info("E-mail de confirmação enviado com sucesso para %s", email)
    # except Exception as e:
    #     logger.error("Falha ao enviar e-mail de confirmação para %s: %s", email, str(e))
    #     raise HTTPException(
    #         status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    #         detail="Falha ao enviar e-mail de confirmação. Tente novamente mais tarde."
    #     )

    # --- 3. Validação Pydantic ---
    try:
        dados_validados = UserBase(
            nome_completo=nome_completo,
            email=email,
            password=password,
            confirmar_password=confirmar_password,
            data_nascimento=data_nascimento,
            nif=nif,
            telefone=telefone,
            genero=genero,
            estado_civil=estado_civil,
            nome_provincia=nome_provincia,
            foi_militante=foi_militante,
            cadastrar_militante=cadastrar_militante,
            nome_municipio=nome_municipio,
            militante_numero=num_militante_final,
            codigo_verificacao_email=secret_number
        )
    except ValidationError as e:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            detail=e.errors(include_url=False, include_context=False)
        )

    # --- 4. Checagens de unicidade e integridade referencial ---
    condicoes = [
        User.email == dados_validados.email,
        User.nif == dados_validados.nif
    ]
    if dados_validados.militante_numero:
        condicoes.append(User.militante_numero == dados_validados.militante_numero)

    existent_user = await session.scalar(select(User).where(or_(*condicoes)))
    if existent_user:
        if existent_user.email == dados_validados.email:
            msg = "O e-mail informado já está cadastrado."
        elif existent_user.nif == dados_validados.nif:
            msg = "O NIF informado já está cadastrado."
        else:
            msg = "O número de militante gerado colidiu. Tente novamente."
        raise HTTPException(status_code=HTTPStatus.CONFLICT, detail=msg)

    provincia_banco = await session.scalar(
        select(Provincia).where(Provincia.nome_provincia == dados_validados.nome_provincia)
    )
    if not provincia_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Província não encontrada no território nacional."
        )

    municipio_banco = await session.scalar(
        select(Municipio).where(
            Municipio.nome_municipio == dados_validados.nome_municipio,
            Municipio.id_provincia == provincia_banco.id
        )
    )
    if not municipio_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"O município '{dados_validados.nome_municipio}' não pertence à província '{dados_validados.nome_provincia}'."
        )

    id_role_alvo = ROLE_MILITANTE_ID if cadastrar_militante == CadastrarComo.MILITANTE else ROLE_SIMPATIZANTE_ID
    role_banco = await session.scalar(select(Role).where(Role.id == id_role_alvo))
    if not role_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="A permissão de acesso especificada não está configurada no sistema."
        )

    # --- 5. Persistência ---
    password_hash = await asyncio.to_thread(hash_password, dados_validados.password)
    novo_usuario = User(
        nome_completo=dados_validados.nome_completo,
        email=dados_validados.email,
        password_hash=password_hash,
        data_nascimento=dados_validados.data_nascimento,
        nif=dados_validados.nif,
        militante_numero=dados_validados.militante_numero,
        telefone=dados_validados.telefone,
        foi_militante=dados_validados.foi_militante,
        cadastrar_militante=dados_validados.cadastrar_militante,
        provincia_id=provincia_banco.id,
        municipio_id=municipio_banco.id,
        role_id=role_banco.id,
        genero=dados_validados.genero,
        estado_civil=dados_validados.estado_civil.value,
        # codigo_verificacao_email=dados_validados.codigo_verificacao_email,
        image_url=None
    )
    novo_usuario.criado_em = datetime.now(timezone.utc)
    # --- 5a. Reserva o registro (sem tocar em serviço externo ainda) ---
    try:
        session.add(novo_usuario)
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Erro de integridade relacional ao registrar documentos."
        )
    except Exception as e:
        await session.rollback()
        logger.critical("Erro catastrófico ao reservar usuário: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno de processamento no servidor."
        )
    

    # --- 5b. Upload da imagem (efeito colateral externo) ---
    try:
        url_secure =await asyncio.wait_for(
            upload_imagem_geral(
                file_bytes=conteudo_bytes,
                identificador=str(novo_usuario.id),
                pasta_alvo="perfis_usuarios",
                prefixo_arquivo="avatar"
            ),
            timeout=30
        )
    except Exception as e:
        # Nada foi commitado ainda, então basta descartar a transação pendente.
        # Sem imagem órfã aqui, pois o upload em si falhou.
        await session.rollback()
        logger.error("Falha ao subir imagem para o Cloudinary: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Falha ao salvar imagem de perfil no serviço de nuvem."
        )

    novo_usuario.image_url = url_secure

    # --- 5c. Commit final. Se falhar aqui, a imagem JÁ foi enviada -> compensar. ---
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # await _compensar_upload_orfao(str(novo_usuario.id))
        await compensar_upload_orfao(f"perfis_usuarios/avatar_{novo_usuario.id}")

        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Erro de integridade relacional ao registrar documentos."
        )
    except Exception as e:
        await session.rollback()
        await compensar_upload_orfao(str(novo_usuario.id))
        logger.critical("Erro catastrófico ao commitar usuário após upload: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno de processamento no servidor."
        )

    # --- 6. Pós-commit: cache (não-bloqueante, nunca deve derrubar a resposta de sucesso) ---
    try:
        await caches.incr("v1:usuarios:lista:versao")
    except Exception as cache_err:
        logger.error("Falha não-bloqueante ao atualizar versão do cache no Redis: %s", cache_err)

    destinatario_tipo = None
    tipo = None
    if novo_usuario.cadastrar_militante == CadastrarComo.MILITANTE:
        destinatario_tipo = "MILITANTE"
        tipo = "Militante"
    elif novo_usuario.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
        destinatario_tipo = "SIMPATIZANTE"
        tipo = "Simpatizante"

    notification = Notification(
        user_id=novo_usuario.id,
        titulo="Bem-vindo à UNITA PGM",
        mensagem=f"Olá {novo_usuario.nome_completo}, seja bem-vindo à UNITA PGM! O seu cadastro como {tipo} foi realizado com sucesso.",
        categoria=RoleCategoriaNotificacao.BEM_VINDO,
        criado_as=datetime.now(timezone.utc),
        destinatario=destinatario_tipo
    )

    try:
        session.add(notification)
        await session.commit()
    except Exception as e:
        logger.error("Falha ao criar notificação de boas-vindas para o usuário %s: %s", novo_usuario.id, str(e))
        # Não interrompe o fluxo principal, apenas loga o erro.
        
    
    try:
        backgroundTasks.add_task(email_sucesso_cadastro_async, novo_usuario.nome_completo, novo_usuario.email)
    except Exception as e:
        logger.error("Falha ao enviar e-mail para %s: %s", novo_usuario.email, str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao enviar e-mail de cadastro.")
    # agora = datetime.now(timezone.utc)
    token_gerado = create_token({'sub': str(novo_usuario.id)})

    ip_address = (
        request.headers.get("x-forwarded-for")
        or (
                request.client.host
                if request.client
                else None
            )
        )
    if not ip_address:
        ip_address = request.client.host if request.client else None

    # 3. Capturar o User-Agent (Navegador/Dispositivo)
    user_agent = request.headers.get("user-agent")

    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,      # <-- Faltava este argumento!
        user_id=novo_usuario.id, 
        ip=ip_address, 
        user_agent=user_agent
    )
    set_auth_cookies(
            response=response,
            access_token=token_gerado,
            refresh_token=refresh_gerado,
        )
    response.headers["Cache-Control"] = "no-store"
    
    return {
        "status": "success",
        "message": "Autenticação realizada com sucesso.",
    }
    

# @user.post("/confirm-email", status_code=status.HTTP_200_OK)
# @limiter.limit("1/minute; 10/day")
# async def confirmar_email_cadastro(request: Request, dados: ConfirmarEmailSchema, session: Session):
#     quary = select(User).where(User.email == dados.email)
#     user = await session.scalar(quary)
#     if not user:
#         logger.warning("Tentativa de confirmação de e-mail para e-mail não cadastrado: %s", dados.email)
#         raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    

#     if user.codigo_verificacao != dados.codigo:
#         raise HTTPException(status_code=400, detail="Código de verificação inválido ou expirado")

#     try:
#         user.ativo = True
#         user.codigo_verificacao_email = None
#         session.add(user)
#         await session.commit()
#         return {"message": "E-mail confirmado com sucesso! A sua conta está ativa."}
#     except Exception as e:
#         await session.rollback()
#         logger.error("Erro ao ativar conta do usuário %s: %s", user.email, str(e))
#         raise HTTPException(status_code=500, detail="Erro interno ao ativar a conta do usuário")


# @user.post("/create", status_code=status.HTTP_202_ACCEPTED)
# @limiter.limit("3/minute; 110/day")
# async def create_user(
#     request: Request,
#     caches: Redis,
#     session: Session,
#     backgroundTasks: BackgroundTasks,
#     nome_completo: str = Form(...),
#     email: str = Form(...),
#     password: str = Form(...),
#     data_nascimento: date = Form(...),
#     nif: str = Form(...),
#     telefone: str = Form(...),
#     militante_numero: str | None = Form(None),
#     genero: Genero = Form(default=Genero.HOMEM),
#     foi_militante: bool = Form(default=False),
#     cadastrar_militante: CadastrarComo = Form(default=CadastrarComo.MILITANTE),
#     estado_civil: EstadoCivil = Form(default=EstadoCivil.SOLTEIRO),
#     nome_provincia: str = Form(...),
#     nome_municipio: str = Form(...),
#     foto_perfil: UploadFile = File(..., description="Foto de perfil obrigatória (JPEG/JPG, max 5MB)"),
# ):
#     # --- 1. Checagens antecipadas de unicidade e integridade ---
#     logger.info("Iniciando processo de cadastro para e-mail: %s, NIF: %s", email, nif)
#     condicoes = [
#         User.email == email,
#         User.nif == nif
#     ]
#     existent_user = await session.scalar(select(User).where(or_(*condicoes)))
#     if existent_user:
#         if existent_user.email == email:
#             logger.warning("Tentativa de cadastro com e-mail já existente: %s", email)
#             msg = "O e-mail informado já está cadastrado."
#         else:
#             logger.warning("Tentativa de cadastro com NIF já existente: %s", nif)
#             msg = "O NIF informado já está cadastrado."
#         raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)

#     provincia_banco = await session.scalar(
#         select(Provincia).where(Provincia.nome_provincia == nome_provincia)
#     )
#     if not provincia_banco:
#         logger.warning("Tentativa de cadastro com província inexistente: %s", nome_provincia)
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Província não encontrada no território nacional."
#         )

#     municipio_banco = await session.scalar(
#         select(Municipio).where(
#             Municipio.nome_municipio == nome_municipio, 
#             Municipio.id_provincia == provincia_banco.id
#         )
#     )
#     if not municipio_banco:
#         logger.warning("Tentativa de cadastro com município inexistente: %s", nome_municipio)
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=f"O município '{nome_municipio}' não pertence à província '{nome_provincia}'."
#         )

#     id_role_alvo = ROLE_MILITANTE_ID if cadastrar_militante == CadastrarComo.MILITANTE else ROLE_SIMPATIZANTE_ID
#     role_banco = await session.scalar(select(Role).where(Role.id == id_role_alvo))
#     if not role_banco:
#         logger.warning("Tentativa de cadastro com role inexistente: %s", id_role_alvo)
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="A permissão de acesso especificada não está configurada no sistema."
#         )

#     # --- 2. Validação do arquivo de imagem ---
#     if not foto_perfil.filename:
#         logger.warning("Tentativa de cadastro sem foto de perfil para e-mail: %s", email)
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A foto de perfil é obrigatória.")

#     extensao = foto_perfil.filename.split(".")[-1].lower()
#     if extensao not in ALLOWED_EXTENSIONS:
#         logger.warning("Tentativa de cadastro com formato de imagem inválido: %s", foto_perfil.filename)
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Formato de imagem inválido. Use apenas JPG, JPEG.")

#     async def _ler_arquivo_com_limite() -> bytes:
#         buffer = bytearray()
#         # Pedaços menores evitam picos de consumo de memória RAM
#         while True:
#             chunk = await foto_perfil.read(256 * 1024) 
#             if not chunk:
#                 break
#             buffer.extend(chunk)
#             if len(buffer) > MAX_FILE_SIZE:
#                 logger.warning("Tentativa de cadastro com foto de perfil maior que 5MB: %s", foto_perfil.filename)
#                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A foto de perfil não pode ser maior que 5MB.")
#         return bytes(buffer)

#     try:
#         conteudo_bytes = await asyncio.wait_for(_ler_arquivo_com_limite(), timeout=FILE_READ_TIMEOUT_SECONDS)
#     except asyncio.TimeoutError:
#         raise HTTPException(status_code=status.HTTP_REQUEST_TIMEOUT, detail="Tempo excedido ao receber o arquivo.")
#     finally:
#         await foto_perfil.close()

#     kind = filetype.guess(conteudo_bytes)
#     if kind is None or kind.mime not in ALLOWED_CONTENT_TYPES:
#         logger.warning("Tentativa de cadastro com conteúdo de arquivo inválido: %s", foto_perfil.filename)
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O conteúdo do arquivo não corresponde a uma imagem válida.")

#     # --- 3. Regras de negócio sobre número de militante ---
#     num_militante_final = None
#     if militante_numero and cadastrar_militante == CadastrarComo.SIMPATIZANTE:
#         logger.warning("Tentativa de cadastro com número de militante para simpatizante: %s", email)
#         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O simpatizante não deve ter número de militante.")

#     if cadastrar_militante == CadastrarComo.MILITANTE:
#         tentativas = 0
#         while tentativas < 5:
#             ano_atual = datetime.now(timezone.utc).year
#             chave_aleatoria = secrets.token_hex(3).upper()
#             num_militante_final = f'UNITA.{ano_atual}-{chave_aleatoria}'
#             numero_exists = await session.scalar(select(User.id).where(User.militante_numero == num_militante_final))
#             if not numero_exists:
#                 break
#             tentativas += 1
#         else:
#             logger.error("Falha ao gerar número de cartão único para o e-mail: %s", email)
#             raise HTTPException(status_code=status.HTTP_INTERNAL_SERVER_ERROR, detail="Erro ao gerar número de cartão único.")

#     # --- 4. Geração do código e Envio do E-mail ---
#     secret_number = secrets.randbelow(900000) + 100000

#     try:
#         backgroundTasks.add_task(enviar_email_confirmacao_cadastro_user_async, email_destino=email, secret_number=secret_number, nome_completo=nome_completo)
#     except Exception as e:
#         logger.error("Falha ao injetar tarefa de e-mail para %s: %s", email, str(e))
#         raise HTTPException(status_code=status.HTTP_INTERNAL_SERVER_ERROR, detail="Falha ao processar e-mail de confirmação.")

#     # Criptografa a senha em uma thread separada para não bloquear o loop de eventos
#     password_hash = await asyncio.to_thread(hash_password, password)

#     # --- 5. Persistência Temporária no Redis (Expira em 15 minutos) ---
#     # Convertendo os bytes da imagem de forma segura para string Base64
#     foto_b64 = base64.b64encode(conteudo_bytes).decode('utf-8')

#     dados_temporarios = {
#         "nome_completo": nome_completo,
#         "email": email,
#         "password_hash": password_hash,
#         "data_nascimento": data_nascimento.isoformat(),
#         "nif": nif,
#         "telefone": telefone,
#         "genero": genero.value,
#         "foi_militante": foi_militante,
#         "cadastrar_militante": cadastrar_militante.value,
#         "estado_civil": estado_civil.value,
#         "id_provincia": str(provincia_banco.id),
#         "id_municipio": str(municipio_banco.id),
#         "id_role": str(role_banco.id),
#         "militante_numero": num_militante_final,
#         "foto_perfil_b64": foto_b64,
#         "codigo_verificacao": secret_number
#     }

#     chave_redis = f"cadastro_pendente:{email}"
#     await caches.setex(chave_redis, 900, json.dumps(dados_temporarios)) # 900 segundos = 15 minutos

#     return {"message": "Código de ativação enviado para o e-mail. Confirme em até 15 minutos."}

# @user.post("/confirm-email", status_code=status.HTTP_201_CREATED)
# @limiter.limit("3/minute; 10/day")
# async def confirmar_email_cadastro(
#     request: Request,
#     response: Response, 
#     dados: ConfirmarEmailSchema, 
#     caches: Redis, 
#     session: Session,
#     backgroundTasks: BackgroundTasks
# ):
#     # 1. Recupera os dados temporários do Redis
#     chave_redis = f"cadastro_pendente:{dados.email}"
#     dados_cache = await caches.get(chave_redis)

#     if not dados_cache:
#         logger.warning("Tentativa de confirmação expirada ou inexistente para o e-mail: %s", dados.email)
#         raise HTTPException(
#             status_code=HTTPStatus.BAD_REQUEST, 
#             detail="O tempo de validação (15 min) expirou ou o registo não existe. Por favor, registe-se novamente."
#         )

#     usuario_data = json.loads(dados_cache)

#     # 2. Validação do código de verificação
#     if usuario_data["codigo_verificacao"] != dados.codigo:
#         raise HTTPException(
#             status_code=HTTPStatus.BAD_REQUEST, 
#             detail="Código de verificação inválido ou expirado."
#         )

#     # Re-checagem rápida de segurança na BD para garantir que o NIF/E-mail não foram tomados nos últimos 15 min
#     usuario_duplicado = await session.scalar(
#         select(User.id).where((User.email == dados.email) | (User.nif == usuario_data["nif"]))
#     )
#     if usuario_duplicado:
#         await caches.delete(chave_redis)
#         raise HTTPException(
#             status_code=HTTPStatus.CONFLICT, 
#             detail="Estes dados de e-mail ou NIF já foram registados por outra conta ativa."
#         )

#     # 3. Cria a instância do usuário na memória para obter o ID (sem commitar)
#     novo_usuario = User(
#         nome_completo=usuario_data["nome_completo"],
#         email=usuario_data["email"],
#         password_hash=usuario_data["password_hash"],
#         data_nascimento=date.fromisoformat(usuario_data["data_nascimento"]),
#         nif=usuario_data["nif"],
#         militante_numero=usuario_data["militante_numero"],
#         telefone=usuario_data["telefone"],
#         foi_militante=usuario_data["foi_militante"],
#         cadastrar_militante=usuario_data["cadastrar_militante"],
#         provincia_id=usuario_data["id_provincia"],
#         municipio_id=usuario_data["id_municipio"],
#         role_id=usuario_data["id_role"],
#         genero=usuario_data["genero"],
#         estado_civil=usuario_data["estado_civil"],
#         codigo_verificacao_email=None,
#         image_url=None
#     )

#     try:
#         session.add(novo_usuario)
#         await session.flush()
#     except IntegrityError:
#         await session.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_CONFLICT,
#             detail="Erro de integridade relacional ao registar documentos."
#         )
#     except Exception as e:
#         await session.rollback()
#         logger.critical("Erro catastrófico ao reservar usuário: %s", e)
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Erro interno de processamento no servidor."
#         )

#     # --- 5. Descodifica a imagem do Redis e faz o Upload para o Cloudinary ---
#     try:
#         conteudo_bytes = base64.b64decode(usuario_data["foto_perfil_b64"])
        
#         url_secure = await asyncio.wait_for(
#             upload_imagem_geral(
#                 file_bytes=conteudo_bytes,
#                 identificador=str(novo_usuario.id),
#                 pasta_alvo="perfis_usuarios",
#                 prefixo_arquivo="avatar"
#             ),
#             timeout=30.0
#         )
#     except Exception as e:
#         await session.rollback()
#         logger.error("Falha ao subir imagem para o Cloudinary na confirmação: %s", e)
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Falha ao salvar imagem de perfil no serviço de nuvem."
#         )

#     novo_usuario.image_url = url_secure

#     # --- 6. Commit Final e compensação de falhas ---
#     try:
#         await session.commit()
#     except IntegrityError:
#         await session.rollback()
#         await compensar_upload_orfao(f"perfis_usuarios/avatar_{novo_usuario.id}")
#         raise HTTPException(
#             status_code=HTTPStatus.CONFLICT,
#             detail="Erro de integridade relacional ao efetivar o registo."
#         )
#     except Exception as e:
#         await session.rollback()
#         await compensar_upload_orfao(f"perfis_usuarios/avatar_{novo_usuario.id}")
#         logger.critical("Erro catastrófico ao commitar usuário após upload: %s", e)
#         raise HTTPException(
#             status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
#             detail="Erro interno de processamento no servidor."
#         )

#     # --- 7. Pós-commit: Limpeza do Redis e atualização de versão de cache de listas ---
#     try:
#         await caches.delete(chave_redis)
#         await caches.incr("v1:usuarios:lista:versao")
#     except Exception as cache_err:
#         logger.error("Falha não-bloqueante ao atualizar dados do Redis após sucesso: %s", cache_err)


#     try:
#         # await enviar_email_confirmacao_cadastro_user_async(email_destino=dados.email, secret_number=novo_usuario.secret_number, nome_completo=novo_usuario.nome_completo)
#         backgroundTasks.add_task(email_sucesso_cadastro_async, dados.email, novo_usuario.nome_completo)
#     except Exception as e:
#         logger.error("Falha ao enviar e-mail para %s: %s", novo_usuario.email, str(e))
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao enviar e-mail de confirmação.")

#     try:
#         backgroundTasks.add_task(email_sucesso_cadastro_async, novo_usuario.nome_completo, novo_usuario.email)
#     except Exception as e:
#         logger.error("Falha ao enviar e-mail para %s: %s", usuario_data.email, str(e))
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao enviar e-mail de cadastro.")

#     token_gerado = create_token({'sub': str(novo_usuario.id)})
#     refresh_gerado = create_refresh_token({'sub': str(novo_usuario.id)})

#     response.set_cookie(
#         key='access_token',
#         value=token_gerado,
#         httponly=True,
#         secure=True,
#         samesite='none',
#         max_age=60 * 15,
#         path='/',
#     )
#     response.set_cookie(
#         key="refresh_token",
#         value=refresh_gerado,
#         httponly=True,
#         secure=True,
#         samesite="none",
#         max_age=60 * 60 * 24 * 7,
#         path="/auth/refresh",
#     )
#     logger.info("Usuário %s confirmado e logado com sucesso.", novo_usuario.email)
#     return {
#         "status": "success",
#         "message": "E-mail confirmado e utilizador autenticado com sucesso."
#     }




@user.patch('/perfil/password', status_code=HTTPStatus.NO_CONTENT)
@limiter.limit("2/minute; 100/day")
async def atualizar_perfil_password(
    request: Request,
    schemas: UpgradePassWord,
    session: Session,
    current_user: Get_current_user
):
    """
    Altera de forma segura a senha do usuário autenticado.
    Valida a credencial atual e atualiza o hash da senha.
    """
    logger.info(
        'Iniciando processo de alteração de senha para o usuário: %s',
        current_user.email
    )

    if not verify_password(
        schemas.senha_atual,
        current_user.password_hash
    ):
        logger.warning(
            'Falha na alteração de senha: senha atual incorreta para o usuário ID: %s',
            current_user.id
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='A senha atual inserida está incorreta.'
        )

    agora = datetime.now(timezone.utc)
    ultima_alteracao = 60 * 60 * 24 * 30

    if current_user.password_alterado_em is not None:
        if (
            agora.timestamp()
            - current_user.password_alterado_em.timestamp()
            < ultima_alteracao
        ):
            logger.warning(
                'Tentativa de alteração de senha muito frequente para o usuário ID: %s',
                current_user.id
            )
            raise HTTPException(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                detail='A senha só pode ser alterada uma vez a cada 30 dias.'
            )

    crypt_password = await asyncio.to_thread(
        hash_password,
        schemas.nova_senha
    )

    current_user.password_hash = crypt_password
    current_user.atualizado_em = agora
    current_user.password_alterado_em = agora

    try:
        session.add(current_user)
        await session.commit()

        logger.info(
            'Senha do usuário %s atualizada com sucesso.',
            current_user.email
        )

    except IntegrityError as e:
        await session.rollback()

        logger.error(
            'Erro de integridade ao tentar atualizar senha no banco: %s',
            str(e.orig)
        )

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Erro interno de consistência ao processar a requisição.'
        )

    except Exception as e:
        await session.rollback()

        logger.error(
            'Erro desconhecido na alteração da senha do usuário %s: %s',
            current_user.email,
            str(e)
        )

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Não foi possível processar a alteração da senha no momento.'
        )

@user.put('/perfil/upgrade', status_code=HTTPStatus.OK)
@limiter.limit("3/minute; 100/day")
async def perfil(request: Request, schemas: UpgradeUser, caches: Redis, session: Session, current_user: Get_current_user):

    current_role_stmt = select(Role.nome).where(Role.id == current_user.role_id)
    current_role_name = await session.scalar(current_role_stmt)

    if current_role_name == 'admin':
        stmt_prov = select(Provincia.nome_provincia).where(Provincia.id == current_user.provincia_id)
        stmt_mun = select(Municipio.nome_municipio).where(Municipio.id == current_user.municipio_id)
        
        nome_prov_atual = await session.scalar(stmt_prov)
        nome_mun_atual = await session.scalar(stmt_mun)

        if schemas.nome_provincia != nome_prov_atual or schemas.nome_municipio != nome_mun_atual:
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Administradores não podem alterar seu escopo geográfico de atuação sozinhos."
            )

    logger.info('A procurar a província: %s', schemas.nome_provincia)
    provincia_banco = await session.scalar(
        select(Provincia).where(Provincia.nome_provincia == schemas.nome_provincia)
    )

    if not provincia_banco:
        logger.warning('Província não encontrada')
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Província não encontrada'
        )

    logger.info(
        'A procurar o município: %s dentro da província %s',
        schemas.nome_municipio,
        schemas.nome_provincia,
    )
    municipio_banco = await session.scalar(
        select(Municipio).where(
            Municipio.nome_municipio == schemas.nome_municipio,
            Municipio.id_provincia == provincia_banco.id,
        )
    )

    if not municipio_banco:
        logger.warning(
            'Município %s não encontrado na província %s',
            schemas.nome_municipio,
            schemas.nome_provincia,
        )
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f'O município "{schemas.nome_municipio}" não pertence à província "{schemas.nome_provincia}"'
        )

    logger.info('Atualizar os dados do usuario %s', current_user.email)
    current_user.nome_completo = schemas.nome_completo
    current_user.email = schemas.email
    current_user.telefone = schemas.telefone
    current_user.provincia_id = provincia_banco.id
    current_user.municipio_id = municipio_banco.id
    current_user.atualizado_em = datetime.now(timezone.utc)
    current_user.estado_civil = schemas.estado_civil

    try:
        session.add(current_user)
        await session.commit()

        await caches.incr("v1:usuarios:lista:versao")
        logger.info('Versão do cache de usuários incrementada globalmente devido à atualização.')
        
        return {'msg': 'Usuário atualizado com sucesso!'}

    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro de integridade ao atualizar usuário: %s', str(e.orig))
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT, 
            detail='O e-mail informado já está sendo utilizado por outro usuário.'
        )
    except Exception as e:
        await session.rollback()
        logger.error('Erro desconhecido na atualização do usuário: %s', str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail='Não foi possível processar a atualização dos dados.'
        )

@user.get('/perfil', status_code=HTTPStatus.OK, response_model=ListarUserBase)
async def obter_meu_perfil(
    session: Session, 
    current_user: Get_current_user
):
    """
    Retorna os dados completos do perfil do usuário autenticado.
    """
    logger.info(f"Usuário {current_user.id} solicitou os dados do seu próprio perfil.")
    
    query = select(User).where(User.id == current_user.id).options(
        selectinload(User.scope),
        selectinload(User.municipio),
        selectinload(User.provincia),
        selectinload(User.role)
        )
    usuario_completo = await session.scalar(query)
    
    return usuario_completo


# @user.patch("/upload-foto", status_code=status.HTTP_200_OK)
# async def atualizar_foto_perfil(session: Session, current_user: Get_current_user, arquivo: UploadFile = File(..., description="Selecione uma imagem JPG ou PNG") ):
#     # 1. Validar a extensão do arquivo
#     extensao = arquivo.filename.split(".")[-1].lower()
#     if extensao not in ALLOWED_EXTENSIONS:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST, 
#             detail="Apenas imagens JPG, JPEG são permitidas."
#         )

#     # 2. Validar o tamanho do arquivo (Max 5MB)
#     conteudo_bytes = await arquivo.read()
#     if len(conteudo_bytes) > MAX_FILE_SIZE:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="A imagem não pode ser maior do que 5MB."
#         )

#     try:
#         # 3. Executar o upload (O Cloudinary substitui automaticamente o arquivo antigo)
#         url_secure_cloudinary = await upload_imagem_geral(
#             file_bytes=conteudo_bytes,
#             identificador=str(current_user.id),
#             pasta_alvo="perfis_usuarios",
#             prefixo_arquivo="avatar"
#         )
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Falha ao atualizar a imagem no serviço de nuvem."
#         )
#     finally:
#         await arquivo.close()

#     # 4. Salvar a URL na tabela do usuário (se já for a mesma, o SQLAlchemy ignora ou atualiza o AuditLog)
#     if hasattr(current_user, "image_url"):
#         current_user.image_url = url_secure_cloudinary
#     else:
#         current_user.foto_url = url_secure_cloudinary
    
#     try:
#         session.add(current_user)
#         await session.commit() 
#     except Exception as e:
#         await session.rollback()
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Erro ao salvar os dados de perfil na base de dados."
#         )

#     return {
#         "msg": "Foto de perfil substituída com sucesso no Cloudinary!",
#         "foto_url": url_secure_cloudinary
#     }




def _higienizar_e_reprocessar_jpeg(conteudo_bruto: bytes) -> bytes:
    """
    Executado em uma Worker Thread separada (CPU-Bound).
    Remove EXIF/Payloads maliciosos e reconstrói a imagem do zero.
    """
    stream_imagem = io.BytesIO(conteudo_bruto)
    
    try:
        with Image.open(stream_imagem) as img_validadora:
            img_validadora.verify()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Estrutura de imagem corrompida ou inválida."
        )
    
    stream_imagem.seek(0)
    
    with Image.open(stream_imagem) as img:
        img = ImageOps.exif_transpose(img)
        
        if img.width > MAX_WIDTH or img.height > MAX_HEIGHT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Dimensões abusivas. Máximo permitido: {MAX_WIDTH}x{MAX_HEIGHT} pixels."
            )
            
        icc_profile = img.info.get("icc_profile")
        img = img.convert("RGB")
        
        buffer_saida = io.BytesIO()
        img.save(
            buffer_saida, 
            format="JPEG", 
            quality=85, 
            optimize=True, 
            icc_profile=icc_profile
        )
        conteudo_processado = buffer_saida.getvalue()
        buffer_saida.close()
        return conteudo_processado


async def upload_imagem_geral(
    file_bytes: bytes, 
    identificador: str, 
    pasta_alvo: str, 
    prefixo_arquivo: str
) -> str:
    """
    Executa o upload síncrono do Cloudinary numa thread separada (I/O Bound),
    retornando apenas a URL segura gerada pelo serviço.
    """
    public_id_completo = f"{pasta_alvo}/{identificador}"
    
    def _upload():
        # Converte os bytes num ficheiro em memória que o SDK do Cloudinary aceita
        file_stream = io.BytesIO(file_bytes)
        retorno = cloudinary.uploader.upload(
            file_stream,
            public_id=public_id_completo,
            overwrite=True,
            invalidate=True,
            resource_type="image"
        )
        return retorno.get("secure_url")

    # Garante que a chamada bloqueante de rede não congele o Event Loop do FastAPI
    return await asyncio.to_thread(_upload)


def deletar_imagem_cloudinary_por_public_id(public_id: str) -> None:
    """
    Helper síncrono executado em BackgroundTasks.
    Remove uma mídia do Cloudinary utilizando seu Public ID exato.
    """
    try:
        resultado = cloudinary.uploader.destroy(public_id)
        if resultado.get("result") != "ok":
            logger.warning("Cloudinary retornou status inesperado ao deletar %s: %s", public_id, resultado)
    except Exception as e:
        logger.error("Falha crítica ao remover imagem do Cloudinary (public_id=%s): %s", public_id, e)


def _extrair_public_id_da_url(url: str) -> str | None:
    """
    Extrai de forma robusta o public_id do Cloudinary a partir da URL guardada.
    Útil se a sua tabela de utilizadores não possuir uma coluna image_public_id dedicada.
    """
    if not url or "://cloudinary.com" not in url:
        return None
    try:
        # Padrão: .../upload/v12345678/pasta_alvo/nome_do_arquivo.jpg
        partes = url.split("/upload/")[-1].split("/", 1)[-1]
        public_id_com_extensao = partes.split("?")[0] # Remove query params se existirem
        public_id = ".".join(public_id_com_extensao.split(".")[:-1]) # Remove a extensão (.jpg)
        return public_id
    except Exception:
        logger.exception("Não foi possível extrair o public_id da URL: %s", url)
        return None


@user.patch("/upload-foto", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute; 100/day")
async def atualizar_foto_perfil(
    request: Request,
    session: Session,
    current_user: Get_current_user,
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(..., description="Selecione uma imagem JPG ou JPEG (max 5MB)"),
):
    if not arquivo.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo enviado.")


    sufixo = Path(arquivo.filename).suffix.lower()

    if (
        sufixo not in ALLOWED_EXTENSIONS
        and arquivo.content_type not in ALLOWED_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas imagens JPG ou JPEG são permitidas."
        )

    # 2. Leitura com limite estrito de tamanho (64KB chunks para poupar RAM)
    async def _ler_arquivo_com_limite() -> bytes:
        buffer = bytearray()
        while True:
            chunk = await arquivo.read(64 * 1024)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A imagem não pode ser maior do que 5MB."
                )
        return bytes(buffer)

    try:
        conteudo_bruto = await asyncio.wait_for(
            _ler_arquivo_com_limite(), timeout=FILE_READ_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.warning("Timeout no upload da foto do usuário %s", current_user.id)
        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="Tempo limite excedido.")
    finally:
        await arquivo.close()

    if len(conteudo_bruto) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")

    # 3. Validação de Magic Bytes
    kind = filetype.guess(conteudo_bruto)
    if kind is None or kind.mime not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O conteúdo real não é um JPEG válido.")

    # 4. Processamento de imagem em Thread Pool
    try:
        conteudo_sanitizado = await asyncio.to_thread(_higienizar_e_reprocessar_jpeg, conteudo_bruto)
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagem corrompida ou inválida.")
    except Image.DecompressionBombError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resolução abusiva detectada.")
    except HTTPException:
        raise

    # 5. Geração Contratual dos IDs Isolados
    identificador_unico = f"{PREFIXO_ARQUIVO}_{current_user.id}_{int(time.time())}"
    novo_public_id = f"{PASTA_ALVO}/{identificador_unico}"
    
    try:
        url_secure_cloudinary = await upload_imagem_geral(
            file_bytes=conteudo_sanitizado,
            identificador=identificador_unico,
            pasta_alvo=PASTA_ALVO,
            prefixo_arquivo=PREFIXO_ARQUIVO
        )
    except Exception as e:
        logger.error("Falha ao enviar para o Cloudinary (user_id=%s): %s", current_user.id, e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha no serviço de nuvem.")

    # Captura o identificador antigo para limpeza posterior
    # Estratégia de Fallback: Se não houver a coluna image_public_id no banco, extrai da URL antiga
    foto_antiga_public_id = getattr(current_user, "image_public_id", None)
    if not foto_antiga_public_id and current_user.image_url:
        foto_antiga_public_id = _extrair_public_id_da_url(current_user.image_url)

    # 6. Persistência Atómica no Banco de Dados
    try:
        current_user.image_url = url_secure_cloudinary
        if hasattr(current_user, "image_public_id"):
            current_user.image_public_id = novo_public_id
            
        session.add(current_user)
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logger.critical("Erro no DB (user_id=%s). Iniciando Saga de compensação na nuvem.", current_user.id)
        
        # SAGA REVERSÃO: Remove o arquivo isolado criado, pois a persistência falhou
        background_tasks.add_task(deletar_imagem_cloudinary_por_public_id, novo_public_id)
        
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao persistir dados.")

    # 7. Limpeza Pós-Sucesso (Remove de vez a imagem antiga da nuvem)
    if foto_antiga_public_id:
        background_tasks.add_task(deletar_imagem_cloudinary_por_public_id, foto_antiga_public_id)

    return {
        "msg": "Foto de perfil substituída com sucesso!",
        "foto_url": url_secure_cloudinary
    }


# @user.get(
#     '/listar', status_code=HTTPStatus.OK, response_model=ListarUser
# )
# async def Listar(
#     response: Response, 
#     session: Session, 
#     caches: Redis, 
#     current_user: Get_current_user,
#     pagin: Paginacao,
#     scope: ScopeValid
# ):

#     try:
#         versao_cache = (await caches.get("v1:usuarios:lista:versao")) or b"1"
#         versao_cache = versao_cache.decode('utf-8') if isinstance(versao_cache, bytes) else str(versao_cache)
#     except Exception as e:
#         logger.error(f'Falha ao ler versão do cache no Redis: {e}')
#         versao_cache = "fallback"

#     cache_key = f"v1:usuarios:lista:{scope.provincia_id or 'all'}:{scope.municipio_id or 'all'}:sk:{pagin.skip}:lm:{pagin.limit}:v:{versao_cache}"

#     try:
#         user_save = await caches.get(cache_key)
#         if user_save:
#             response.headers['X-Cache-lock'] = 'veio do redis'
#             logger.info('Dados vindo do redis')
#             return json.loads(user_save)
#     except Exception as e:
#         logger.error('Error na solicitacao dos dados do redis: %s', e)

#     logger.info('Buscando dados do postgresSQL...')
    
#     query = select(User).where(User.ativo == True).options(
#         selectinload(User.scope),
#         selectinload(User.provincia), 
#         selectinload(User.municipio),
#         selectinload(User.role)
#     )

#     count_query = select(User.genero).where(User.ativo == True)
    
#     if scope.municipio_id:
#         logger.info(f'Filtrando usuários do município: {scope.municipio_id}')
#         query = query.where(User.municipio_id == scope.municipio_id)
#         count_query = count_query.where(User.municipio_id == scope.municipio_id)
        
#     elif scope.provincia_id:
#         logger.info(f'Filtrando usuários da província: {scope.provincia_id}')
#         query = query.where(User.provincia_id == scope.provincia_id)
#         count_query = count_query.where(User.provincia_id == scope.provincia_id)
        
#     else:
#         logger.info('Super Admin detectado. Trazendo todos os usuários ativos.')


#     contagens = await session.scalars(count_query)
#     lista_generos = contagens.all()

#     total_user = len(lista_generos)
#     total_homens = sum(1 for genero in lista_generos if genero == 'Masculino')
#     total_mulheres = sum(1 for genero in lista_generos if genero == 'Mulher')

#     query = query.order_by(User.criado_em.desc())
#     query = query.offset(pagin.skip).limit(pagin.limit)
#     users = await session.scalars(query)
#     userAll = users.all()

#     if not userAll:
#         logger.warning('Nenhum usuário ativo foi encontrado!')
#         raise HTTPException(
#             status_code=HTTPStatus.NOT_FOUND, 
#             detail='Nenhum usuário ativo foi encontrado!'
#         )

#     resposta_estruturada = {
#         "total_usuarios": total_user,
#         "total_homens": total_homens,
#         "total_mulheres": total_mulheres,
#         "usuarios": [ListarUserBase.model_validate(u).model_dump(mode='json') for u in userAll]
#     }

#     try:
#         await caches.set(cache_key, json.dumps(resposta_estruturada), ex=60)
#         logger.info('Caches guardados com sucesso!')
#     except Exception as e:
#         logger.error('Nao foi possivel guardar os caches no redis: %s', e)

#     response.headers['X-Cache-lock'] = 'veio do postgres'
#     return resposta_estruturada



@user.get(
    '/listar', status_code=status.HTTP_200_OK, response_model=ListarUser
)
async def Listar(
    response: Response, 
    session: Session, 
    caches: Redis, 
    current_user: Get_current_user,
    pagin: Paginacao,
    scope: ScopeValid
):

    # 1. Recuperação da Versão do Cache
    try:
        versao_cache = (await caches.get("v1:usuarios:lista:versao")) or b"1"
        versao_cache = versao_cache.decode('utf-8') if isinstance(versao_cache, bytes) else str(versao_cache)
    except Exception as e:
        logger.error(f'Falha ao ler versão do cache no Redis: {e}')
        versao_cache = "fallback"

    cache_key = f"v1:usuarios:lista:{scope.provincia_id or 'all'}:{scope.municipio_id or 'all'}:sk:{pagin.skip}:lm:{pagin.limit}:v:{versao_cache}"

    # 2. Leitura do Cache Redis
    try:
        user_save = await caches.get(cache_key)
        if user_save:
            response.headers['X-Cache-lock'] = 'veio do redis'
            logger.info('Dados vindo do redis')
            return Response(content=user_save, media_type="application/json", headers=dict(response.headers))
    except Exception as e:
        logger.error('Erro na solicitação dos dados do redis: %s', e)

    logger.info('Buscando dados do postgresSQL...')
    
    # 3. Definição das Queries Base
    query = select(User).where(User.ativo == True).options(
        selectinload(User.scope),
        selectinload(User.provincia), 
        selectinload(User.municipio),
        selectinload(User.role)
    )

    # CORRIGIDO: Agora usa o value real do Enum (HOMEM / MULHER) para não quebrar no Postgres
    count_query = select(
        func.count(User.id).label("total"),
        func.sum(case((User.genero == Genero.HOMEM.value, 1), else_=0)).label("homens"),
        func.sum(case((User.genero == Genero.MULHER.value, 1), else_=0)).label("mulheres")
    ).where(User.ativo == True)

    # 4. Aplicação dos Filtros de Escopo Geográfico (Aplica a AMBAS as queries)
    if scope.municipio_id:
        logger.info(f'Filtrando usuários do município: {scope.municipio_id}')
        query = query.where(User.municipio_id == scope.municipio_id)
        count_query = count_query.where(User.municipio_id == scope.municipio_id)
    elif scope.provincia_id:
        logger.info(f'Filtrando usuários da província: {scope.provincia_id}')
        query = query.where(User.provincia_id == scope.provincia_id)
        count_query = count_query.where(User.provincia_id == scope.provincia_id)
    else:
        logger.info('Super Admin detectado. Trazendo todos os usuários ativos.')

    # 5. Execução ÚNICA das Contagens (Extremamente rápido e seguro)
    result_counts = await session.execute(count_query)
    counts = result_counts.one()
    
    # Mapeia os resultados da única linha retornada pelo banco
    total_user = counts.total or 0
    total_homens = counts.homens or 0
    total_mulheres = counts.mulheres or 0

    # 6. Execução da Busca Paginada de Utilizadores
    query = query.order_by(User.criado_em.desc()).offset(pagin.skip).limit(pagin.limit)
    users = await session.scalars(query)
    userAll = users.all()

    if not userAll:
        logger.warning('Nenhum usuário ativo foi encontrado!')
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail='Nenhum usuário ativo foi encontrado!'
        )

    # 7. Construção do Objeto de Resposta Alinhado com o Pydantic
    resposta_obj = ListarUser(
        total_user=total_user,
        total_homens=total_homens,
        total_mulheres=total_mulheres,
        usuarios=userAll
    )

    # 8. Salvando o JSON estruturado no Cache
    try:
        json_para_cache = resposta_obj.model_dump_json()
        await caches.set(cache_key, json_para_cache, ex=60)
        logger.info('Caches guardados com sucesso!')
    except Exception as e:
        logger.error('Nao foi possivel guardar os caches no redis: %s', e)

    response.headers['X-Cache-lock'] = 'veio do postgres'
    return resposta_obj




@user.post('/solicitar/militancia', status_code=HTTPStatus.CREATED)
@limiter.limit("100/minute")
async def solicitar_militancia(request: Request, session: Session, current_user: Get_current_user):
    if current_user.cadastrar_militante != 'SIMPATIZANTE':
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=f'Usuario {current_user.email} precisar ser simpatizante')
    
    solicitacao_existente = await session.scalar(
        select(SolicitacaoMilitancia).where(
            SolicitacaoMilitancia.user_id == current_user.id, 
            SolicitacaoMilitancia.status == StatusSolicitacao.PENDENTE
        )
    )
    agora = datetime.now(timezone.utc)
    if solicitacao_existente:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui uma solicitação em análise.")

    nova_solicitacao = SolicitacaoMilitancia(user_id=current_user.id, status=StatusSolicitacao.PENDENTE)
    session.add(nova_solicitacao)

   
    logger.info('Busca a solicitação pendente deste usuário para garantir o fluxo correto')
    solicitacao = await session.scalar(
    select(SolicitacaoMilitancia).where(
        SolicitacaoMilitancia.user_id == current_user.id, SolicitacaoMilitancia.status == StatusSolicitacao.PENDENTE
        )
    )
    if not solicitacao:
        raise HTTPException(
           status_code=HTTPStatus.BAD_REQUEST, detail='Nenhuma solicitação pendente encontrada para este usuário.'
       )
   
       # if not usuario_banco.militante_numero:
       #     raise HTTPException(
       #         status_code=HTTPStatus.BAD_REQUEST,
       #         detail="Operação rejeitada. O usuário precisa primeiro ter um número de militante atribuído."
       #     )
   
       # agora = datetime.now(timezone.utc)
   
       # if scope.provincia_id is not None:
       #     if usuario_banco.provincia_id != scope.provincia_id:
       #         raise HTTPException(
       #             status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
       #         )
       # elif scope.municipio_id is not None:
       #     if usuario_banco.municipio_id != scope.municipio_id:
       #         raise HTTPException(
       #             status_code=HTTPStatus.FORBIDDEN, detail='Operação negada. Região geográfica diferente.'
       #         )
   
    tentativas = 0
    num_militante_final = None

    if not current_user.militante_numero:
        while tentativas < 5:
            ano_atual = datetime.now(timezone.utc).year
            chave_aleatoria = secrets.token_hex(3)[:6].upper()
            num_militante_final = f'UNITA.{ano_atual}-{chave_aleatoria}'
            numero_exists = await session.scalar(select(User).where(User.militante_numero == num_militante_final))
            if not numero_exists:
               break
            tentativas += 1
        else:
            logger.error('Falha crítica: Excedeu o limite de tentativas para gerar um número de cartão único.')
            raise HTTPException(
               status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro de infraestrutura ao gerar número de cartão.'
            )
   
    solicitacao.status = StatusSolicitacao.APROVADO
    current_user.cadastrar_militante = CadastrarComo.MILITANTE
    current_user.role_id = ROLE_MILITANTE_ID
    current_user.militante_numero = num_militante_final
    current_user.atualizado_em = agora
   
    nova_notificacao = Notification(
        user_id=current_user.id,
        titulo='Solicitacao de Militancia aprovado!',
        mensagem=f'Olá {current_user.nome_completo}, a sua solicitacao de militancia foi aprovada com sucesso!',
        destinatario="MILITANTE",
    )
   
   
    try:
        session.add(solicitacao)
        session.add(nova_notificacao)
   
        await session.commit()
   
        # backgroundTasks.add_task(
        #     enviar_resposta_solicitacao_militancia,
        #     email_destino=usuario_banco.email,
        #     nome_simpatizante=usuario_banco.nome_completo,
        #     status_pedido="Aprovado",
        #     observacoes=observacao
        # )
   
        logger.info('Solicitacao de militancia  do usuario %s finalizado com sucesso.', current_user.email)
        return {'msg': f'Solicitacao de militancia  do usuario {current_user.email} finalizado com sucesso.'}
   
    except IntegrityError as e:
        await session.rollback()
        logger.error('Erro crítico de integridade ao aprovar a militancia do usuário %s: %s', current_user.email, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail='Erro interno ao processar a aprovacao de militancia.'
        )



# @user.post('/card/solicitar', status_code=HTTPStatus.CREATED)
# async def solicitar_cartao(session: Session, current_user: Get_current_user, backgroundTasks: BackgroundTasks):
#     # 1. Verifica se já existe cartão ativo
#     agora = datetime.now(timezone.utc)
#     cartao = await session.scalar(select(CartaoMilitante).where(CartaoMilitante.user_id == current_user.id, CartaoMilitante.data_expiracao > agora))
#     if cartao:
#         raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui um cartão ativo.")

#     # 2. Verifica se já existe uma solicitação pendente
#     solicitacao_existente = await session.scalar(
#         select(SolicitacaoCartao).where(
#             SolicitacaoCartao.user_id == current_user.id, 
#             SolicitacaoCartao.status == StatusSolicitacao.PENDENTE))
#     if solicitacao_existente:
#         raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui uma solicitação em análise.")

#     # 3. Cria a solicitação no banco
#     nova_solicitacao = SolicitacaoCartao(user_id=current_user.id, status=StatusSolicitacao.PENDENTE)
#     session.add(nova_solicitacao)

#     query_admin = select(User).where(User.role_id == 1)  # Supondo que role_id 1 seja para administradores
#     admin = await session.scalar(query_admin)

#     if not admin:
#         logger.error("Nenhum administrador encontrado para notificação de solicitação de cartão.")
#         raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Nenhum administrador disponível para processar a solicitação.")
    

#     query_scope_admin = select(AdminScope).where(AdminScope.user_id == admin.id)
#     scope_admin = await session.scalar(query_scope_admin)

#     if not scope_admin:
#         logger.error("Nenhum escopo de administrador encontrado para o usuário administrador.")
#         raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Escopo do administrador não configurado.")
    
#     if scope_admin.municipio_id and current_user.municipio_id != scope_admin.municipio_id:
#         logger.warning("Administrador não tem permissão para aprovar solicitações de outro município.")
#         raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Administrador não autorizado para este município.")
#     if scope_admin.provincia_id and current_user.provincia_id != scope_admin.provincia_id:
#         logger.warning("Administrador não tem permissão para aprovar solicitações de outra província.")
#         raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="Administrador não autorizado para esta província.")

#     # 4. Cria uma notificação para o administrador
#     notificacao_admin = Notification(
#         user_id=scope_admin.id, # Vinculado ao autor para rastro
#         titulo="Nova Solicitação de Cartão",
#         mensagem=f"O militante {current_user.nome_completo} solicitou a emissão do cartão."
#     )
#     session.add(notificacao_admin)
    
#     await session.commit()
#     backgroundTasks.add_task(enviar_email_solicitacao_cartao_militante, current_user, agora)
#     return {"detail": "Solicitação enviada com sucesso. Aguarde a aprovação do administrador."}


@user.post('/card/solicitar', status_code=HTTPStatus.CREATED)
@limiter.limit("1/day")
async def solicitar_cartao(request: Request, session: Session, current_user: Get_current_user):

    if current_user.cadastrar_militante != 'MILITANTE':
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=f'Usuario {current_user.email} precisar ser militante')
    
    agora = datetime.now(timezone.utc)
    cartao = await session.scalar(
        select(CartaoMilitante).where(
            CartaoMilitante.user_id == current_user.id, 
            CartaoMilitante.activo == True
        )
    )
    if cartao:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui um cartão ativo.")

    solicitacao_existente = await session.scalar(
        select(SolicitacaoCartao).where(
            SolicitacaoCartao.user_id == current_user.id, 
            SolicitacaoCartao.status == StatusSolicitacao.PENDENTE
        )
    )
    if solicitacao_existente:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui uma solicitação em análise.")

    nova_solicitacao = SolicitacaoCartao(user_id=current_user.id, status=StatusSolicitacao.PENDENTE)
    session.add(nova_solicitacao)

    query_admin_regional = (
        select(User)
        .join(AdminScope, AdminScope.user_id == User.id)
        .where(
            User.role_id == admin_id,
            (AdminScope.municipio_id == current_user.municipio_id) | 
            (AdminScope.provincia_id == current_user.provincia_id)
        )
        .limit(1)
    )
    admin_alvo = await session.scalar(query_admin_regional)

    if not admin_alvo:
        logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
        query_admin_geral = select(User).where(User.role_id == admin_id).limit(1)
        admin_alvo = await session.scalar(query_admin_geral)

    if not admin_alvo:
        logger.critical("Falha crítica: Nenhum administrador cadastrado no sistema inteiro.")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail="Nenhum administrador disponível para processar a solicitação no momento."
        )

    notificacao_admin = Notification(
        admin_id=admin_alvo.id,
        user_id = current_user.id,
        titulo="Nova Solicitação de Cartão",
        mensagem=f"O militante {current_user.nome_completo} (Nº {current_user.militante_numero or 'Pendente'}) solicitou a emissão do cartão.",
        destinatario="ADMIN",
        categoria=RoleCategoriaNotificacao.SOLICITACAO_CARTAO
    )

    session.add(notificacao_admin)

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error("Erro ao salvar solicitação e notificação: %s", str(e))
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Erro ao salvar dados no banco.")

    # backgroundTasks.add_task(
    #     enviar_email_solicitacao_cartao_militante, 
    #     admin_alvo.email,
    #     current_user.nome_completo,
    #     current_user.militante_numero or "Pendente de Atribuição",
    #     agora
    # )

    return {"detail": "Solicitação enviada com sucesso. Aguarde a aprovação do administrador."}



# @user.get('/card', status_code=HTTPStatus.OK, response_model=CardBase)
# async def obter_cartao(session: Session, current_user: Get_current_user):
#     """
#     Retorna os detalhes do cartão do militante logado, se houver um cartão ativo.
#     """
#     if current_user.cadastrar_militante != 'MILITANTE':
#         raise HTTPException(
#             status_code=HTTPStatus.FORBIDDEN,
#             detail="É necessário ser militante para visualizar o cartão."
#         )

#     cartao = await session.scalar(
#         select(CartaoMilitante).where(
#             CartaoMilitante.user_id == current_user.id,
#             CartaoMilitante.activo.is_(True)
#         )
#     )
    
#     if not cartao:
#         raise HTTPException(
#             status_code=HTTPStatus.NOT_FOUND,
#             detail="Nenhum cartão ativo encontrado."
#         )

    
#     return cartao


@user.get('/card', status_code=status.HTTP_200_OK, response_model=CardBase)
async def obter_cartao(session: Session, current_user: Get_current_user):
    """
    Retorna os detalhes do cartão do militante logado, se houver um cartão ativo.
    """
    if current_user.cadastrar_militante != 'MILITANTE':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="É necessário ser militante para visualizar o cartão."
        )

    # 1. Correção do MissingGreenlet adicionando selectinload
    cartao = await session.scalar(
        select(CartaoMilitante)
        .where(
            CartaoMilitante.user_id == current_user.id,
            CartaoMilitante.activo.is_(True)
        )
        .options(
            selectinload(CartaoMilitante.municipio),
            selectinload(CartaoMilitante.provincia)
        )
    )
    
    if not cartao:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum cartão ativo encontrado."
        )

    # 2. Correção da validação: Injetar dinamicamente os dados esperados pelo CardBase
    # que pertencem ao utilizador, mas que o Pydantic precisa ler no root do objeto
    cartao.numero_cartao = current_user.militante_numero
    cartao.nome_militante = current_user.nome_completo
    
    return cartao



@user.get('/notificacoes', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes(
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

    # 1. Determina dinamicamente o destinatário com base no tipo de cadastro
    # destinatario_tipo = None
    # if current_user.cadastrar_militante == CadastrarComo.MILITANTE:
    #     destinatario_tipo = "MILITANTE"
    # elif current_user.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
    #     destinatario_tipo = "SIMPATIZANTE"

    # 2. Constrói os filtros base (reutilizáveis e seguros)
    filtros = [Notification.user_id == current_user.id]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    total_query = (
        select(func.count(Notification.id))
        .where(*filtros)
    )
    total = await session.scalar(total_query) or 0
    # 3. Consulta Principal (Ordenação e Paginação aplicadas no fim)
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
    


@user.get('/notificacoes/nao-lidas', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes_nao_lidas(
    session: Session,
    current_user: Get_current_user,
    limit: int = Query(default=10, le=50, description="Número de notificações por página"),
    offset: int = Query(default=0, ge=0,  le=10000, description="Número de registros a pular (offset)")
):
    """
    Retorna a lista de notificações do usuário logado de forma paginada,
    conforme o seu tipo de cadastro (Militante ou Simpatizante).
    """
    logger.info("Usuário %s listando notificações...", current_user.id)

    # 1. Determina dinamicamente o destinatário com base no tipo de cadastro
    # destinatario_tipo = None
    # if current_user.cadastrar_militante == CadastrarComo.MILITANTE:
    #     destinatario_tipo = "MILITANTE"
    # elif current_user.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
    #     destinatario_tipo = "SIMPATIZANTE"

    # 2. Constrói os filtros base (reutilizáveis e seguros)
    filtros = [Notification.user_id == current_user.id]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    # 3. Consulta Principal (Ordenação e Paginação aplicadas no fim)
    query = (
        select(Notification)
        .options(joinedload(Notification.solicitante))
        .where(*filtros, Notification.lido_as.is_(None))
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
            'results': []}
        

    # 4. Consulta do Contador (Usa os mesmos filtros dinâmicos de forma consistente)
    query_nao_lidas = (
        select(func.count(Notification.id))
        .where(*filtros, Notification.lido_as.is_(None))
    )
    total_nao_lidas = await session.scalar(query_nao_lidas) or 0

    return {
        'total': total_nao_lidas, 
        'results': notificacoes}





@user.get('/notificacoes/dashboard', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
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

    # 1. Determina dinamicamente o destinatário com base no tipo de cadastro
    # destinatario_tipo = None
    # if current_user.cadastrar_militante == CadastrarComo.MILITANTE:
    #     destinatario_tipo = "MILITANTE"
    # elif current_user.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
    #     destinatario_tipo = "SIMPATIZANTE"

    # 2. Constrói os filtros base (reutilizáveis e seguros)
    filtros = [Notification.user_id == current_user.id]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    total_query = (
        select(func.count(Notification.id))
        .where(*filtros, Notification.lido_as.is_(None))
    )
    total = await session.scalar(total_query) or 0
    # 3. Consulta Principal (Ordenação e Paginação aplicadas no fim)
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
    



@user.get('/notificacoes/lidas', status_code=HTTPStatus.OK, response_model=NotificationListResponse)
async def listar_notificacoes_lidas(
    session: Session,
    current_user: Get_current_user,
    limit: int = Query(default=10, le=50, description="Número de notificações por página"),
    offset: int = Query(default=0, ge=0, le=10000, description="Número de registros a pular (offset)")
):
    """
    Retorna a lista de notificações do usuário logado de forma paginada,
    conforme o seu tipo de cadastro (Militante ou Simpatizante).
    """
    logger.info("Usuário %s listando notificações...", current_user.id)

    # 1. Determina dinamicamente o destinatário com base no tipo de cadastro
    # destinatario_tipo = None
    # if current_user.cadastrar_militante == CadastrarComo.MILITANTE:
    #     destinatario_tipo = "MILITANTE"
    # elif current_user.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
    #     destinatario_tipo = "SIMPATIZANTE"

    # 2. Constrói os filtros base (reutilizáveis e seguros)
    filtros = [Notification.user_id == current_user.id, Notification.lido_as.is_not(None)]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    # 3. Consulta Principal (Ordenação e Paginação aplicadas no fim)
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
        return {
            'total': 0, 
            'results': []}
        

    # 4. Consulta do Contador (Usa os mesmos filtros dinâmicos de forma consistente)
    query_lidas = (
        select(func.count(Notification.id))
        .where(*filtros, Notification.lido_as.is_not(None))
    )
    total_lidas = await session.scalar(query_lidas) or 0

    return {
        'total': total_lidas, 
        'results': notificacoes}
    


# @user.patch('/notificacoes/{id_notificacao}/ler', status_code=HTTPStatus.OK)
# async def marcar_como_lida(
#     id_notificacao: uuid.UUID,
#     session: Session,
#     current_user: Get_current_user
# ):
#     """
#     Atualiza o campo 'lido_as' de uma notificação específica com a data e hora atual.
#     Garante que um militante não consiga ler ou alterar a notificação de outro.
#     """
#     logger.info("Militante %s tentando ler notificação %s", current_user.id, id_notificacao)

#     # Busca a notificação garantindo que ela pertence ao usuário logado
#     query = select(Notification).where(
#         Notification.id == id_notificacao,
#         Notification.user_id == current_user.id, 
#         Notification.destinatario == 'MILITANTE'
#     )
#     notificacao = await session.scalar(query)

#     if not notificacao:
#         logger.warning("Notificação %s não encontrada para o usuário %s", id_notificacao, current_user.id)
#         raise HTTPException(
#             status_code=HTTPStatus.NOT_FOUND,
#             detail="Notificação não encontrada no seu histórico."
#         )

#     # Se ainda não foi lida, atualiza com o carimbo de data/hora atual
#     if  notificacao.lido_as is None:
#         notificacao.lido_as = datetime.now(timezone.utc)
#         try:
#             await session.commit()
#             await session.refresh(notificacao)
#             logger.info(
#                     "Usuário %s marcou a notificação %s como lida",
#                     current_user.id,
#                     id_notificacao
#                 )
#         except Exception as e:
#             await session.rollback()
            
#             logger.exception("Erro ao marcar notificação como lida: %s", str(e))
#             raise HTTPException(
#                 status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
#                 detail="Erro ao atualizar o status da notificação."
#             )

#     return notificacao



@user.patch(
    '/notificacoes/{id_notificacao}/ler',
    status_code=HTTPStatus.OK,
    response_model=NotificationResponse
)
async def marcar_como_lida(
    response: Response,
    id_notificacao: uuid.UUID,
    session: Session,
    current_user: Get_current_user
):
    """
    Marca uma notificação do militante como lida.
    Garante que o usuário só possa alterar notificações próprias.
    """

    logger.info(
        "Usuário %s tentando marcar notificação %s como lida",
        current_user.id,
        id_notificacao
    )

    # destinatario_tipo = None
    # if current_user.cadastrar_militante == CadastrarComo.MILITANTE:
    #     destinatario_tipo = "MILITANTE"
    # elif current_user.cadastrar_militante == CadastrarComo.SIMPATIZANTE:
    #     destinatario_tipo = "SIMPATIZANTE"

    filtros = [Notification.user_id == current_user.id, Notification.id == id_notificacao]
    # if destinatario_tipo:
    #     filtros.append(Notification.destinatario == destinatario_tipo)

    query = (
            select(Notification)
            .options(joinedload(Notification.solicitante))
            .where(*filtros)
        )
    
    notificacao = await session.scalar(
        query
    )
        # select(Notification)
        # .options(joinedload(Notification.solicitante))
        # .where(
        #     Notification.id == id_notificacao,
        #     Notification.user_id == current_user.id,
        #     Notification.destinatario == "MILITANTE"
        # )

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
            # await session.refresh(notificacao)

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


@user.get('/{user_id}', status_code=HTTPStatus.OK, response_model=ListarUserBase)
async def obter_usuario_por_id(
    user_id: uuid.UUID,
    session: Session,
    current_user: Get_current_user,
    scope: ScopeValid
):
    """
    Retorna os detalhes completos de um usuário específico por ID.
    Administradores regionais só podem visualizar usuários de seu próprio escopo geográfico.
    """
    logger.info("Admin %s solicitou detalhes do usuário %s.", current_user.id, user_id)

    query = (
        select(User)
        .where(User.id == user_id, User.ativo.is_(True))
        .options(selectinload(User.scope),
                 selectinload(User.provincia),
                 selectinload(User.municipio),
                 selectinload(User.role)
        )
    )
    user_target = await session.scalar(query)

    if not user_target:
        logger.warning(f"Usuário {user_id} não foi encontrado ou está inativo.")
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="Usuário não encontrado."
        )

    if scope.municipio_id is not None:
        if user_target.municipio_id != scope.municipio_id:
            logger.warning(f"Admin Municipal {current_user.id} tentou ler usuário {user_id} de outro município.")
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Operação negada. O usuário informado pertence a outra região geográfica."
            )
            
    elif scope.provincia_id is not None:
        if user_target.provincia_id != scope.provincia_id:
            logger.warning(f"Admin Provincial {current_user.id} tentou ler usuário {user_id} de outra província.")
            raise HTTPException(
                status_code=HTTPStatus.FORBIDDEN,
                detail="Operação negada. O usuário informado pertence a outra região geográfica."
            )
    else:
        logger.info(f"Super Admin {current_user.id} visualizando usuário {user_id} com sucesso.")

    return user_target



@user.delete('/delete/', status_code=HTTPStatus.OK)
@limiter.limit("2/minute; 100/day")
async def delete_user(
    request: Request,
    response: Response,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    codigo: DeleteUser,
) -> Dict[str, str]:
    """
    Executa o Soft Delete de forma dinâmica e segura.
    Descobre os privilégios buscando o nome da Role no banco, eliminando IDs fixos.
    """
    user_to_delete = None
    if codigo.valid != 'ELIMINAR':
        logger.warning("Erro, na confirmacao de delete da conta do usuario")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Erro, na confirmacao de delete da conta do usuario")




    logger.info("Usuário %s executou auto-exclusão da conta.", current_user.id)
    user_to_delete = current_user
       
    user_to_delete.deletado_em = datetime.now(timezone.utc)
    user_to_delete.ativo = False

    try:
        session.add(user_to_delete)
        await caches.incr("v1:usuarios:lista:versao")
        await session.commit()

        
        logger.info("Usuário %s desativado com sucesso. Versão do cache incrementada.", current_user.email)

    except Exception as e:
        await session.rollback()
        logger.error("Erro crítico durante commit de exclusão: do usuario %s,  %s ", current_user.email, str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar a desativação da conta."
        )
    # await apagar_foto_perfil_cloudinary(str(user_to_delete.id))

    refresh_token = request.cookies.get(
            # "__Host-refresh_token"
            "refresh_token"
        )
    
    try:
    
        if refresh_token:

            try:
    
                payload = decode(
                    refresh_token,
                    settings.SECRET_KEY,
                    algorithms=[settings.ALGORITHM],
                )
    
                token_jti = payload.get("jti")
    
            except PyJWTError:
    
                token_jti = None
    
            if token_jti:
    
                agora = datetime.now(timezone.utc)
    
                result = await session.execute(
                    select(UserRefreshToken)
                    .where(
                        UserRefreshToken.token_jti == token_jti,
                        UserRefreshToken.revogado.is_(False),
                    )
                    .with_for_update()
                )
    
                db_token = (
                    result.scalar_one_or_none()
                )
    
                if db_token:
    
                    db_token.revogado = True
                    db_token.revogado_em = agora
    
                    await session.commit()
    
            # =====================================================
            # Apagar cookies
            # =====================================================
    
        response.delete_cookie(
             # key="__Host-access_token",
            key="access_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )
    
        response.delete_cookie(
                # key="__Host-refresh_token",
            key="refresh_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )
    
        response.headers["Cache-Control"] = "no-store"
    
        return {"msg": "Usuário deletado com sucesso!"}
    
    except Exception:
    
        await session.rollback()
    
        logger.exception(
            "Erro durante logout."
        )
    
            # Mesmo em caso de erro interno,
            # remove as credenciais do navegador.
    
        response.delete_cookie(
            # key="__Host-access_token",
            key="access_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
            )
    
        response.delete_cookie(
            # key="__Host-refresh_token",
            key="refresh_token",
            path="/",
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES
        )
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    
        return {'msg': 'Usuário deletado com sucesso!'}







# @user.delete('/delete/{user_id}', status_code=HTTPStatus.OK)
# @limiter.limit("2/minute; 100/day")
# async def delete_user(
#     request: Request,
#     response: Response,
#     user_id: uuid.UUID,
#     session: Session,
#     caches: Redis,
#     current_user: Get_current_user,
#     scope: ScopeValid
# ) -> Dict[str, str]:
#     """
#     Executa o Soft Delete de forma dinâmica e segura.
#     Descobre os privilégios buscando o nome da Role no banco, eliminando IDs fixos.
#     """
#     user_to_delete = None
#     if current_user.id == user_id:
#         logger.info("Usuário %s executou auto-exclusão da conta.", current_user.id)
#         user_to_delete = current_user

#     else:

#         query = (
#             select(User)
#             .where(User.id == user_id, User.ativo == True)
#             .options(selectinload(User.scope))
#             .with_for_update() 
#         )
#         user_to_delete = await session.scalar(query)

#         if not user_to_delete:
#             logger.warning("Exclusão falhou: ID %s inexistente ou já inativo.", user_id)
#             raise HTTPException(
#                 status_code=HTTPStatus.NOT_FOUND, 
#                 detail="Usuário não encontrado."
#             )

#         target_scope = user_to_delete.scope

#         if target_scope:

#             # if scope.municipio_id is not None and target_scope.municipio_id is None:
#             #     logger.warning("Admin Municipal %s tentou deletar Admin de nível superior %s.", current_user.id, user_to_delete.id)
#             #     raise HTTPException(
#             #         status_code=HTTPStatus.FORBIDDEN,
#             #         detail="Permissão negada. Você não pode deletar um administrador de nível superior."
#             #     )

#             if scope.provincia_id is not None and scope.municipio_id is None:
#                 if target_scope.provincia_id is None and target_scope.municipio_id is None:
#                     logger.warning("Admin Provincial %s tentou deletar o Super Admin %s.",current_user.id, user_to_delete.id)
#                     raise HTTPException(
#                         status_code=HTTPStatus.FORBIDDEN,
#                         detail="Permissão negada. Você não pode deletar um Super Administrador."
#                     )

#         # if scope.municipio_id is not None:
#         #     if user_to_delete.municipio_id != scope.municipio_id:
#         #         logger.warning("Admin Municipal %s tentou invadir escopo do município %s.", current_user.id, user_to_delete.provincia_id)
#         #         raise HTTPException(
#         #             status_code=HTTPStatus.FORBIDDEN,
#         #             detail="Operação negada. O usuário informado pertence a outra região geográfica."
#         #         )
                
#         if scope.provincia_id is not None:
#             if user_to_delete.provincia_id != scope.provincia_id:
#                 logger.warning("Admin Provincial %s tentou invadir escopo da província %s.", current_user.id, user_to_delete.provincia_id)
#                 raise HTTPException(
#                     status_code=HTTPStatus.FORBIDDEN,
#                     detail="Operação negada. O usuário informado pertence a outra região geográfica."
#                 )
#         else:
#             logger.info("Super Admin %s autorizado para exclusão global.", current_user.id)

#     user_to_delete.deletado_em = datetime.now(timezone.utc)
#     user_to_delete.ativo = False

#     try:
#         session.add(user_to_delete)
#         await caches.incr("v1:usuarios:lista:versao")
#         await session.commit()

        
#         logger.info("Usuário %s desativado com sucesso. Versão do cache incrementada.", user_id)

#     except Exception as e:
#         await session.rollback()
#         logger.error("Erro crítico durante commit de exclusão: do usuario %s,  %s ", user_id, str(e))
#         raise HTTPException(
#             status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
#             detail="Erro interno ao processar a desativação da conta."
#         )
#     # await apagar_foto_perfil_cloudinary(str(user_to_delete.id))

#     refresh_token = request.cookies.get(
#             # "__Host-refresh_token"
#             "refresh_token"
#         )
    
#     try:
    
#         if refresh_token:

#             try:
    
#                 payload = decode(
#                     refresh_token,
#                     settings.SECRET_KEY,
#                     algorithms=[settings.ALGORITHM],
#                 )
    
#                 token_jti = payload.get("jti")
    
#             except PyJWTError:
    
#                 token_jti = None
    
#             if token_jti:
    
#                 agora = datetime.now(timezone.utc)
    
#                 result = await session.execute(
#                     select(UserRefreshToken)
#                     .where(
#                         UserRefreshToken.token_jti == token_jti,
#                         UserRefreshToken.revogado.is_(False),
#                     )
#                     .with_for_update()
#                 )
    
#                 db_token = (
#                     result.scalar_one_or_none()
#                 )
    
#                 if db_token:
    
#                     db_token.revogado = True
#                     db_token.revogado_em = agora
    
#                     await session.commit()
    
#             # =====================================================
#             # Apagar cookies
#             # =====================================================
    
#         response.delete_cookie(
#              # key="__Host-access_token",
#             key="access_token",
#             path="/",
#             httponly=True,
#             samesite=settings.SAMESITE_COOKIE,
#             secure=settings.SECURE_COOKIES
#         )
    
#         response.delete_cookie(
#                 # key="__Host-refresh_token",
#             key="refresh_token",
#             path="/",
#             httponly=True,
#             samesite=settings.SAMESITE_COOKIE,
#             secure=settings.SECURE_COOKIES
#         )
    
#         response.headers["Cache-Control"] = "no-store"
    
#         return 
    
#     except Exception:
    
#         await session.rollback()
    
#         logger.exception(
#             "Erro durante logout."
#         )
    
#             # Mesmo em caso de erro interno,
#             # remove as credenciais do navegador.
    
#         response.delete_cookie(
#             # key="__Host-access_token",
#             key="access_token",
#             path="/",
#             httponly=True,
#             samesite=settings.SAMESITE_COOKIE,
#             secure=settings.SECURE_COOKIES
#             )
    
#         response.delete_cookie(
#             # key="__Host-refresh_token",
#             key="refresh_token",
#             path="/",
#             httponly=True,
#             samesite=settings.SAMESITE_COOKIE,
#             secure=settings.SECURE_COOKIES
#         )
#         response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    
#         return {'msg': 'Usuário deletado com sucesso!'}




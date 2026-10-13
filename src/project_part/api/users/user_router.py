import json
import logging
import io
import base64
import time
import hmac
from jwt import PyJWTError, decode
from user_agents import parse
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError
from project_part.core import pending_registration
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
from decimal import Decimal
import secrets
import uuid
from datetime import datetime, timezone, date

from pydantic import TypeAdapter, model_validator, ValidationError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import (
    func,
    or_,
    select,
    case,
    extract,
    desc,
    asc,
    update,
)
import pyotp
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, joinedload

from fastapi import Response
from project_part.core.revocar_token_apos_alterar_passWord import revogar_todas_sessoes, emitir_access_token
from project_part.services.two_factor_challenge import (
    criar_challenge_2fa,
    get_client_ip,
    obter_challenge_valida,
    registrar_tentativa,
    consumir_challenge,
    CHALLENGE_TTL,
)
from project_part.core.revocar_token_apos_alterar_passWord import (
    emitir_access_token,
)
from project_part.core.secury import (
    hash_password,
    verify_password,
    Get_current_user,
    garante_escopo_territorial,
    create_token_recuperar_senha,
    create_token,
    decrypt_totp_secret,
    gerar_e_registar_refresh_token
    )
from project_part.utils.eliminar_usuario import (
    limpar_cookies_auth,
    ContaSnapshot,
    senha_valida,
    registar_falha_credencial,
    verificar_segundo_fator,
    registar_falha_credencial,
    ids_admins_a_notificar,
    desativar_conta,
    MSG_ERRO_INTERNO,
    MSG_JA_DESATIVADA,
    MSG_BLOQUEADO,
    MSG_SENHA_INCORRETA,
    MSG_2FA_INVALIDO,
)
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
# from project_part.utils.preparar_quota import preparar_aviso_primeira_quota
from project_part.api.auth.util import set_auth_cookies
from project_part.services.claudflare_turnfile import verificar_turnstile
from project_part.tasks.email_tasks import (
    enviar_email_confirmacao_cadastro,
    enviar_email_cadastro_realizado_sucesso,
    enviar_email_ativar_quota,
    enviar_email_bloqueio,
    enviar_email_conta_desativada,
)
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
    Doacao,
    MetodoPagamentoEnum,
    DonationStatusEnum,
    QuotaStatusEnum,
    PagamentoQuota,
    BackupCode,

)
from project_part.utils.crypto import HASH_SEM
from project_part.utils.security_helpers import (
    mascarar_email,
    duracao_bloqueio_min,
    erro_interno,
    resposta_credenciais_invalidas,
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
    DoacaoList,
    Delete2FARequest,
    DoacaoResponse,
    ContribuicoesIndividuoResponse,
    ContribuicaoItem,
    TipoContribuicao,
    UltimoPagamentoQuotaResponse,
    UpdateEmailRecuperacao,

)

logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]
Redis = Annotated[AsyncRedis, Depends(get_redis)]
Paginacao = Annotated[LimitUser, Depends()]
Claudflare_turnfile = Annotated[bool, Depends(verificar_turnstile)]
ScopeValid =  Annotated[AdminScope, Depends(garante_escopo_territorial)]

user = APIRouter(prefix='/user', tags=['User'])



FILE_READ_TIMEOUT_SECONDS = 30.0
MAX_TENTATIVAS_CODIGO = 5
TTL_CADASTRO_S = 15 * 60


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
    

@user.post('/create', status_code=HTTPStatus.ACCEPTED)
@limiter.limit("3/minute; 30/day")
async def create_user(
    request: Request,
    caches: Redis,
    session: Session,
    backgroundTasks: BackgroundTasks,
    _captcha: Claudflare_turnfile,
    aceitou_termos: bool,
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
    Inicia o cadastro: valida dados, gera código de verificação e envia e-mail.
    O usuário só é criado após confirmação do e-mail.
    """
    # --- 1. Validação do arquivo ---
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
            chunk = await foto_perfil.read(1024 * 1024)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > settings.FILE_SIZE_LIMIT:
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
            aceitou_termos = aceitou_termos,
            genero=genero,
            estado_civil=estado_civil,
            nome_provincia=nome_provincia,
            foi_militante=foi_militante,
            cadastrar_militante=cadastrar_militante,
            nome_municipio=nome_municipio,
            militante_numero=num_militante_final,
            codigo_verificacao_email=None  # ainda não precisamos
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

    id_role_alvo = settings.ROLE_MILITANTE_ID if cadastrar_militante == CadastrarComo.MILITANTE else settings.ROLE_SIMPATIZANTE_ID
    role_banco = await session.scalar(select(Role).where(Role.id == id_role_alvo))
    if not role_banco:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail="A permissão de acesso especificada não está configurada no sistema."
        )

    # --- 5. Geração do código, hash da senha e persistência cifrada ---
    secret_number = secrets.randbelow(900000) + 100000  # 6 dígitos
    async with HASH_SEM:
        password_hash = await run_in_threadpool(hash_password, dados_validados.password)

    dados_temporarios = {
        "nome_completo": dados_validados.nome_completo,
        "email": dados_validados.email,
        "aceitou_termos": dados_validados.aceitou_termos,
        "password_hash": password_hash,   # [SEC-001] era "password": dados_validados.password
        "data_nascimento": dados_validados.data_nascimento.isoformat(),
        "nif": dados_validados.nif,
        "telefone": dados_validados.telefone,
        "genero": dados_validados.genero.value if hasattr(dados_validados.genero, "value") else dados_validados.genero,
        "foi_militante": dados_validados.foi_militante,
        "cadastrar_militante": dados_validados.cadastrar_militante.value if hasattr(dados_validados.cadastrar_militante, "value") else dados_validados.cadastrar_militante,
        "estado_civil": dados_validados.estado_civil.value if hasattr(dados_validados.estado_civil, "value") else dados_validados.estado_civil,
        "id_provincia": str(provincia_banco.id),
        "id_municipio": str(municipio_banco.id),
        "id_role": str(role_banco.id),
        "militante_numero": num_militante_final,
        # [SEC-001] REMOVIDOS: "foto_perfil_b64" (a foto vai como bytes cifrados, em chave própria)
        # e "codigo_verificacao" (fica só um HMAC do código, dentro do payload cifrado)
    }

    try:
        # [SEC-001] Cifra tudo, guarda com TTL de 15 min e devolve a referência opaca.
        # Gravar ANTES de enviar o e-mail: antes, se o Redis falhasse, o utilizador
        # recebia um código para um registo que não existia.
        ref = await pending_registration.guardar(
            caches, dados_temporarios, conteudo_bytes, str(secret_number)
        )
    except Exception:
        # [SEC-001] Não registar o payload nem a exceção completa (pode conter PII)
        # logger.error("Falha ao guardar registo pendente no Redis.")
        logger.exception("Falha ao guardar registo pendente no Redis.")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Falha ao iniciar o registo."
        )

    try:
        
        await enviar_email_confirmacao_cadastro(
            backgroundTasks,
            email_destino=dados_validados.email,   # [SEC-001] o validado, igual ao guardado
            secret_number=secret_number,
            nome_completo=dados_validados.nome_completo,
        )
    except Exception as e:
        # [SEC-001] Se o e-mail não saiu, não deixar um registo pendente órfão
        await pending_registration.descartar(caches, ref)
        logger.error("Falha ao injetar tarefa de e-mail para %s: %s",
                     mascarar_email(dados_validados.email), str(e))
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Falha ao processar e-mail de confirmação."
        )

    return {
        "status": "success",
        "message": "Código de ativação enviado para o e-mail. Confirme em até 15 minutos.",
        "registration_ref": ref,
    }





@user.post("/confirm-email", status_code=HTTPStatus.CREATED)
@limiter.limit("3/minute; 10/day")
async def confirmar_email_cadastro(
    request: Request,
    response: Response,
    dados: ConfirmarEmailSchema,   # [SEC-001] agora: registration_ref + codigo (sem email)
    caches: Redis,
    session: Session,
    _captcha: Claudflare_turnfile,
    backgroundTasks: BackgroundTasks,
):
    agora = datetime.now(timezone.utc)
    versao_politica_apd = settings.VERSAO_POLITICA_APD

    # --- 1. Recuperar, validar o código e consumir (uso único) ---
    # [SEC-001] consumir() valida o código por HMAC (compare_digest), limita as
    # tentativas (5 por registo) e apaga o registo ao devolver os dados.
    # Mensagem única: não distingue "expirado", "inexistente" e "código errado".
    resultado = await pending_registration.consumir(
        caches, dados.registration_ref, dados.codigo
    )
    if resultado is None:
        logger.warning(
            "Confirmação de cadastro recusada (inválida, expirada ou tentativas esgotadas)."
        )
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Código inválido ou expirado. Se necessário, registe-se novamente.",
        )
    usuario_data, conteudo_bytes = resultado
    email_log = mascarar_email(usuario_data["email"])

    # [SEC-001] O hash já vem feito do /create: não voltar a fazer hash.
    password_hash = usuario_data["password_hash"]

    # --- 2. Re-checagem de unicidade (proteção contra race condition) ---
    # [FIX] era dados.email, que já não existe no schema
    usuario_duplicado = await session.scalar(
        select(User.id).where(
            (User.email == usuario_data["email"]) | (User.nif == usuario_data["nif"])
        )
    )
    if usuario_duplicado:
        # O registo já foi consumido: não há nada a apagar no Redis
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Estes dados de e-mail ou NIF já foram registados por outra conta ativa.",
        )

    # --- 3. Cria o utilizador (ainda sem commit) ---
    novo_usuario = User(
        nome_completo=usuario_data["nome_completo"],
        email=usuario_data["email"],
        password_hash=password_hash,
        consentimento_lpd=usuario_data["aceitou_termos"],
        concedido_em=agora,
        versao_politica_apd=versao_politica_apd,
        data_nascimento=date.fromisoformat(usuario_data["data_nascimento"]),
        nif=usuario_data["nif"],
        militante_numero=usuario_data["militante_numero"],
        telefone=usuario_data["telefone"],
        foi_militante=usuario_data["foi_militante"],
        cadastrar_militante=usuario_data["cadastrar_militante"],
        provincia_id=usuario_data["id_provincia"],
        municipio_id=usuario_data["id_municipio"],
        role_id=usuario_data["id_role"],
        genero=usuario_data["genero"],
        estado_civil=usuario_data["estado_civil"],
        image_url=None,
    )
    novo_usuario.criado_em = datetime.now(timezone.utc)

    try:
        session.add(novo_usuario)
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Erro de integridade relacional ao registar documentos.",
        )
    except Exception as e:
        await session.rollback()
        logger.critical("Erro catastrófico ao reservar usuário: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno de processamento no servidor.",
        )

    # --- 4. Upload da foto (só agora) ---
    # [SEC-001] conteudo_bytes já vem decifrado de consumir(); sem base64
    try:
        url_secure = await asyncio.wait_for(
            upload_imagem_geral(
                file_bytes=conteudo_bytes,
                identificador=str(novo_usuario.id),
                pasta_alvo=PASTA_ALVO,
                prefixo_arquivo=PREFIXO_ARQUIVO,
            ),
            timeout=30,
        )
    except Exception as e:
        await session.rollback()
        logger.error("Falha ao subir imagem para o Cloudinary na confirmação: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Falha ao salvar imagem de perfil no serviço de nuvem.",
        )

    novo_usuario.image_url = url_secure

    # --- 5. Commit final ---
    # [FIX] a compensação usa as mesmas constantes do upload (antes: literal "perfis_usuarios/avatar_")
    caminho_upload = f"{PASTA_ALVO}/{PREFIXO_ARQUIVO}_{novo_usuario.id}"
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await compensar_upload_orfao(caminho_upload)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Erro de integridade relacional ao efetivar o registo.",
        )
    except Exception as e:
        await session.rollback()
        await compensar_upload_orfao(caminho_upload)
        logger.critical("Erro catastrófico ao commitar usuário após upload: %s", e)
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno de processamento no servidor.",
        )

    # --- 6. Invalidação de cache ---
    # [FIX] REMOVIDO: caches.delete(chave_redis). A variável deixou de existir e o
    # registo já foi apagado em consumir(). Se ficasse, dava NameError e o incr abaixo
    # nunca correria (o try/except engolia o erro).
    try:
        await caches.incr("v1:usuarios:lista:versao")
    except Exception as cache_err:
        logger.error(
            "Falha não-bloqueante ao atualizar dados do Redis após sucesso: %s", cache_err
        )

    # --- 7. Notificação de boas-vindas ---
    if novo_usuario.cadastrar_militante == CadastrarComo.MILITANTE:
        destinatario_tipo = "MILITANTE"
        tipo = "Militante"
        tipo_pagamento = "o pagamento da sua quota inicial"
    else:
        destinatario_tipo = "SIMPATIZANTE"
        tipo = "Simpatizante"
        tipo_pagamento = "a tua primeira doação"

    notification = Notification(
        user_id=novo_usuario.id,
        titulo="Bem-vindo à UNITA PGM",
        mensagem=(
            f"Olá {tipo} {novo_usuario.nome_completo}, seja bem-vindo à UNITA PGM! "
            f"O seu cadastro foi realizado com sucesso. "
            f"Aceda à secção Financeira para efetuar {tipo_pagamento}."
        ),
        categoria=RoleCategoriaNotificacao.BEM_VINDO,
        criado_as=datetime.now(timezone.utc),
        destinatario=destinatario_tipo,
    )
    try:
        session.add(notification)
        await session.flush()  # garante que o ID da notificação é gerado
        avisar_quota = novo_usuario.cadastrar_militante == CadastrarComo.MILITANTE

        nome, email = novo_usuario.nome_completo, novo_usuario.email
        await session.commit()

        if avisar_quota:
            await enviar_email_ativar_quota(
                backgroundTasks,
                nome_completo=nome,
                email_destinatario=email,
            )
    except Exception as e:
        # [FIX] rollback para a sessão não ficar num estado inválido para o passo seguinte
        await session.rollback()
        logger.error(
            "Falha ao criar notificação de boas-vindas para o usuário %s: %s",
            novo_usuario.id, str(e),
        )

    # --- 8. E-mail de sucesso ---
    try:
        await enviar_email_cadastro_realizado_sucesso(
            backgroundTasks,
            email_destino=novo_usuario.email,
            nome_completo=novo_usuario.nome_completo,
        )
    except Exception as e:
        # [FIX] e-mail mascarado (antes: completo, dado pessoal no log)
        logger.error(
            "Falha ao enviar e-mail de sucesso para %s: %s", email_log, str(e)
        )

    # --- 9. Autenticação ---
    token_gerado = emitir_access_token(
        novo_usuario.id, novo_usuario.password_alterado_em
    )

    ip_address = get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    try:
        refresh_gerado = await gerar_e_registar_refresh_token(
            session=session,
            user_id=novo_usuario.id,
            ip=ip_address,
            user_agent=user_agent,
        )
        await session.commit()  # garante que o refresh token é persistido
        set_auth_cookies(
            response=response,
            access_token=token_gerado,
            refresh_token=refresh_gerado,
        )
        response.headers["Cache-Control"] = "no-store"
    except Exception as e:
        await session.rollback()
        logger.error(
            "Falha ao gerar e registrar token de refresh para o usuário %s: %s",
            novo_usuario.id, str(e),
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno de processamento no servidor.",
        )

    # [FIX] e-mail mascarado no log (antes: novo_usuario.email completo)
    logger.info("Usuário %s confirmado e logado com sucesso.", email_log)

    return {
        "status": "success",
        "message": "E-mail confirmado e utilizador autenticado com sucesso.",
    }


@user.patch('/perfil/password', status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("2/minute; 7/day")
async def atualizar_perfil_password(
    request: Request,
    response: Response,
    schemas: UpgradePassWord,
    session: Session,
    _captcha: Claudflare_turnfile,
    current_user: Get_current_user
):
    """
        Altera de forma segura a senha do usuário autenticado.
        Valida a credencial atual, atualiza o hash da senha e REVOGA todas as
        sessões existentes (refresh tokens + access tokens antigos).
        O dispositivo que fez a alteração recebe uma sessão nova; todos os outros
        ficam deslogados.
    """

    user_id = current_user.id
    user_email = current_user.email
    
    logger.info(
        'Iniciando processo de alteração de senha para o usuário: %s',
        user_email
    )

    async with HASH_SEM:
        if not await run_in_threadpool(
                verify_password,
                schemas.senha_atual,
                current_user.password_hash
            ):
            logger.warning(
                'Falha na alteração de senha: senha atual incorreta para o usuário ID: %s',
                user_id
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='A senha atual inserida está incorreta.'
            )

        agora = datetime.now(timezone.utc)
        # ultima_alteracao = 60 * 60 * 24 * 30

        # if current_user.password_alterado_em is not None:
        #     if (
        #         agora.timestamp()
        #         - current_user.password_alterado_em.timestamp()
        #         < ultima_alteracao
        #     ):
        #         logger.warning(
        #             'Tentativa de alteração de senha muito frequente para o usuário ID: %s',
        #             current_user.id
        #         )
        #         raise HTTPException(
        #             status_code=HTTPStatus.TOO_MANY_REQUESTS,
        #             detail='A senha só pode ser alterada uma vez a cada 30 dias.'
        #         )

        crypt_password = await run_in_threadpool(
            hash_password,
           schemas.nova_senha
        )

    current_user.password_hash = crypt_password
    current_user.atualizado_em = agora
    current_user.password_alterado_em = agora

    try:
        session.add(current_user)

        revogados = await revogar_todas_sessoes(session, user_id, agora)
        await session.commit()

        logger.info(
                    'Senha do usuário %s atualizada com sucesso. Sessões revogadas: %d',
                    user_email,
                    revogados
                )

    except IntegrityError as e:
        await session.rollback()

        logger.error(
            'Erro de integridade ao tentar atualizar senha no banco: %s',
            str(e.orig)
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR   ,
            detail='Erro interno de consistência ao processar a requisição.'
        )

    except Exception as e:
        await session.rollback()

        logger.error(
            'Erro desconhecido na alteração da senha do usuário %s: %s',
            user_email,
            str(e)
        )

        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Não foi possível processar a alteração da senha no momento.'
        )

    
    try:
        novo_access = emitir_access_token(user_id, agora)
        novo_refresh = await gerar_e_registar_refresh_token(
            session=session,
            user_id=user_id,
            ip=get_client_ip(request),
            user_agent=request.headers.get('user-agent'),
        )
        await session.commit()
        set_auth_cookies(
            response=response,
            access_token=novo_access,
            refresh_token=novo_refresh,
        )
        response.headers['Cache-Control'] = 'no-store'
    except Exception as e:
        await session.rollback()
        logger.warning(
            'Senha alterada, mas não foi possível reemitir a sessão do dispositivo actual (user %s): %s',
            user_id,
            str(e)
        )


@user.patch('/email-recuperacao', status_code=HTTPStatus.OK)
@limiter.limit("3/minute; 10/day")
async def atualizar_email_recuperacao(
    request: Request,
    schemas: UpdateEmailRecuperacao,
    session: Session,
    _captcha: Claudflare_turnfile,
    current_user: Get_current_user
):
    """
        Atualiza o e-mail de recuperação do usuário autenticado.
        Valida o formato do e-mail, atualiza o campo na base de dados e envia
        um e-mail de confirmação para o novo endereço.
    """

    # user_id = current_user.id
    user_email = current_user.email

    logger.info(
        'Iniciando processo de atualização de e-mail de recuperação para o usuário: %s',
        user_email
    )


    current_user.email_recuperacao = schemas.novo_email
    current_user.atualizado_em = datetime.now(timezone.utc)

    try:
        session.add(current_user)
        await session.commit()

        # Enviar e-mail de confirmação (assíncrono)
        # backgroundTasks.add_task(enviar_email_confirmacao_recuperacao_async, schemas.novo_email, current_user.nome_completo)

        logger.info(
            'E-mail de recuperação do usuário %s atualizado com sucesso para %s',
            user_email,
            schemas.novo_email
        )

        return {'msg': 'E-mail de recuperação atualizado com sucesso! Confirme no seu novo endereço.'}

    except IntegrityError as e:
        await session.rollback()
        logger.error(
            'Erro de integridade ao tentar atualizar e-mail de recuperação no banco: %s',
            str(e.orig)
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='O e-mail informado já está sendo utilizado por outro usuário.'
        )
    except Exception as e:
        await session.rollback()
        logger.error(
            'Erro desconhecido na atualização do e-mail de recuperação do usuário %s: %s',
            user_email,
            str(e)
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Não foi possível processar a atualização do e-mail de recuperação no momento.'
        )
    


@user.put('/perfil/upgrade', status_code=HTTPStatus.OK)
@limiter.limit("2/minute; 5/day")
async def perfil(
    request: Request,
    _captcha: Claudflare_turnfile,
    schemas: UpgradeUser,
    caches: Redis,
    session: Session,
    current_user: Get_current_user
    ):

    """
        Atualiza os dados do perfil do usuário autenticado. 
    """


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
    email_log = mascarar_email(current_user.email)
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

    logger.info('Atualizar os dados do usuario %s', email_log)

    # Atualiza os dados do usuário

    if schemas.nome_completo != current_user.nome_completo:
        cartao_ativo_stmt = select(func.count()).select_from(CartaoMilitante).where(
            CartaoMilitante.user_id == current_user.id,
            CartaoMilitante.activo == True
        )
        tem_cartao_ativo = await session.scalar(cartao_ativo_stmt) or 0

        if tem_cartao_ativo > 0:
            logger.warning('Usuário %s tentou alterar o nome completo, mas possui cartão ativo.', email_log)
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail='Não é possível alterar o nome completo porque possui um cartão de militante ativo. Contacte a administração.'
            )
        
        # Se não tiver cartão ativo, permite a alteração do nome
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
@limiter.limit("10/minute")
async def obter_meu_perfil(
    request: Request,
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
@limiter.limit("3/minute; 10/day")
async def atualizar_foto_perfil(
    request: Request,
    session: Session,
    _captcha: Claudflare_turnfile,
    current_user: Get_current_user,
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(..., description="Selecione uma imagem JPG ou JPEG (max 5MB)"),
):
    """ 
    Atualiza a foto de perfil do usuário.
    - Valida o arquivo enviado (extensão, tamanho, conteúdo real).
    - Sanitiza a imagem removendo EXIF e reconstrói o JPEG.
    """
    logger.info("Usuário %s iniciou o upload de nova foto de perfil.", current_user.id)

    if not arquivo.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum arquivo enviado.")

    # 1. Correção da Query (Valida Impedimentos: Solicitação Pendente OU Cartão já Ativo)
    # Nota: Ajuste 'user_id' / 'id_user' conforme o mapeamento real do seu modelo
    solicitacao_impedimento = await session.scalar(
        select(SolicitacaoCartao).where(
            SolicitacaoCartao.user_id == current_user.id,
            SolicitacaoCartao.status.in_([StatusSolicitacao.PENDENTE, StatusSolicitacao.APROVADO])
        ).limit(1)
    )

    if solicitacao_impedimento:
        logger.warning("Usuário %s tentou alterar a foto de perfil com processo de cartão em andamento ou ativo.", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Não é permitido alterar a foto de perfil enquanto houver um cartão ativo ou solicitação em análise."
        )

    # 2. Correção Lógica de Validação de Extensão (Mudança de 'and' para 'or')
    sufixo = Path(arquivo.filename).suffix.lower()
    if sufixo not in ALLOWED_EXTENSIONS or arquivo.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas imagens JPG ou JPEG são permitidas."
        )

    # 3. Leitura com limite estrito de tamanho
    async def _ler_arquivo_com_limite() -> bytes:
        buffer = bytearray()
        while True:
            chunk = await arquivo.read(64 * 1024)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > settings.FILE_SIZE_LIMIT:
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

    # 4. Validação de Magic Bytes
    kind = filetype.guess(conteudo_bruto)
    if kind is None or kind.mime not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O conteúdo real não é um JPEG válido.")

    # 5. Processamento de imagem em Thread Pool
    try:
        conteudo_sanitizado = await asyncio.to_thread(_higienizar_e_reprocessar_jpeg, conteudo_bruto)
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Imagem corrompida ou inválida.")
    except Image.DecompressionBombError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resolução abusiva detectada.")

    # 6. Geração dos IDs
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

    # Captura o identificador antigo para limpeza
    foto_antiga_public_id = getattr(current_user, "image_public_id", None)
    if not foto_antiga_public_id and current_user.image_url:
        foto_antiga_public_id = _extrair_public_id_da_url(current_user.image_url)

    # 7. Persistência Atómica no Banco de Dados
    try:
        current_user.image_url = url_secure_cloudinary
        if hasattr(current_user, "image_public_id"):
            current_user.image_public_id = novo_public_id
            
        session.add(current_user)
        await session.commit()
    except SQLAlchemyError as e:
        await session.rollback()
        logger.critical("Erro no DB (user_id=%s). Iniciando Saga de compensação na nuvem.", current_user.id)
        
        # SAGA REVERSÃO: Remove a nova imagem se falhar o Commit
        background_tasks.add_task(deletar_imagem_cloudinary_por_public_id, novo_public_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erro ao persistir dados.")

    # 8. Limpeza Pós-Sucesso
    if foto_antiga_public_id:
        background_tasks.add_task(deletar_imagem_cloudinary_por_public_id, foto_antiga_public_id)

    return {
        "msg": "Foto de perfil substituída com sucesso!",
        "foto_url": url_secure_cloudinary
    }


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
        logger.error(f'Acesso negado: Usuário {current_user.id} tentou listar usuários de um município específico ({scope.municipio_id}) sem permissão.')
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Acesso negado: não é permitido listar usuários de um município específico.'
        )
        # logger.info(f'Filtrando usuários do município: {scope.municipio_id}')
        # query = query.where(User.municipio_id == scope.municipio_id)
        # count_query = count_query.where(User.municipio_id == scope.municipio_id)
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
@limiter.limit("3/minute")
async def solicitar_militancia(
    request: Request,
    session: Session,
    current_user: Get_current_user
    ):
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
    current_user.role_id = settings.ROLE_MILITANTE_ID
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


@user.post('/card/solicitar', status_code=HTTPStatus.CREATED)
@limiter.limit("2/minute, 10/day")
async def solicitar_cartao(
    request: Request, 
    session: Session,
    current_user: Get_current_user
):

    # 1. Correção do Status Code (403 para falta de permissão)
    if current_user.cadastrar_militante != 'MILITANTE':
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, 
            detail=f'Usuário {current_user.email} precisa ser militante para solicitar um cartão.'
        )
    
    agora = datetime.now(timezone.utc)
    
    # Verificar cartão ativo existente
    cartao = await session.scalar(
        select(CartaoMilitante).where(
            CartaoMilitante.user_id == current_user.id, 
            CartaoMilitante.activo == True
        )
    )
    if cartao:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Você já possui um cartão ativo.")


    solicitacao_impedimento = await session.scalar(
        select(SolicitacaoCartao).where(
            SolicitacaoCartao.user_id == current_user.id,
            SolicitacaoCartao.status.in_([StatusSolicitacao.PENDENTE, StatusSolicitacao.APROVADO])
        ).limit(1)
    )
    
    if solicitacao_impedimento:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, 
            detail="Você já possui uma solicitação em análise ou já aprovada."
        )

    nova_solicitacao = SolicitacaoCartao(user_id=current_user.id, status=StatusSolicitacao.PENDENTE)
    session.add(nova_solicitacao)

    # Buscar administrador regional
    query_admin_regional = (
        select(User)
        .join(AdminScope, AdminScope.user_id == User.id)
        .where(
            User.role_id == settings.ADMIN_ROLE_ID,
            (AdminScope.municipio_id == current_user.municipio_id) | 
            (AdminScope.provincia_id == current_user.provincia_id)
        )
        .limit(1)
    )
    admin_alvo = await session.scalar(query_admin_regional)

    if not admin_alvo:
        logger.warning("Nenhum admin regional específico encontrado. Buscando Admin Geral...")
        query_admin_geral = select(User).where(User.role_id == settings.ADMIN_ROLE_ID).limit(1)
        admin_alvo = await session.scalar(query_admin_geral)

    if not admin_alvo:
        logger.critical("Falha crítica: Nenhum administrador cadastrado no sistema inteiro.")
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR, 
            detail="Nenhum administrador disponível para processar a solicitação no momento."
        )

    notificacao_admin = Notification(
        admin_id=admin_alvo.id,
        user_id=current_user.id,
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
        logger.error("Erro ao salvar solicitação e notificação: %s", str(e), exc_info=True)
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail="Erro ao salvar dados no banco.")

    return {"detail": "Solicitação enviada com sucesso. Aguarde a aprovação do administrador."}


@user.get('/card/solicitacao/status', summary='Estado da solicitação de cartão')
@limiter.limit("4/minute; 30/day")
async def status_solicitacao_cartao(
    request: Request,
    session: Session,
    current_user: Get_current_user,
):
    """
    Retorna o estado atual da solicitação de cartão do utilizador.
    Usado pelo frontend para decidir se pode ou não solicitar um novo cartão.
    """

    # 1. Verifica se já tem cartão ativo
    cartao_ativo = await session.scalar(
        select(CartaoMilitante).where(
            CartaoMilitante.user_id == current_user.id,
            CartaoMilitante.activo == True,
        )
    )

    if cartao_ativo:
        return {
            "pode_solicitar": False,
            "status_solicitacao": None,
        }

    # 2. Busca a solicitação mais recente (qualquer status)
    solicitacao = await session.scalar(
        select(SolicitacaoCartao)
        .where(SolicitacaoCartao.user_id == current_user.id)
        .order_by(SolicitacaoCartao.criado_as.desc())  # ajusta o nome do campo se for diferente
        .limit(1)
    )

    if not solicitacao:
        return {
            "pode_solicitar": True,
            "status_solicitacao": None,
        }

    # 3. Decide se pode solicitar com base no status
    status = solicitacao.status

    if status in (StatusSolicitacao.PENDENTE, StatusSolicitacao.APROVADO):
        pode_solicitar = False
    elif status == StatusSolicitacao.REJEITADO:
        pode_solicitar = True
    else:
        # fallback para outros status que possas ter
        pode_solicitar = True

    return {
        "pode_solicitar": pode_solicitar,
        "status_solicitacao": status.value if hasattr(status, "value") else str(status),
    }


@user.get('/card', status_code=status.HTTP_200_OK, response_model=CardBase)
@limiter.limit("30/minute")
async def obter_cartao(
    request: Request,
    session: Session,
    current_user: Get_current_user
    ):
    """
    Retorna os detalhes do cartão ativo do militante ou o status atual da sua última solicitação.
    """
    logger.info('A buscar cartão/solicitação para o utilizador: %s', current_user.email)
    
    # 1. Validação de permissão em primeiro lugar
    if current_user.cadastrar_militante != 'MILITANTE':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="É necessário ser militante para visualizar o cartão."
        )

    # 2. Busca a ÚLTIMA solicitação para saber o estado real (Pendente, Rejeitado, etc.)
    ultima_solicitacao = await session.scalar(
        select(SolicitacaoCartao)
        .where(SolicitacaoCartao.user_id == current_user.id)
        .order_by(SolicitacaoCartao.criado_as.desc())
    )

    # Se nunca solicitou ou se foi REJEITADO, não tem cartão ativo.
    # Retorna os campos nulos de forma segura com o status correto para o Next.js liberar o botão.
    if not ultima_solicitacao or ultima_solicitacao.status == StatusSolicitacao.REJEITADO:
        return {
            "id": None,
            "numero_cartao": None,
            "nome_militante": None,
            "data_emissao": None,
            "image_url": None,
            "url_qrcode": None,
            "activo": False,
            "provincia": None,
            "municipio": None,
            "status": ultima_solicitacao.status if ultima_solicitacao else "NENHUM"
        }

    # 3. Se a solicitação está PENDENTE, ele também não tem cartão emitido ainda
    if ultima_solicitacao.status == StatusSolicitacao.PENDENTE:
        return {
            "id": None,
            "numero_cartao": None,
            "nome_militante": None,
            "data_emissao": None,
            "image_url": None,
            "url_qrcode": None,
            "activo": False,
            "provincia": None,
            "municipio": None,
            "status": "PENDENTE"
        }

    # 4. Se chegou aqui, a solicitação está APROVADA. Vamos buscar o cartão ativo.
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
    
    # Caso de inconsistência: aprovado mas cartão não gerado por erro de sistema
    if not cartao:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitação aprovada, mas nenhum cartão ativo foi gerado."
        )

    # 5. Retorna o payload completo e válido mapeado para o CardBase
    return {
        "id": cartao.id,
        "numero_cartao": current_user.militante_numero,
        "nome_militante": current_user.nome_completo,
        "data_emissao": cartao.data_emissao,
        "image_url": cartao.image_url,
        "url_qrcode": cartao.url_qrcode,
        "activo": cartao.activo,
        "provincia": cartao.provincia,
        "municipio": cartao.municipio,
        "status": "APROVADO"
    }


@user.get('/doacoes', status_code=HTTPStatus.OK, response_model=DoacaoList)
@limiter.limit('30/minute')
async def listar_doacoes(
    request: Request,
    session: Session,
    current_user: Get_current_user,
    status: DonationStatusEnum | None = Query(None),
    metodo: MetodoPagamentoEnum | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    """Lista doações. Filtro territorial via doador (se aplicável)."""
    filtros = []

    if status:
        filtros.append(Doacao.status == status)
    if metodo:
        filtros.append(Doacao.metodo_pagamento == metodo)


    filtros.append(Doacao.user_id == current_user.id)
    # Escopo: admin provincial/municipal só vê doações de users do território
    filtros.append(Doacao.user_id.isnot(None))
    query = (
        select(Doacao)
        .join(User, User.id == Doacao.user_id)
        .options(selectinload(Doacao.doador))
        .where(*filtros)
    )


    count_q = (
        select(func.count(Doacao.id))
        .join(User, User.id == Doacao.user_id)
        .where(*filtros)
    )

    count_q = select(func.count(Doacao.id)).where(*filtros) if filtros else select(func.count(Doacao.id))

    total = await session.scalar(count_q) or 0

    result = await session.execute(
        query.order_by(Doacao.data_doacao.desc()).limit(limit).offset(offset)
    )
    doacoes = result.scalars().all()

    results = []
    for d in doacoes:
        results.append(
            DoacaoResponse(
                id=d.id,
                user_id=d.user_id,
                quantia=d.quantia,
                moeda=d.moeda,
                meses_pagar=d.meses_pagar,
                descricao=d.descricao,
                metodo_pagamento=d.metodo_pagamento,
                id_transacao=d.id_transacao,
                status=d.status,
                observacao=d.observacao,
                data_doacao=d.data_doacao,
                aprovado_em=d.aprovado_em,
            )
        )

    return {'total': total, 'results': results}


@user.get('/notificacoes',
          status_code=HTTPStatus.OK,
          response_model=NotificationListResponse
          )
@limiter.limit("30/minute")
async def listar_notificacoes(
    request: Request,
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
    filtros = [Notification.user_id == current_user.id, Notification.destinatario != 'ADMIN']
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
@limiter.limit("30/minute")
async def listar_notificacoes_nao_lidas(
    request: Request,
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
    filtros = [Notification.user_id == current_user.id, Notification.destinatario != 'ADMIN']
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




@user.get('/notificacoes/dashboard',
          status_code=HTTPStatus.OK,
          response_model=NotificationListResponse
          )
@limiter.limit("30/minute")
async def listar_notificacoes_dashboard(
    request: Request,
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
    filtros = [Notification.user_id == current_user.id, Notification.destinatario != 'ADMIN']
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
@limiter.limit("30/minute")
async def listar_notificacoes_lidas(
    request: Request,
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
    filtros = [Notification.user_id == current_user.id, Notification.lido_as.is_not(None), Notification.destinatario != 'ADMIN']
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
    


@user.patch(
    '/notificacoes/{id_notificacao}/ler',
    status_code=HTTPStatus.OK,
    response_model=NotificationResponse
)
@limiter.limit("30/minute")
async def marcar_como_lida(
    request: Request,
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

    filtros = [Notification.user_id == current_user.id, Notification.id == id_notificacao, Notification.destinatario != 'ADMIN']
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


def _estado_ui(status: str) -> str:
    mapa = {
        'APPROVED': 'Pago',
        'PENDING': 'Pendente',
        'REJECTED': 'Rejeitado',
        'CANCELLED': 'Cancelado',
    }
    return mapa.get(status, status)



@user.get(
    '/minhas-contribuicoes',
    status_code=status.HTTP_200_OK,
    response_model=ContribuicoesIndividuoResponse,
)
@limiter.limit('30/minute')
async def listar_minhas_contribuicoes(
    request: Request,
    session: Session,
    current_user: Get_current_user,
    ano: int | None = Query(None, description='Filtrar por ano (ex: 2026). Omitir = todos'),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    """
    Histórico de quotas + doações de um militante.
    """
    logger.info(
        'usuaio %s listando contribuições suas (ano=%s)',
        current_user.id,
        ano,
    )

    usuario = await session.scalar(select(User).where(User.id == current_user.id))
    if not usuario:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Utilizador não encontrado.')

    items: list[ContribuicaoItem] = []
    total_pago = Decimal('0')

    # ── Quotas ───────────────────────────────────────────────────
    q_quota = select(PagamentoQuota).where(PagamentoQuota.user_id == current_user.id)
    if ano is not None:
        q_quota = q_quota.where(
            extract('year', PagamentoQuota.data_pagamento) == ano
        )

    quotas = (await session.execute(q_quota)).scalars().all()
    for p in quotas:
        data = p.aprovado_em or p.data_pagamento
        if p.status == QuotaStatusEnum.APPROVED:
            total_pago += p.quantia
        items.append(
            ContribuicaoItem(
                id=p.id,
                tipo=TipoContribuicao.QUOTA,
                data=data,
                referencia=p.referencia,
                valor=p.quantia,
                estado=_estado_ui(p.status.value if hasattr(p.status, 'value') else str(p.status)),
                status=p.status.value if hasattr(p.status, 'value') else str(p.status),
                periodo=p.periodo,
                metodo_pagamento=(
                    p.metodo_pagamento.value
                    if hasattr(p.metodo_pagamento, 'value')
                    else str(p.metodo_pagamento)
                ),
            )
        )

    # ── Doações ──────────────────────────────────────────────────
    q_doacao = select(Doacao).where(Doacao.user_id == current_user.id)
    if ano is not None:
        q_doacao = q_doacao.where(extract('year', Doacao.data_doacao) == ano)

    doacoes = (await session.execute(q_doacao)).scalars().all()
    for d in doacoes:
        data = d.aprovado_em or d.data_doacao
        if d.status == DonationStatusEnum.APPROVED:
            total_pago += d.quantia
        items.append(
            ContribuicaoItem(
                id=d.id,
                tipo=TipoContribuicao.DOACAO,
                data=data,
                referencia=d.referencia,
                valor=d.quantia,
                estado=_estado_ui(d.status.value if hasattr(d.status, 'value') else str(d.status)),
                status=d.status.value if hasattr(d.status, 'value') else str(d.status),
                periodo=None,
                metodo_pagamento=(
                    d.metodo_pagamento.value
                    if hasattr(d.metodo_pagamento, 'value')
                    else str(d.metodo_pagamento)
                ),
            )
        )

    # Ordenar por data desc e paginar
    items.sort(key=lambda x: x.data, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]

    return ContribuicoesIndividuoResponse(
        user_id=usuario.id,
        nome=usuario.nome_completo,
        total_pago=total_pago,
        ano=ano,
        total=total,
        limit=limit,
        offset=offset,
        results=page,
    )


@user.get('/ultimo-pagamento/quota', status_code=status.HTTP_200_OK, response_model=UltimoPagamentoQuotaResponse)
@limiter.limit('30/minute')
async def obter_ultimo_pagamento_quota(
    request: Request,
    current_user: Get_current_user,
    session: Session
):
    """
    Retorna as informações da quota do usuário logado baseado na expiração.
    """
    logger.info('Usuário %s solicitando último pagamento de quota', current_user.id)

    # Se o utilizador nunca pagou cotas (campo nulo no banco)
    if not current_user.data_expiracao_quota:
        return UltimoPagamentoQuotaResponse(
            ultimo_pagamento=None,
            proximo_pagamento=None,
            dias_restantes=0
        )

    # data_expiracao_quota representa até quando a quota dele é válida (próximo pagamento)
    proximo_pagamento = current_user.data_expiracao_quota
    
    # O último pagamento assume-se que foi feito 30 dias antes da data de expiração
    ultimo_pagamento = proximo_pagamento - timedelta(days=30)
    
    hoje = datetime.now(timezone.utc).date()
    # Calcula a diferença exata em dias (pode ser negativa se estiver em atraso)
    dias_restantes = (proximo_pagamento - hoje).days

    return UltimoPagamentoQuotaResponse(
        ultimo_pagamento=ultimo_pagamento,
        proximo_pagamento=proximo_pagamento,
        dias_restantes=max(0, dias_restantes), # Retorna 0 se os dias forem negativos (ou remova o max() se quiser mostrar dias em atraso)
    )


@user.delete('/delete/', status_code=HTTPStatus.OK)
@limiter.limit('2/minute')
async def delete_user(
    request: Request,
    response: Response,
    _captcha: Claudflare_turnfile,
    session: Session,
    caches: Redis,
    current_user: Get_current_user,
    schemas: DeleteUser,
    backgroundTasks: BackgroundTasks,
) -> dict[str, str]:
    """Desativa a conta do utilizador autenticado (soft delete).

    Exige a senha e, se a conta tiver 2FA, o código TOTP ou de resgate.
    Revoga todas as sessões e notifica os administradores competentes.
    """
    agora = datetime.now(timezone.utc)
    conta = ContaSnapshot.de(current_user)

    if current_user.deletado_em is not None:
        raise HTTPException(HTTPStatus.BAD_REQUEST, MSG_JA_DESATIVADA)
    if current_user.bloqueado_ate and current_user.bloqueado_ate > agora:
        raise HTTPException(HTTPStatus.TOO_MANY_REQUESTS, MSG_BLOQUEADO)

    # 1. Reautenticação
    if not await senha_valida(conta, schemas.confirmar_senha):
        await registar_falha_credencial(session, conta, agora, MSG_SENHA_INCORRETA)

    resgate_id = None
    if conta.two_factor_enabled:
        ok, resgate_id = await verificar_segundo_fator(session, conta, schemas.codigo_2fa)
        if not ok:
            await registar_falha_credencial(session, conta, agora, MSG_2FA_INVALIDO)

    # 2. Eliminação (transação única)
    admin_ids = await ids_admins_a_notificar(session, conta.provincia_id)
    if not admin_ids:
        logger.warning('Nenhum admin para notificar a eliminação de %s.', conta.id)

    try:
        await desativar_conta(session, current_user, conta, agora, resgate_id, admin_ids)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        logger.exception('Erro ao desativar a conta %s.', conta.email_log)
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, MSG_ERRO_INTERNO)

    logger.info('Conta %s desativada por auto-exclusão.', conta.email_log)

    # 3. Pós-commit (falhas aqui não desfazem a eliminação)
    try:
        await caches.incr('v1:usuarios:lista:versao')
    except Exception:
        logger.error('Falha ao invalidar a cache após eliminar %s.', conta.email_log)

    try:
        await enviar_email_conta_desativada(
            backgroundTasks, nome_completo=conta.nome_completo, email_destino=conta.email
        )
    except Exception:
        logger.error('Falha ao agendar o e-mail de conta desativada (%s).', conta.email_log)

    limpar_cookies_auth(response)
    return {'msg': 'Conta desativada com sucesso.'}




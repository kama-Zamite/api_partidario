import pyotp
import qrcode
import io
import secrets
import base64
import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Response,
)
from typing import Annotated
from project_part.db.session import get_session  # Substitua pelo seu método de sessão
from project_part.model.models import User, BackupCode  # Seu modelo SQLAlchemy de Usuário
from project_part.core.secury import hash_password, verify_password
from project_part.core.secury import Get_current_user  # Sua dependência de autenticação JWT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from project_part.api.Auth_2fa.schemas import Code2FA

logger = logging.getLogger(__name__)
router_2FA = APIRouter(prefix="/auth/2fa", tags=["Autenticação 2FA"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router_2FA.post("/setup")
async def setup_2fa(current_user: Get_current_user, db: Session):
    """
        Gera o segredo TOTP e retorna o QR Code
        necessário para configurar o autenticador.
    """
    if current_user.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA já está ativado nesta conta.")

    secret = pyotp.random_base32()
    try:
        logger.info("Tentado adcionar segredo do 2FA")
        current_user.two_factor_secret = secret
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("erro ao tentar adcionar segredo do 2FA %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="erro ao tentar atualizar o estudos do 2FA")
    


    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="UNITA PGM",
    )

    # Retorna apenas dados puros em texto
    return {
        "provisioning_uri": provisioning_uri
    }


# @router_2FA.post(
#     "/setup",
#     responses={
#         200: {
#             "content": {
#                 "image/png": {}
#             }
#         }
#     }
# )
# async def setup_2fa(
#     current_user: Get_current_user,
#     db: Session,
# ):
#     """
#     Gera o segredo TOTP e retorna o QR Code
#     necessário para configurar o autenticador.
#     """

#     if current_user.two_factor_enabled:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="2FA já está ativado nesta conta.",
#         )

#     secret = pyotp.random_base32()

#     try:
#         current_user.two_factor_secret = secret
#         await db.commit()

#     except Exception:
#         await db.rollback()
#         logger.exception(
#             "Erro ao iniciar configuração do 2FA para usuário ID=%s",
#             current_user.id,
#         )
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Erro ao iniciar configuração do 2FA.",
#         )

#     totp = pyotp.TOTP(secret)

#     provisioning_uri = totp.provisioning_uri(
#         name=current_user.email,
#         issuer_name="UNITA Plataforma",
#     )

#     qr = qrcode.QRCode(
#         version=1,
#         box_size=10,
#         border=5,
#     )

#     qr.add_data(provisioning_uri)
#     qr.make(fit=True)

#     img = qr.make_image(
#         fill_color="black",
#         back_color="white",
#     )

#     buffer = io.BytesIO()

#     img.save(
#         buffer,
#         format="PNG",
#     )
    
#     buffer.seek(0)

#     return Response(
#         content=buffer.getvalue(),
#         media_type="image/png",
#     )


@router_2FA.post("/verify-and-enable")
async def verify_and_enable_2fa(
    body: Code2FA,
    current_user: Get_current_user,
    db: Session,
):
    """
    Valida o código TOTP e ativa definitivamente o 2FA.
    """

    if current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O 2FA já está ativado nesta conta.",
        )

    if not current_user.two_factor_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O setup do 2FA não foi iniciado.",
        )

    totp = pyotp.TOTP(current_user.two_factor_secret)

    codigo_valido = totp.verify(
        body.codigo,
        valid_window=1,
    )

    if not codigo_valido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código inválido ou expirado.",
        )

    # ─── SE O CÓDIGO FOR VÁLIDO, GERAMOS OS CÓDIGOS DE BACKUP ───
    codigos_limpos = []
    objetos_backup = []

     # Vamos gerar 5 códigos de 8 dígitos numéricos aleatórios
    for _ in range(5):
        # Gera algo como "48291053"
        codigo_aleatorio = "".join(secrets.choice("0123456789") for _ in range(8))
        codigos_limpos.append(codigo_aleatorio)
        
        # Cria o hash para guardar na base de dados
        hash_do_codigo = hash_password(codigo_aleatorio)
        
        # Cria a instância do modelo
        objetos_backup.append(
            BackupCode(user_id=current_user.id, code_hash=hash_do_codigo)
        )
    try:
        # 1. Vincula o usuário explicitamente à sessão atual do banco de dados
        user_atualizado = await db.merge(current_user)
        
        # 2. Altera o valor no objeto mesclado
        user_atualizado.two_factor_enabled = True

        # CORREÇÃO: Adiciona os objetos de backup criados à sessão ativa do banco
        db.add_all(objetos_backup)

        # 3. Salva e atualiza tudo de uma vez (Usuário + 5 códigos)
        await db.commit()
        await db.refresh(user_atualizado)

    except Exception:
        await db.rollback()

        logger.exception(
            "Erro ao ativar 2FA e gerar códigos de backup para usuário ID=%s",
            current_user.id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao ativar o 2FA.",
        )

    return {
        "message": "Autenticação de Dois Fatores (2FA) ativada com sucesso!",
        "two_factor_enabled": user_atualizado.two_factor_enabled,
        "backup_codes": codigos_limpos
    }


@router_2FA.post("/disable")
async def disable_2fa(
    body: Code2FA,
    current_user: Get_current_user,
    db: Session,
):
    """
    Desativa o 2FA da conta do usuário após validar o código atual.
    """
    # 1. Verifica se o 2FA está mesmo ativo
    if not current_user.two_factor_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O 2FA não está ativo nesta conta.",
        )

    # 2. Inicializa o validador com o segredo guardado
    totp = pyotp.TOTP(current_user.two_factor_secret)

    # 3. Valida se o código enviado é correto
    codigo_valido = totp.verify(
        body.codigo,
        valid_window=1,
    )

    if not codigo_valido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código de verificação inválido. Não foi possível desativar.",
        )

    try:
        # 4. Mescla o usuário na sessão assíncrona ativa
        user_atualizado = await db.merge(current_user)
        
        # 5. Desliga o recurso e APAGA a chave secreta antiga por segurança
        user_atualizado.two_factor_enabled = False
        user_atualizado.two_factor_secret = None  # Limpeza preventiva

        await db.commit()
        await db.refresh(user_atualizado)

    except Exception:
        await db.rollback()
        logger.exception(
            "Erro ao desativar 2FA para usuário ID=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao desativar o 2FA.",
        )

    return {
        "message": "Autenticação de Dois Fatores (2FA) desativada com sucesso."
    }



# Lógica dentro do seu endpoint de validação de login:
async def verificar_segundo_fator(user_id, codigo_enviado, db):
    # 1. Se o código tiver 6 dígitos, valida com o pyotp tradicional
    if len(codigo_enviado) == 6:
        # (Sua validação normal com pyotp...)
        return True
        
    # 2. Se o código tiver 8 dígitos, é um código de backup!
    elif len(codigo_enviado) == 8:
        # Busca todos os códigos ativos (não usados) deste utilizador
        result = await db.execute(
            select(BackupCode).where(BackupCode.user_id == user_id, BackupCode.used == False)
        )
        codigos_banco = result.scalars().all()

        if not codigos_banco:
            logger.error("Codigo de backup invalido")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Codigo de backup invalido')
        
        # Compara o código enviado com os hashes guardados
        for codigo_db in codigos_banco:
            if verify_password(codigo_enviado, codigo_db.code_hash): # Sua função de verificar hash
                # Código válido! Marca como usado para nunca mais ser reutilizado
                codigo_db.used = True
                await db.commit()
                return True
                
        raise HTTPException(status_code=400, detail="Código de backup inválido ou já utilizado.")


#versao final se geracao de qrcode no Backend

# @router_2FA.post("/setup")
# async def setup_2fa(current_user: Get_current_user, db: Session):
#     if current_user.two_factor_enabled:
#         raise HTTPException(status_code=400, detail="2FA já ativo.")

#     secret = pyotp.random_base32()
#     current_user.two_factor_secret = secret
#     await db.commit()

#     totp = pyotp.TOTP(secret)
#     provisioning_uri = totp.provisioning_uri(
#         name=current_user.email,
#         issuer_name="UNITA Plataforma",
#     )

#     # Retorna apenas dados puros em texto
#     return {
#         "secret": secret,
#         "provisioning_uri": provisioning_uri
#     }

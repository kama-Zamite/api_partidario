import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus

from project_part.core.secury import (
    verify_password,
    Get_current_user,
    decrypt_totp_secret,
    )
from fastapi.concurrency import run_in_threadpool
from project_part.utils.security_helpers import (
    mascarar_email,
    duracao_bloqueio_min,
    erro_interno,
    resposta_credenciais_invalidas,
)
from project_part.core.setting import settings
from project_part.utils.crypto import HASH_SEM
from project_part.model.models import (
    AdminScope,
    User,
    UserRefreshToken,
    BackupCode,
    Notification,
    RoleCategoriaNotificacao,
    CadastrarComo,
)

import pyotp
from fastapi import (
    HTTPException,
    Request,
    Response,
)
from sqlalchemy import (
    and_,
    or_,
    select,
    update, 
    func,
)

logger = logging.getLogger(__name__)

MSG_SENHA_INCORRETA = 'A senha inserida está incorreta.'
MSG_2FA_INVALIDO = 'Código de dois fatores inválido.'
MSG_BLOQUEADO = 'Demasiadas tentativas. Tente novamente mais tarde.'
MSG_JA_DESATIVADA = 'A conta já foi desativada.'
MSG_ERRO_INTERNO = 'Erro interno ao processar a desativação da conta.'


@dataclass(frozen=True)
class ContaSnapshot:
    """Valores lidos antes do 1.º commit (o commit expira o objeto ORM)."""
    id: uuid.UUID
    email: str
    email_log: str
    nome_completo: str
    provincia_id: uuid.UUID | None
    two_factor_enabled: bool
    totp_secret_cifrado: str | None
    password_hash: str
    tipo_user: str

    @classmethod
    def de(cls, u: User) -> 'ContaSnapshot':
        return cls(
            id=u.id,
            email=u.email,
            email_log=mascarar_email(u.email),
            nome_completo=u.nome_completo,
            provincia_id=u.provincia_id,
            two_factor_enabled=u.two_factor_enabled,
            totp_secret_cifrado=u.two_factor_secret,
            password_hash=u.password_hash,
            tipo_user=(
                'Militante'
                if u.cadastrar_militante == CadastrarComo.MILITANTE
                else 'Simpatizante'
            ),
        )


# ─────────────────────────── Falhas de credencial ───────────────────────────

async def registar_falha_credencial(
    session,
    conta: ContaSnapshot,
    agora: datetime,
    detalhe: str
) -> None:
    """Conta a falha no mesmo contador do login (incremento atómico) e levanta 400/429."""
    try:
        tentativas = await session.scalar(
            update(User)
            .where(User.id == conta.id)
            .values(tentativa_acertos=func.coalesce(User.tentativa_acertos, 0) + 1)
            .returning(User.tentativa_acertos)
        )
        bloqueou = tentativas >= settings.MAX_TENTATIVAS
        if bloqueou:
            n_bloqueios = await session.scalar(
                update(User)
                .where(User.id == conta.id)
                .values(
                    tentativas_apos_bloqueio=func.coalesce(User.tentativas_apos_bloqueio, 0) + 1,
                    tentativa_acertos=0,
                )
                .returning(User.tentativas_apos_bloqueio)
            )
            await session.execute(
                update(User)
                .where(User.id == conta.id)
                .values(
                    bloqueado_ate=agora + timedelta(minutes=duracao_bloqueio_min(n_bloqueios))
                )
            )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception('Falha ao registar tentativa falhada de %s.', conta.email_log)
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, MSG_ERRO_INTERNO)

    logger.warning('Credenciais inválidas na eliminação de %s (bloqueou=%s).', conta.email_log, bloqueou)
    if bloqueou:
        raise HTTPException(HTTPStatus.TOO_MANY_REQUESTS, MSG_BLOQUEADO)
    raise HTTPException(HTTPStatus.BAD_REQUEST, detalhe)


# ─────────────────────────────── Verificações ───────────────────────────────

async def senha_valida(conta: ContaSnapshot, senha: str) -> bool:
    async with HASH_SEM:
        return await run_in_threadpool(verify_password, senha, conta.password_hash)


async def verificar_segundo_fator(
    session,
    conta: ContaSnapshot,
    codigo_bruto: str | None
) -> tuple[bool, uuid.UUID | None]:
    """Valida TOTP (6 dígitos) ou código de resgate (8). Devolve (ok, id_do_resgate)."""
    codigo = (codigo_bruto or '').strip()

    if len(codigo) == 6:
        try:
            segredo = decrypt_totp_secret(conta.totp_secret_cifrado)
        except Exception:
            logger.exception('Falha ao desencriptar segredo 2FA de %s.', conta.id)
            raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, 'Erro interno de segurança.')
        return pyotp.TOTP(segredo).verify(codigo, valid_window=1), None

    if len(codigo) == 8:
        resgates = (
            await session.scalars(
                select(BackupCode).where(
                    BackupCode.user_id == conta.id, BackupCode.used.is_(False)
                )
            )
        ).all()
        async with HASH_SEM:
            for resgate in resgates:
                if await run_in_threadpool(verify_password, codigo, resgate.code_hash):
                    return True, resgate.id

    return False, None


# ─────────────────────────────── Notificações ───────────────────────────────

async def ids_admins_a_notificar(
        session,
        provincia_id: uuid.UUID | None) -> set[uuid.UUID]:
    """Admin provincial (da mesma província) + superadmins (sem território)."""
    superadmin = and_(AdminScope.provincia_id.is_(None), AdminScope.municipio_id.is_(None))
    criterios = [superadmin]
    if provincia_id is not None:
        criterios.append(
            and_(AdminScope.provincia_id == provincia_id, AdminScope.municipio_id.is_(None))
        )

    ids = await session.scalars(
        select(User.id)
        .join(AdminScope, AdminScope.user_id == User.id)
        .where(
            User.role_id == settings.ADMIN_ROLE_ID,
            User.ativo.is_(True),
            User.deletado_em.is_(None),
            or_(*criterios),
        )
    )
    return set(ids.all())


# ───────────────────────────────── Transação ────────────────────────────────

async def desativar_conta(
    session,
    user: User,
    conta: ContaSnapshot,
    agora: datetime,
    resgate_id: uuid.UUID | None,
    admin_ids: set[uuid.UUID],
) -> None:
    """Soft delete + revogação de TODAS as sessões + notificações, numa só transação."""
    user.deletado_em = agora
    user.ativo = False
    user.password_alterado_em = agora  # invalida os access tokens existentes
    user.tentativa_acertos = 0
    session.add(user)

    await session.execute(
        update(UserRefreshToken)
        .where(UserRefreshToken.user_id == conta.id, UserRefreshToken.revogado.is_(False))
        .values(revogado=True, revogado_em=agora)
    )

    if resgate_id is not None:  # uso único, mesmo com pedidos concorrentes
        usado = await session.execute(
            update(BackupCode)
            .where(BackupCode.id == resgate_id, BackupCode.used.is_(False))
            .values(used=True)
        )
        if usado.rowcount != 1:
            raise HTTPException(HTTPStatus.BAD_REQUEST, MSG_2FA_INVALIDO)

    session.add_all(
        Notification(
            admin_id=admin_id,
            user_id=conta.id,
            titulo='Delete de Conta',
            mensagem=f'O {conta.tipo_user} {conta.nome_completo} eliminou a sua conta.',
            tipo_usuario=conta.tipo_user,
            destinatario='ADMIN',
            categoria=RoleCategoriaNotificacao.DELETE_CONTA,
        )
        for admin_id in admin_ids
    )
    await session.commit()


def limpar_cookies_auth(response: Response) -> None:
    for chave in ('access_token', 'refresh_token'):
        response.delete_cookie(
            key=chave,
            path='/',
            httponly=True,
            samesite=settings.SAMESITE_COOKIE,
            secure=settings.SECURE_COOKIES,
        )
    response.headers['Cache-Control'] = 'no-store'

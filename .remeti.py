#Aqui tens os endpoints de recuperação de senha **prontos para produção**, no mesmo estilo e padrão de segurança que tens no resto da aplicação.

### 1. Schema (coloca no teu ficheiro de schemas)

#```python
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

class ForgotPasswordSchema(BaseModel):
    email: EmailStr

class ResetPasswordSchema(BaseModel):
    token: str = Field(..., min_length=20)
    nova_senha: str = Field(..., min_length=8, max_length=128)
    confirmacao_senha: str

    @field_validator("nova_senha")
    @classmethod
    def validar_forca_senha(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra maiúscula.")
        if not re.search(r"[a-z]", v):
            raise ValueError("A senha deve conter pelo menos uma letra minúscula.")
        if not re.search(r"\d", v):
            raise ValueError("A senha deve conter pelo menos um número.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("A senha deve conter pelo menos um caractere especial.")
        return v

    @field_validator("confirmacao_senha")
    @classmethod
    def senhas_iguais(cls, v: str, info) -> str:
        if "nova_senha" in info.data and v != info.data["nova_senha"]:
            raise ValueError("As senhas não coincidem.")
        return v
```

---

### 2. Modelo do Token (models.py)

```python
class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user = relationship("User", back_populates="password_reset_tokens")
```

Não te esqueças de adicionar a relação no modelo `User`:

```python
password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
```

---

### 3. Funções auxiliares (podes colocar num `auth_utils.py` ou onde preferires)

```python
import secrets
from datetime import datetime, timedelta, timezone

def gerar_token_reset() -> tuple[str, str]:
    """Retorna (token_em_claro, token_hash)"""
    token_claro = secrets.token_urlsafe(32)
    token_hash = hash_password(token_claro)
    return token_claro, token_hash
```

---

### 4. Endpoints (produção)

```python
from datetime import datetime, timedelta, timezone
from fastapi import status, BackgroundTasks, Request, Response
from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

# ============================================================
# 1. PEDIDO DE RECUPERAÇÃO DE SENHA
# ============================================================
@user.post(
    "/password/forgot",
    status_code=status.HTTP_200_OK,
    summary="Solicitar recuperação de senha"
)
@limiter.limit("3/minute; 8/hour; 15/day")
async def forgot_password(
    request: Request,
    body: ForgotPasswordSchema,
    session: Session,
    backgroundTasks: BackgroundTasks,
    _captcha: Claudflare_turnfile,
):
    """
    Inicia o fluxo de recuperação de senha.
    Sempre devolve a mesma resposta (anti-enumeração).
    """
    email = body.email.lower().strip()
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    logger.info("Pedido de recuperação de senha para o e-mail: %s (ip=%s)", email, ip)

    user = await session.scalar(
        select(User).where(User.email == email)
    )

    # Só processa se o utilizador existir e estiver ativo
    if user and user.ativo and not user.bloqueado_permanente:
        try:
            # 1. Invalida todos os tokens anteriores deste utilizador
            await session.execute(
                update(PasswordResetToken)
                .where(
                    PasswordResetToken.user_id == user.id,
                    PasswordResetToken.used == False  # noqa: E712
                )
                .values(used=True)
            )

            # 2. Gera novo token
            token_claro, token_hash = gerar_token_reset()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=20)

            novo_token = PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
                ip_address=ip,
                user_agent=(user_agent or "")[:500] or None,
            )
            session.add(novo_token)
            await session.commit()

            # 3. Envia e-mail
            link = f"{settings.FRONTEND_URL}/redefinir-senha?token={token_claro}"

            backgroundTasks.add_task(
                email_recuperacao_senha_async,
                nome_completo=user.nome_completo,
                email_destino=user.email,
                link_reset=link,
                minutos_validade=20,
            )

            logger.info(
                "Token de recuperação gerado para o utilizador ID=%s",
                user.id
            )

        except Exception as e:
            await session.rollback()
            logger.exception(
                "Erro ao processar pedido de recuperação de senha para %s: %s",
                email, str(e)
            )
            # Mesmo em erro interno, não revelamos nada ao cliente

    # Resposta sempre igual (anti-enumeração)
    return {
        "message": "Se o endereço de e-mail estiver associado a uma conta, receberá instruções para redefinir a senha."
    }


# ============================================================
# 2. REDEFINIÇÃO DE SENHA (com token)
# ============================================================
@user.post(
    "/password/reset",
    status_code=status.HTTP_200_OK,
    summary="Redefinir senha com token de recuperação"
)
@limiter.limit("5/minute; 15/hour")
async def reset_password(
    request: Request,
    body: ResetPasswordSchema,
    session: Session,
    _captcha: Claudflare_turnfile,
):
    """
    Redefine a senha usando um token de recuperação válido.
    Revoga todas as sessões existentes.
    """
    ip = get_client_ip(request)
    agora = datetime.now(timezone.utc)

    logger.info("Tentativa de redefinição de senha (ip=%s)", ip)

    # 1. Busca tokens ainda válidos (não usados e não expirados)
    tokens = await session.scalars(
        select(PasswordResetToken).where(
            PasswordResetToken.used == False,  # noqa: E712
            PasswordResetToken.expires_at > agora
        )
    )
    tokens_lista = tokens.all()

    token_valido = None
    for t in tokens_lista:
        if verify_password(body.token, t.token_hash):
            token_valido = t
            break

    if not token_valido:
        logger.warning("Token de recuperação inválido ou expirado (ip=%s)", ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token inválido ou expirado. Solicite um novo link de recuperação."
        )

    # 2. Carrega o utilizador
    user = await session.scalar(
        select(User).where(User.id == token_valido.user_id)
    )

    if not user or not user.ativo or user.bloqueado_permanente:
        logger.warning(
            "Tentativa de reset com token de utilizador inválido/inativo (user_id=%s)",
            token_valido.user_id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token inválido ou expirado. Solicite um novo link de recuperação."
        )

    # 3. Verifica se a nova senha é diferente da atual (opcional mas recomendado)
    if await asyncio.to_thread(verify_password, body.nova_senha, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nova senha deve ser diferente da senha atual."
        )

    try:
        # 4. Atualiza a senha
        user.password_hash = await asyncio.to_thread(hash_password, body.nova_senha)
        user.password_alterado_em = agora
        user.atualizado_em = agora

        # 5. Marca o token como usado
        token_valido.used = True

        # 6. Invalida TODOS os outros tokens de reset deste utilizador
        await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != token_valido.id
            )
            .values(used=True)
        )

        # 7. Revoga TODAS as sessões ativas (refresh tokens)
        await revogar_todas_sessoes(session, user.id, agora)

        # 8. (Opcional recomendado) Força reconfiguração do 2FA
        # if user.two_factor_enabled:
        #     user.two_factor_enabled = False
        #     user.two_factor_secret = None
        #     # Também apagar códigos de backup se quiseres
        #     await session.execute(
        #         delete(BackupCode).where(BackupCode.user_id == user.id)
        #     )

        session.add(user)
        await session.commit()

        logger.info(
            "Senha redefinida com sucesso para o utilizador ID=%s (ip=%s)",
            user.id, ip
        )

    except Exception as e:
        await session.rollback()
        logger.exception(
            "Erro ao redefinir senha do utilizador ID=%s: %s",
            user.id, str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível redefinir a senha no momento. Tente novamente."
        )

    return {
        "message": "Senha redefinida com sucesso. Faça login com a nova senha."
    }
```

---

### Checklist de produção

| Item | Status |
|------|--------|
| Token de alta entropia (`secrets.token_urlsafe(32)`) | ✅ |
| Guarda apenas o **hash** do token | ✅ |
| Validade curta (20 minutos) | ✅ |
| Uso único | ✅ |
| Rate limiting forte | ✅ |
| Anti-enumeração (resposta sempre igual) | ✅ |
| Revoga todas as sessões após reset | ✅ |
| Impede reutilização da senha atual | ✅ |
| Captcha | ✅ |
| Logging adequado | ✅ |
| Tratamento de erros sem vazar informação | ✅ |
| Invalidação de tokens antigos | ✅ |

---

### Recomendações finais

1. Cria a migration do modelo `PasswordResetToken`.
2. Implementa a função `email_recuperacao_senha_async` (com template profissional).
3. Decide se queres forçar a reconfiguração do 2FA após reset (está comentado no código).
4. No frontend, o link deve ser algo como:  
   `https://teu-dominio.com/redefinir-senha?token=...`

Queres que eu também te forneça a versão da função de envio de e-mail e o template HTML?
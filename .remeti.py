# =============================================================================
# SEC-008 — Reset de senha (auth_router.py ~613) + últimos call sites
#
# Marcadores:
#   # [SEC-008]    -> resolve a vulnerabilidade
#   # [HARDENING]  -> outras correcções encontradas ao ler o código
#
# Imports extra:
#   import asyncio
#   from sqlalchemy import update
#   from app.security.sessions import revogar_todas_sessoes
# =============================================================================


# =============================================================================
# 1) POST /redefinir-senha
# =============================================================================
@auth.post('/redefinir-senha', status_code=HTTPStatus.OK)
@limiter.limit('5/minute')
async def redefinir_senha(
    request: Request,
    payload: RedefinirSenhaSchema,
    session: Session):
    """Endpoint para redefinir a senha do usuário. Recebe o token de recuperação e a nova senha, verifica a validade do token e atualiza a senha no banco de dados.
    Revoga TODAS as sessões existentes do utilizador (refresh tokens e access tokens).
    Args:
        payload (RedefinirSenhaSchema): Objeto contendo o token de recuperação e a nova senha.
        session (Session): Sessão assíncrona do banco de dados (SQLAlchemy).
    Raises:
        HTTPException [404 NOT FOUND]: Se o usuário não for encontrado no banco de dados.
        HTTPException [400 BAD REQUEST]: Se o token já foi usado ou é inválido.
    Returns:
        dict: Mensagem informando que a senha foi atualizada com sucesso.
    """

    email, token_id = await check_token_recuperar_senha(
        payload.token,
        session
        )

    # [HARDENING] hash_password é CPU-bound (bcrypt/argon2). Antes corria síncrono
    #             dentro do event loop e DENTRO da transacção. Agora corre numa thread
    #             e ANTES de abrir qualquer lock na base de dados.
    pwd_hash = await asyncio.to_thread(hash_password, payload.password)

    try:
        # [HARDENING] Removidos os selectinload(User.provincia/municipio): duas
        #             queries extra que este endpoint nunca usa.
        user_banco = await session.scalar(select(User).where(User.email == email))

        if not user_banco:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='Usuário associado ao token não encontrado.')

        # Guardado agora: depois do commit/rollback os atributos ficam expirados.
        user_id = user_banco.id

        # [SEC-008] CONSUMO ATÓMICO do token de recuperação (uso único).
        #           Antes: SELECT (usado = False) e, mais abaixo, `usado = True`.
        #           Dois pedidos simultâneos com o MESMO link passavam ambos pelo SELECT
        #           antes de qualquer commit e redefiniam a senha duas vezes. Agora o
        #           UPDATE condicional só dá rowcount == 1 a UM dos pedidos; o outro
        #           recebe a mensagem de "já utilizado".
        logger.info('Consumindo token de recuperação: %s', token_id)
        resultado_token = await session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.id == token_id,
                PasswordResetToken.usado.is_(False),
            )
            .values(usado=True)
            .execution_options(synchronize_session=False)
        )
        if resultado_token.rowcount != 1:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Este link de recuperação já foi utilizado ou é inválido.",
            )
        logger.info('Token de recuperação consumido com sucesso: %s', token_id)

        # [SEC-008] (opcional, recomendado) Invalida também OUTROS links de reset
        #           pendentes deste utilizador, para que um e-mail antigo/roubado não
        #           permita um segundo reset. Só se PasswordResetToken tiver user_id:
        #
        #   await session.execute(
        #       update(PasswordResetToken)
        #       .where(PasswordResetToken.user_id == user_id, PasswordResetToken.usado.is_(False))
        #       .values(usado=True)
        #       .execution_options(synchronize_session=False)
        #   )

        data_atualizacao = datetime.now(timezone.utc)
        user_banco.password_hash = pwd_hash
        user_banco.atualizado_em = data_atualizacao
        # [SEC-008] Muda a "versão de senha" (pwv): todos os access tokens emitidos até
        #           agora deixam de ser aceites pelo check_token no próximo pedido.
        #           ATENÇÃO: o PATCH /perfil/password bloqueia nova troca durante 30 dias
        #           após este campo; quem faz reset fica 30 dias sem poder trocar a senha
        #           pelo perfil. Se não quiseres isto, separa a versão numa coluna própria.
        user_banco.password_alterado_em = data_atualizacao

        # [SEC-008] flush() explícito: faz o UPDATE users (bloqueia a linha do
        #           utilizador) ANTES do UPDATE dos tokens. Mesma ordem de locks do
        #           /refresh e do PATCH /perfil/password (users -> user_refresh_tokens),
        #           o que evita deadlocks e serializa reset e refresh concorrentes.
        await session.flush()

        # [SEC-008] Revoga TODOS os refresh tokens NA MESMA TRANSACÇÃO da nova senha e
        #           do consumo do token de reset: ou acontece tudo, ou nada.
        revogados = await revogar_todas_sessoes(session, user_id, data_atualizacao)

        await session.commit()
        logger.info(
            'Senha atualizada com sucesso para o usuário %s. Sessões revogadas: %d',
            user_id,  # [HARDENING] id em vez do e-mail nos logs
            revogados,
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(
            "Erro crítico ao redefinir senha (token_id=%s): %s",
            token_id,
            str(e),
        )
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Erro interno ao processar a redefinição de senha.",
        )
    # [SEC-008] Não emitimos sessão aqui: o utilizador tem de fazer login com a nova
    #           senha (e passar no 2FA, se activo).
    return {
        "status": "success",
        "message": "Senha redefinida com sucesso!",
    }


# =============================================================================
# 2) ÚLTIMOS CALL SITES DE create_token  (fecha o passo 3 do SEC-008)
#    Imports: from app.security.sessions import emitir_access_token
# =============================================================================

# --- 2a) POST /login, ramo SEM 2FA ------------------------------------------
#
#   ANTES:
#       token_gerado = create_token({'sub': str(user.id)})
#   DEPOIS:
#       # [SEC-008] access token com sub + type=access + pwv
#       token_gerado = emitir_access_token(user.id, user.password_alterado_em)
#
# --- 2b) POST /login/2fa-verify ---------------------------------------------
#   O token é emitido DEPOIS do commit, por isso guarda a versão da senha antes
#   dele (junto de nome_completo / email_destino / user_id_str):
#
#       nome_completo = user.nome_completo
#       email_destino = user.email
#       user_id_str = str(user.id)
#       pwd_alterado_em = user.password_alterado_em    # [SEC-008] guardado antes do commit
#
#   e no ponto de emissão:
#
#   ANTES:
#       token_gerado = create_token({'sub': user_id_str})
#   DEPOIS:
#       # [SEC-008]
#       token_gerado = emitir_access_token(user_id, pwd_alterado_em)
#
# --- 2c) Verificação final ----------------------------------------------------
#   Procura por `create_token(` em todo o projecto. Só deve restar UMA ocorrência:
#   a chamada dentro do próprio emitir_access_token. Qualquer outra emite tokens sem
#   `pwv` (e o check_token passa a rejeitá-los para quem já mudou a senha).
# =============================================================================
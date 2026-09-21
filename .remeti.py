# =============================================================================
# PATCHES — 2FA em produção (IP inconsistente entre /login e /2fa-verify)
#
# CAUSA: o /login gravava na challenge o header x-forwarded-for EM BRUTO
#        (cadeia "cliente, cloudflare, render..."), enquanto o /2fa-verify
#        comparava só o PRIMEIRO IP (get_client_ip). Nunca coincidiam.
#
# Marcadores:  # [FIX-2FA] = correcção da causa   # [HARDENING] = extra
# =============================================================================


# =============================================================================
# A) get_client_ip  (security/two_factor_challenge.py)
# [HARDENING] Trunca ao limite da coluna UserRefreshToken.ip_address (String(45)).
#             Um x-forwarded-for forjado e longo rebentava o INSERT do refresh token.
# =============================================================================
def get_client_ip(request: Request) -> str | None:
    xff = request.headers.get('x-forwarded-for')
    if xff:
        valor = xff.split(',')[0].strip()
    else:
        valor = request.client.host if request.client else None
    return valor[:45] if valor else None  # [HARDENING] era: return xff.split(',')[0].strip()


# =============================================================================
# B) POST /login — substitui o bloco que calcula ip_address / user_agent
# =============================================================================

#   ANTES (apagar):
#       ip_address = (
#           request.headers.get("x-forwarded-for")
#           or (request.client.host if request.client else None)
#       )
#       if not ip_address:
#           ip_address = request.client.host if request.client else None
#       user_agent = request.headers.get("user-agent")
#
#   DEPOIS:
    # [FIX-2FA] MESMA função que o /2fa-verify usa. Garante que o IP gravado na
    #           challenge é exactamente o IP que será comparado na verificação.
    ip_address = get_client_ip(request)
    user_agent = request.headers.get("user-agent")


# --- B2) /login, ramo SEM 2FA: falha do commit final -------------------------
#   ANTES:
#       try:
#           session.add(user)
#           await session.commit()
#           logger.info('Sucesso na atualizacao do ultimo_login do usuario')
#       except Exception as e:
#           await session.rollback()
#           logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))
#
#   DEPOIS:
    try:
        session.add(user)
        await session.commit()
        logger.info('Sucesso na atualizacao do ultimo_login do usuario')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel concluir o login no DB: %s', str(e))
        # [HARDENING] Este commit é o que GRAVA o refresh token (o
        #             gerar_e_registar_refresh_token só o adiciona à sessão). Se falhar
        #             e continuarmos, enviamos ao cliente um refresh token que não
        #             existe na base -> sessão "válida" que falha no primeiro /refresh.
        #             Agora devolve 500 e nenhum cookie é definido.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento.',
        )


# =============================================================================
# C) POST /login/2fa-verify
# =============================================================================

# --- C1) junto de nome_completo / email_destino / user_id_str (ANTES do commit) --
    nome_completo = user.nome_completo
    email_destino = user.email
    user_id_str = str(user.id)
    # [HARDENING] Guardado antes do commit: depois dele os atributos do `user` podem
    #             estar expirados e aceder-lhes numa sessão async dá MissingGreenlet
    #             (o teu `emitir_access_token(user.id, user.password_alterado_em)`
    #             acontecia DEPOIS do commit).
    pwd_alterado_em = user.password_alterado_em


# --- C2) depois do log "autenticado com sucesso (2FA)" ---------------------------
#   ANTES (apagar TUDO isto):
#       token_gerado = emitir_access_token(user.id, user.password_alterado_em)
#       ip_address = (request.headers.get("x-forwarded-for") or (...))
#       if not ip_address: ...
#       user_agent = request.headers.get("user-agent")
#       refresh_gerado = await gerar_e_registar_refresh_token(... user_id=user.id ...)
#
#   DEPOIS:
    token_gerado = emitir_access_token(user_id, pwd_alterado_em)

    # [FIX-2FA] ip_address e user_agent JÁ foram calculados no topo do endpoint com
    #           get_client_ip. Antes eram recalculados aqui com o x-forwarded-for em
    #           bruto (cadeia inteira), o que dava valores diferentes dentro do mesmo
    #           pedido e podia ultrapassar os 45 caracteres do campo ip_address.
    refresh_gerado = await gerar_e_registar_refresh_token(
        session=session,
        user_id=user_id,
        ip=ip_address,
        user_agent=(user_agent or '')[:500] or None,  # [HARDENING] limite da coluna (500)
    )


# --- C3) commit que grava o refresh token -----------------------------------------
#   ANTES:
#       try:
#           session.add(user)
#           await session.commit()
#           logger.info('Sucesso na atualizacao do ultimo_login do usuario')
#       except Exception as e:
#           await session.rollback()
#           logger.error('Nao foi possivel atualizar a data de ultimo_login no DB: %s', str(e))
#
#   DEPOIS:
    try:
        await session.commit()
        logger.info('Refresh token registado com sucesso (2FA)')
    except Exception as e:
        await session.rollback()
        logger.error('Nao foi possivel registar o refresh token no DB: %s', str(e))
        # [HARDENING] Mesma razão do B2. A challenge já foi consumida (commit anterior),
        #             por isso o utilizador tem de fazer login outra vez: falha segura.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='Erro interno de processamento.',
        )
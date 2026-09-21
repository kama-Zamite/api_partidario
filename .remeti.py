# =============================================================================
# /refresh — versão corrigida a partir do código que colaste
#
# Marcadores:
#   # [REFRESH]  -> alteração desta versão
#
# Imports que TÊM de existir neste módulo (um em falta = NameError = 500 em TODOS
# os refresh, apanhado pelo `except Exception` final):
#   from project_part.<...>.sessions import revogar_todas_sessoes, emitir_access_token
#   from project_part.<...>.two_factor_challenge import get_client_ip
# =============================================================================

# [REFRESH] Constantes usadas pelo endpoint. Na versão que colaste elas não aparecem
#           definidas nem importadas: `IP_MAX` e `UA_MAX` dão NameError no passo 8.
IP_MAX = 45    # UserRefreshToken.ip_address = String(45)
UA_MAX = 500   # UserRefreshToken.user_agent = String(500)

# [REFRESH] Janela (segundos) em que um refresh token já rodado, se voltar a ser
#           apresentado, é tratado como CORRIDA LEGÍTIMA (duas abas / vários pedidos
#           a receber 401 ao mesmo tempo e a chamar /refresh em paralelo) e não como
#           roubo. Fora da janela continua a ser reutilização real -> revoga tudo.
REFRESH_REUSE_GRACE_SECONDS = 10


@auth.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
)
async def refresh_token(
    request: Request,
    response: Response,
    session: Session,
    token_data: dict = Depends(check_refresh_token),
):

    user_id = token_data["user_id"]
    token_jti = token_data["jti"]

    agora = datetime.now(timezone.utc)

    try:

        # =====================================================
        # 1. Buscar e BLOQUEAR o utilizador (antes do token)
        # =====================================================
        # [REFRESH] Na versão que colaste faltava o with_for_update: o comentário do
        #           passo 6 dizia "bloqueado no passo 1" mas era um SELECT simples.
        #           Sem o lock, um refresh a meio de uma troca/reset de senha podia
        #           criar um refresh token que sobrevivia à revogação. Ordem de locks:
        #           users -> user_refresh_tokens (igual à troca de senha e ao reset).
        #           of=User bloqueia só a linha de users, mesmo com joins no modelo.
        #           Se este SELECT FOR UPDATE der erro na tua base, envia-me o erro.

        user = await session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update(of=User)
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 2. LOCK DA LINHA DO TOKEN
        # =====================================================

        result = await session.execute(
            select(UserRefreshToken)
            .where(
                UserRefreshToken.token_jti == token_jti
            )
            .with_for_update()
        )

        db_token = result.scalar_one_or_none()

        if not db_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        if str(db_token.user_id) != str(user_id):
            logger.warning(
                "Refresh token com jti de outro utilizador. jwt_user=%s",
                user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 3. Verificar estado
        # =====================================================

        if db_token.revogado:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 4. Token já rodado: corrida legítima OU reutilização
        # =====================================================

        if db_token.utilizado:

            utilizado_ha = (
                (agora - db_token.utilizado_em).total_seconds()
                if db_token.utilizado_em
                else None
            )

            # [REFRESH] Corrida legítima: outro pedido acabou de rodar ESTE token
            #           (o token novo já foi entregue ao browser pela outra resposta).
            #           Antes: qualquer segundo pedido revogava TODAS as sessões do
            #           utilizador -> "desloga sozinho" com duas abas / pedidos
            #           paralelos. Agora respondemos 409 SEM revogar nada e SEM emitir
            #           tokens; o cliente repete o pedido original com o cookie novo.
            #           Um atacante com o token roubado não ganha nada nesta janela
            #           (não recebe tokens), e depois dela cai na revogação total.
            if utilizado_ha is not None and 0 <= utilizado_ha <= REFRESH_REUSE_GRACE_SECONDS:
                logger.info(
                    "Refresh concorrente tolerado (%.1fs após a rotação). user_id=%s",
                    utilizado_ha,
                    user_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Sessão em renovação. Repita o pedido.",
                )

            logger.warning(
                "Reutilização de refresh token detectada. "
                "user_id=%s",
                user_id,
            )

            # Revoga todas as sessões do usuário.
            await revogar_todas_sessoes(session, user_id, agora)

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 5. Verificar expiração
        # =====================================================

        if db_token.expira_em <= agora:

            db_token.revogado = True
            db_token.revogado_em = agora

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão expirada.",
            )

        # =====================================================
        # 6. Verificar estado da conta
        # =====================================================
        # Conta desativada ou bloqueada permanentemente: revoga TODAS as sessões.

        if not user.ativo or user.bloqueado_permanente:

            await revogar_todas_sessoes(session, user_id, agora)

            await session.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão inválida.",
            )

        # =====================================================
        # 7. Consumir token antigo
        # =====================================================

        db_token.utilizado = True
        db_token.utilizado_em = agora

        # =====================================================
        # 8. Informações da nova sessão
        # =====================================================

        ip_address = (get_client_ip(request) or "")[:IP_MAX] or None

        user_agent = (
            request.headers.get("user-agent") or ""
        )[:UA_MAX] or None

        # =====================================================
        # 9. Criar NOVO refresh token
        # =====================================================

        novo_refresh_token = (
            await gerar_e_registar_refresh_token(
                session=session,
                user_id=user.id,
                ip=ip_address,
                user_agent=user_agent,
            )
        )

        # =====================================================
        # 10. Criar novo access token (sub + type=access + pwv)
        # =====================================================

        novo_access_token = emitir_access_token(
            user.id,
            user.password_alterado_em,
        )

        # =====================================================
        # 11. COMMIT ATÔMICO
        # =====================================================

        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "Falha ao gravar refresh token no banco de dados."
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro interno de autenticação.",
            )

        # =====================================================
        # 12. Atualizar cookies
        # =====================================================

        set_auth_cookies(
            response=response,
            access_token=novo_access_token,
            refresh_token=novo_refresh_token,
        )

        response.headers["Cache-Control"] = "no-store"

        return {
            "status": "success",
            "message": "Tokens de autenticação renovados com sucesso."
        }
    except HTTPException:

        raise

    except Exception:

        await session.rollback()

        # logger.exception regista o traceback completo: é AQUI que aparece
        # o NameError / TypeError que estiver a causar o 500.
        logger.exception(
            "Erro interno durante refresh token."
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno de autenticação.",
        )
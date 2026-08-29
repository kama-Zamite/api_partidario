import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel
from project_part.core.setting import settings

logger = logging.getLogger(__name__)



TEST_SECRETS = {
    "1x00000000000000000000AA": "1x0000000000000000000000000000000AA",  # sempre passa
    "2x00000000000000000000AB": "2x0000000000000000000000000000000AA",  # sempre falha
    "3x00000000000000000000FF": "3x0000000000000000000000000000000AA",  # token já usado
}

async def verificar_turnstile(
    # Recomendo usar o alias para garantir que o FastAPI leia o header no padrão web (com hífens)
    cf_turnstile_response: str = Header(..., alias="cf-turnstile-response", description="Token do Cloudflare Turnstile")
) -> bool:
    """
    Dependência do FastAPI que valida o token do Turnstile enviado no Header da requisição.
    """
    if not cf_turnstile_response or not cf_turnstile_response.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de segurança (Captcha) ausente."
        )

    token_limpo = cf_turnstile_response.strip()
    # producao
    secret_a_usar = settings.CLOUDFLARE_TURNSTILE_SECRET

    # Chaves de teste
    # Usa secret de teste se for um token de teste, senão usa a secret real
    # secret_a_usar = TEST_SECRETS.get(token_limpo, settings.CLOUDFLARE_TURNSTILE_SECRET)

    async with httpx.AsyncClient(timeout=15.0) as client:
        payload = {
            "secret": secret_a_usar,
            "response": token_limpo
        }
        try:
            response = await client.post(
                settings.CLOUDFLARE_VALIDATE_URL,
                data=payload
                )
            
            dados = response.json()

            success = dados.get("success", False)
            error_codes = dados.get("error-codes", [])
            if success:
                logger.info("Turnstile validado com sucesso.")
                return True
            # === Tratamento específico dos erros mais comuns ===
            logger.warning("Turnstile falhou. error-codes=%s | response=%s", error_codes, dados)

            if "invalid-input-response" in error_codes:
                detail = "Token do Captcha inválido ou expirado. Resolva o desafio novamente."
            elif "timeout-or-duplicate" in error_codes:
                detail = "Token do Captcha já foi utilizado ou expirou. Tente novamente."
            elif "invalid-input-secret" in error_codes:
                detail = "Configuração de segurança inválida no servidor."
                logger.error("Secret key do Turnstile está incorreta!")
            elif "bad-request" in error_codes:
                detail = "Requisição de validação malformada."
            else:
                detail = "Validação de segurança falhou. Tente novamente."

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            )
                
        except httpx.TimeoutException:
            logger.error("Timeout ao contactar o Cloudflare Turnstile.")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Serviço de validação temporariamente indisponível (timeout). Tente novamente em alguns segundos.",
            )

        except httpx.RequestError as e:
            logger.error("Erro de rede ao contactar Cloudflare: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível contactar o serviço de validação. Tente novamente.",
            )
        except HTTPException:
        # Re-raise as HTTPExceptions que nós mesmos lançamos
            raise

        except Exception as e:
            logger.exception("Erro inesperado na validação do Turnstile: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erro interno ao validar o Captcha.",
            )


# # Exemplo de uso no seu endpoint de Login ou Cadastro
# @router_auth.post("/login")
# async def login(body: LoginRequest, db: Session = Depends(get_db)):
    
#     # 🌟 VALIDAÇÃO DO CAPTCHA DA CLOUDFLARE
#     captcha_valido = await validar_turnstile(body.captcha_token)
#     if not captcha_valido:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Validação de segurança (Captcha) falhou. Tente novamente."
#         )

#     # ... Resto da sua lógica de login por senha e 2FA ...

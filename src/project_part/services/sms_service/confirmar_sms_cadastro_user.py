import logging
import httpx
from project_part.core.setting import settings

logger = logging.getLogger(__name__)


async def send_sms_cadastro_user(phone_number: str, secret_number: str):
    url = settings.URL_TELCOSMS
    api_key = settings.CHAVE_TELCOSMS

    message_body = f"Use o código: {secret_number} para confirmar seu cadastro."

    payload = {
        "message": {
            "api_key_app": api_key,
            "phone_number": phone_number,
            "message_body": message_body,
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        logger.info(f"Enviando SMS de confirmação de cadastro para o número: {phone_number}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        logger.info(
            f"Resposta TelcoSMS - Status: {response.status_code} | Body: {response.text}"
        )

        response.raise_for_status()
        return response

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Erro HTTP ao enviar SMS para {phone_number}. "
            f"Status: {e.response.status_code} | Resposta: {e.response.text}"
        )
        raise
    except Exception as e:
        logger.error(f"Erro ao enviar SMS de confirmação para {phone_number}. Erro: {e}")
        raise
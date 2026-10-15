import resend
import os
import pathlib
import logging
from project_part.core.setting import settings
from jinja2 import Environment, FileSystemLoader
from project_part.utils.security_helpers import mascarar_email


logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATE))

async def email_reativacao_conta_async(
        email: str,
        name: str
        ):
    LOGO_URL = settings.URL_LOGO_WELLCOME
    REDIRECT_URL = settings.URL_LOGIN

    try:
        content = env.get_template('emailReativacaoConta.html')
        html_content = content.render(
            nome_doador=name,
            logo_url=LOGO_URL,
            url_painel=REDIRECT_URL,
        )
    except Exception as e:
        logger.exception('Erro ao carregar o template Jinja2 do Admin: %s', e)
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email],
        'subject': f'Conta Reativada',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    email_log = mascarar_email(email)
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Email de reativação de conta enviado para %s | ID: %s",
            email_log,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha ao enviar o email de reativação de conta para %s: %s", email_log, str(e))
        return None


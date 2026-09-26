import logging
import pathlib
import resend
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings


resend.api_key = settings.RESEND_API_KEY
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATE))


async def enviar_email_confirmacao_cadastro_user_async(email_destino: str, secret_number: int, nome_completo: str):
    LOGO_URL = settings.URL_LOGO_UNCLOCK
    try:
        content = env.get_template('confirmar_email_cadastro_user.html')

        
        html_content = content.render(
            nome=nome_completo,
            logo_url=LOGO_URL,
            secret_number=secret_number
        )
    except Exception as e:
        logger.exception('erro ao carregar o tamplete jinja2 %s', e)
        return

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_destino],
        'subject': 'Confirmação de cadastro',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "E-mail de login enviado com sucesso para %s | ID: %s",
            email_destino,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha crítica ao enviar e-mail para %s: %s", email_destino, str(e))
        return None
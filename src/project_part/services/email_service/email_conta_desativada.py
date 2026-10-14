import resend
import os
import pathlib
import logging
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY
# Configuração do Jinja2

logger = logging.getLogger(__name__)
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
template_dir = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(template_dir))

async def email_conta_desativada_async(
        nome_completo: str,
        email_militante: str,
    ):

    LOGO_URL = settings.URL_LOGO_WELLCOME
    try:
        content = env.get_template('emailContaDesativada.html')
        html_content = content.render(
            nome_usuario=nome_completo,
            logo_url=LOGO_URL,
            link_suporte=settings.URL_LOGIN
        )
    except Exception as e:
        logger.error(f"Error rendering email template: {e}")
        return

    params = {
        'from': settings.EMAIL_FROM,
        'to': email_militante,  # Enviar para o email do admin
        'subject': f'Notificação de Conta Desativada',
        'html': html_content,
        'reply_to': "no-reply@unita.com"
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de conta desativada enviada para o Admin | ID: %s",
            email_id,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return None
import logging
import pathlib

import resend
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

TEMPLATES = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATES))


async def email_sucesso_login_async(
        nome_completo: str, 
        ip_address: str,
        email_destino: str,
        navegador: str,
        sistema_operacional: str,
        # data_hora: str,
        ):
    LOGO_URL = settings.URL_LOGO_WELLCOME
    REDIRECT_URL = settings.URL_LOGIN
    try:
        content = env.get_template('emailLogin.html')
        html_content = content.render(
            nome=nome_completo,
            ip=ip_address,
            logo_url = LOGO_URL,
            url_redifinir_senha = REDIRECT_URL,
            navegador=navegador,
            sistema_operacional=sistema_operacional,
        )
    except Exception as e:
        logger.exception('erro ao carregar o tamplete jinja2 %s', e)
        return

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_destino],
        'subject': 'Login bem-sucedido',
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
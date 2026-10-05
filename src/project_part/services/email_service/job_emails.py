import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.RESEND_API_KEY

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'

env = Environment(loader=FileSystemLoader(TEMPLATE))

async def enviar_email_quota_vencida_async(
        nome_completo: str,
        email_destinatario: str,
        data_vencimento: str
        ):
    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_LOGIN
    try:
        template = env.get_template("emailQuotaVencida.html")
        html_content = template.render(
            nome_completo=nome_completo,
            data_vencimento=data_vencimento,
            logo_url=LOGO_URL,
            redirect_url=REDIRECT_URL
        )
    except Exception as e:
        logger.error(f"Error rendering email template: {e}")
        return
    
    params = {
        'from': settings.EMAIL_FROM,
        'to': email_destinatario,  # Enviar para o email do admin
        'subject': f'Alerta: Regularização de Quota em Atraso',
        'html': html_content,
        'reply_to': "no-reply@unita.com"
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de quota vencida enviada para o %s | ID: %s",
            email_destinatario,
            email_id,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return None


    
async def enviar_email_ativar_quota_async(
        nome_completo: str,
        email_destinatario: str
        ):
    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_LOGIN
    try:
        template = env.get_template("emailAtivarQuota.html")
        html_content = template.render(
            nome_completo=nome_completo,
            logo_url=LOGO_URL,
            redirect_url=REDIRECT_URL
        )
    except Exception as e:
        logger.error(f"Error rendering email template: {e}")
        return
    params = {
        'from': settings.EMAIL_FROM,
        'to': email_destinatario,  # Enviar para o email do admin
        'subject': f'Ativa as tuas Quotas de Militante',
        'html': html_content,
        'reply_to': "no-reply@unita.com"
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de doação rejeitada enviada para o %s | ID: %s",
            email_destinatario,
            email_id,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return None
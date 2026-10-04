import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY
logger = logging.getLogger(__name__)


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATES = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATES))

async def email_notificacao_quota_aprovar_async(
        nome_completo: str,
        quantia: float,
        meses_pagar: int,
        referencia: str,
        email_destinatario : str,
):
    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_LOGIN

    try:
        content = env.get_template('emailNotificacaoQuotaAprovarAdmin.html')
        html_content = content.render(
            nome_militante=nome_completo,
            quantia=f"{quantia:,.2f} Kz",
            referencia=referencia,
            meses_pagar=meses_pagar,
            logo_url=LOGO_URL,
            url_painel=REDIRECT_URL,
        )
    except Exception as e:
        logger.exception('Erro ao carregar o template Jinja2 do Admin: %s', e)
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_destinatario],
        'subject': f'Aprovação de Pagamento de Quota',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de aprovação de pagamento de quota enviada para o militante %s | ID: %s",
            email_destinatario,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha ao  enviar notificação de aprovação de pagamento de quota para o militante %s: %s", email_destinatario, str(e))
        return None

import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.RESEND_API_KEY
# Configuração do Jinja2


BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
template_dir = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(template_dir))

async def email_notificacao_rejeitada_admin_async(
        nome_completo: str,
        numero_militante: str,
        quantia: float,
        email_militante: str,
        referencia: str,
        motivo_rejeicao: str,
        id_transacao: str,
    ):

    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_LOGIN
    try:
        content = env.get_template('emailNotificacaoDoacaoRejeitadaAdmin.html')
        html_content = content.render(
            nome_doador=nome_completo,
            numero_militante=numero_militante,
            quantia=f"{quantia:,.2f} Kz",
            referencia=referencia,
            id_transacao=id_transacao,
            motivo_rejeicao=motivo_rejeicao,
            logo_url=LOGO_URL,
            url_painel=REDIRECT_URL,
        )
    except Exception as e:
        logger.error(f"Error rendering email template: {e}")
        return
    params = {
        'from': settings.EMAIL_FROM,
        'to': email_militante,  # Enviar para o email do admin
        'subject': f'Notificação de Doação Rejeitada',
        'html': html_content,
        'reply_to': "no-reply@unita.com"
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de doação rejeitada enviada para o Admin | ID: %s",
            email_id,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return None
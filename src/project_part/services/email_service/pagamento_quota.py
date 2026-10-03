import resend
import logging
import pathlib
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

logger = logging.getLogger(__name__)

resend_client = resend.Resend(api_key=settings.RESEND_API_KEY)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATES = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATES))

async def email_notificacao_quota_admin_async(
    nome_completo: str,
    numero_militante: str,
    email_admin: str,  # E-mail do administrador ou da tesouraria geral
    quantia: float,
    meses_pagar: int,
    referencia: str,
    id_transacao: str,
):
    LOGO_URL = settings.CLAUDINARY_URL_CONFIRMACAO
    REDIRECT_URL = settings.URL_LOGIN  # Painel administrativo

    try:
        content = env.get_template('emailNotificacaoQuotaAdmin.html')
        html_content = content.render(
            nome_militante=nome_completo,
            numero_militante=numero_militante,
            quantia=f"{quantia:,.2f} Kz",
            meses_pagar=meses_pagar,
            referencia=referencia,
            id_transacao=id_transacao,
            logo_url=LOGO_URL,
            url_painel=REDIRECT_URL,
        )
    except Exception as e:
        logger.exception('Erro ao carregar o template Jinja2 do Admin: %s', e)
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_admin],
        'subject': f'⚠️ Alerta: Novo Pagamento de Quota ({numero_militante})',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de pagamento de quota enviada para o Admin %s | ID: %s",
            email_admin,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha ao enviar notificação de quota ao Admin %s: %s", email_admin, str(e))
        return None

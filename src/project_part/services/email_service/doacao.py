import resend
import logging
import pathlib
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings


resend.api_key = settings.RESEND_API_KEY
logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATE))

async def email_notificacao_doacao_admin_async(
    nome_completo: str,
    numero_militante: str,
    email_admin: str,
    nome_admin: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
    doador: str | None = None
):
    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_ADMINISTRATIVO

    try:
        content = env.get_template('emailNotificacaoDoacaoAdmin.html')
        html_content = content.render(
            nome_doador=nome_completo,
            numero_militante=numero_militante,
            nome_admin=nome_admin,
            quantia=f"{quantia:,.2f} Kz",
            referencia=referencia,
            id_transacao=id_transacao,
            logo_url=LOGO_URL,
            url_painel=REDIRECT_URL,
            doador_tipo=doador,
        )
    except Exception as e:
        logger.exception('Erro ao carregar o template Jinja2 do Admin: %s', e)
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_admin],
        'subject': f'Nova Doação',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de doação enviada para o Admin %s | ID: %s",
            email_admin,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha ao enviar notificação de doação ao Admin %s: %s", email_admin, str(e))
        return None

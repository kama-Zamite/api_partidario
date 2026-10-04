import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY

# Caminho absoluto 100% à prova de falhas dentro do contentor Docker no Windows
TEMPLATE_DIR = pathlib.Path("/app/src/project_part/templates")
if not TEMPLATE_DIR.exists():
    BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
    TEMPLATE_DIR = BASE_DIR / "templates"

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

async def email_rejeicao_solicitacao_fundo_async(
    nome_completo: str,
    email_solicitante: str,
    motivo_rejeicao: str,
    provincia: str,
    quantia: float,
):
    """
    Envia um e-mail de notificação de rejeição de solicitação de fundos para o solicitante.
    """
    LOGO_URL = settings.CLAUDINARY_URL_QUOTA_PAGAMENTO
    REDIRECT_URL = settings.URL_ADMINISTRATIVO
    
    try:
        template = env.get_template("emailRejeicaoSolicitacaoFundos.html")
        html_content = template.render(
            nome_completo=nome_completo,
            email_solicitante=email_solicitante,
            logo_url=LOGO_URL,
            redirect_url=REDIRECT_URL,
            motivo_rejeicao=motivo_rejeicao,
            provincia=provincia,
            quantia=f"{quantia:,.2f} AOA",
        )

    except Exception as e:
        logger.exception('Erro ao carregar o template Jinja2 do Admin: %s', e)
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_solicitante],
        'subject': 'Solicitação de Fundos Indeferida',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "Notificação de rejeição de solicitação de fundos enviada para o solicitante %s | ID: %s",
            email_solicitante,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha ao enviar notificação de rejeição da solicitação de fundos ao solicitante %s: %s", email_solicitante, str(e))
        return None

import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY
# Configuração do Jinja2
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
template_dir = BASE_DIR / "templates"
env = Environment(loader=FileSystemLoader(template_dir))

async def email_notificacao_suporte_async(
    nome_completo: str,
    email_suporte: str,
    assunto: str,
    mensagem: str,
    categoria: str,
):
    LOGO_URL = settings.CLAUDINARY_URL_CONFIRMACAO
    LINK_RESPOSTA = settings.URL_ADMINISTRATIVO
    try:
        content = env.get_template("emailNotificacaoSuporte.html")
        html_content = content.render(
            nome_completo=nome_completo,
            assunto=assunto,
            mensagem=mensagem,
            categoria=categoria,
            logo_url=LOGO_URL,
            link_resposta = LINK_RESPOSTA,  # Substitua pelo link real de resposta
        )
    except Exception as e:
        logging.error(f"Error rendering email template: {e}")
        return

    params = {
        "from": settings.EMAIL_FROM,
        "to": email_suporte,
        "subject": f"Suporte",
        "html": html_content,
        "reply_to": "no-reply@unita.com"
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logging.info(
            "Notificação de suporte enviada para o Admin | ID: %s",
            email_id,
        )
        return result
    except Exception as e:
        logging.error(f"Failed to send email: {e}")
        return None
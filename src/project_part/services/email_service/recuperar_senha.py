import logging
import pathlib
import resend
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

# Configuração da API Key da Resend
resend.api_key = settings.RESEND_API_KEY  




BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATES = BASE_DIR / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATES))


async def enviar_email_real_async(email_destino: str, token: str, nome_completo: str):
    link_completo = f"https://app-gestao-plataforma-2026.vercel.app/redefinir-senha?token={token}"
    URL_LOGO_OFICIAL = settings.URL_LOGO_UNCLOCK

    # 1. Carregar e renderizar o template Jinja2
    try:
        content = env.get_template("recuperar_senha.html")
        html_content = content.render(
            link=link_completo, 
            logo_url=URL_LOGO_OFICIAL,
            nome=nome_completo
            )
    except Exception as e:
        logger.error("Erro ao carregar o template Jinja2: %s", str(e))
        return

    # 2. Configurar parâmetros de envio via Resend
    params = {
        "from": settings.EMAIL_FROM,  # Valor mapeado do seu .env: "UNITA <onboarding@militantes.dev>"
        "to": [email_destino],
        "subject": "Recuperação de Palavra-passe",
        "html": html_content,
        "reply_to": "no-reply@unita.com",  
    }

    # 3. Enviar via Resend (assíncrono)
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        
        logger.info(
            "E-mail de recuperação enviado com sucesso para %s | ID: %s",
            email_destino,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha crítica ao enviar e-mail para %s: %s", email_destino, str(e))
        return None

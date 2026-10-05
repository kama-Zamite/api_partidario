import resend
import logging
import pathlib
from jinja2 import (
    Environment,
    FileSystemLoader
)

from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).parent.parent.parent

TEMPLATE = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATE))


def _formatar_duracao(minutos: int) -> str:
    if minutos < 60:
        return f'{minutos} minutos'
    horas, resto = divmod(minutos, 60)
    if resto == 0:
        return f'{horas} hora' if horas == 1 else f'{horas} horas'
    return f'{horas}h{resto:02d}min'



async def email_Bloqueado_temp_async(
        nome_completo: str,
        token: str,
        email_destino: str,
        minutos: int = 15,
        ):
    LOGO_URL = settings.URL_LOGO_UNCLOCK
    link_completo = f"https://app-gestao-plataforma-2026.vercel.app/redefinir-senha?token={token}"
    
    try:
        # Corrige o nome do ficheiro para o que realmente existe na pasta templates/
        content = env.get_template('bloqueio_temp_email.html')  # ← corrige aqui
        
        html_content = content.render(
            nome=nome_completo,
            logo_url=LOGO_URL,
            url_redefinir_senha=link_completo,
            duracao=_formatar_duracao(minutos),
        )
    except Exception as e:
        logger.exception('Erro ao carregar/renderizar o template do e-mail de bloqueio')
        return

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_destino],
        'subject': 'Conta bloqueada temporariamente',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
        
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "E-mail de bloqueio temporário enviado com sucesso para %s | ID: %s",
            email_destino,
            email_id,
        )
        return result
    except Exception as e:
        logger.exception("Falha crítica ao enviar e-mail de bloqueio para %s: %s", email_destino, e)
        return None


import logging
import pathlib
from urllib.parse import quote

import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

from project_part.core.setting import settings

resend.api_key = settings.RESEND_API_KEY

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'

# autoescape=True é obrigatório: o nome do utilizador entra no HTML do e-mail.
env = Environment(
    loader=FileSystemLoader(TEMPLATE),
    autoescape=select_autoescape(['html', 'xml']),
)

# Idealmente defina FRONTEND_URL em settings (.env) em vez de fixar aqui.
FRONTEND_URL = getattr(settings, 'FRONTEND_URL', 'https://app-gestao-plataforma-2026.vercel.app')


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
    link_completo = f'{FRONTEND_URL}/redefinir-senha?token={quote(token, safe="")}'

    try:
        template = env.get_template('bloqueio_temp_email.html')
        html_content = template.render(
            nome=nome_completo,
            logo_url=settings.URL_LOGO_UNCLOCK,
            url_redefinir_senha=link_completo,
            duracao=_formatar_duracao(minutos),
        )
    except Exception:
        logger.exception('Erro ao carregar/renderizar o template do e-mail de bloqueio')
        return None

    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_destino],
        'subject': 'Conta bloqueada temporariamente',
        'html': html_content,
        'reply_to': 'no-reply@unita.com',
    }

    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get('id') if isinstance(result, dict) else getattr(result, 'id', 'Desconhecido')
        logger.info(
            "E-mail de bloqueio temporário enviado com sucesso para %s | ID: %s",
            email_destino,
            email_id,
        )
        return result
    except Exception:
        # Ligue aqui o Sentry/alerta: falhas de envio de e-mail de segurança devem ser vistas.
        logger.exception('Falha ao enviar e-mail de bloqueio')
        return None
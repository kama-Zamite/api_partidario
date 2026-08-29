import logging
import pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
TEMPLATE = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATE))


async def enviar_email_confirmacao_cadastro_user_async(email_destino: str, secret_number: int, nome_completo: str):
    try:
        content = env.get_template('confirmar_email_cadastro_user.html')
        html_content = content.render(secret_number=secret_number, nome=nome_completo)
    except Exception as e:
        logger.error('Erro ao carregar o template Jinja2: %s', str(e))
        return

    mensagem = MIMEMultipart('alternative')
    mensagem['From'] = f"UNITA PGM <{settings.SMTP_USER}>"
    mensagem['To'] = email_destino
    mensagem['Subject'] = 'Confirmação de Email'
    mensagem['Reply-To'] = 'no-reply@unita.com'

    mensagem.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        await aiosmtplib.send(
            mensagem,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True if settings.SMTP_PORT == 587 else False,
            use_tls=True if settings.SMTP_PORT == 465 else False,
            # timeout=30.0,
        )
        logger.info('E-mail de confirmação de criacao de usuario enviado com sucesso para %s', email_destino)
    except Exception as e:
        logger.error('Falha crítica ao enviar e-mail para %s: %s', email_destino, str(e))

import logging
import pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

TEMPLATES = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(TEMPLATES))


async def email_sucesso_login_async(
        nome_completo: str, 
        ip_address: str,
        email_destino: str,
        navegador: str,
        sistema_operacional: str,
        ):
    try:
        content = env.get_template('emailLogin.html')
        html_content = content.render(
            nome=nome_completo,
            ip=ip_address,
            navegador=navegador,
            sistema_operacional=sistema_operacional
        )
    except Exception as e:
        logger.exception('erro ao carregar o tamplete jinja2 %s', e)
        return

    mensagem = MIMEMultipart('alternative')
    mensagem['From'] = f"UNITA PGM <{settings.SMTP_USER}>"
    mensagem['To'] = email_destino
    mensagem['Subject'] = 'Login realizado com sucesso'
    mensagem['Reply-To'] = 'no-reply@unita.com'

    mensagem.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        await aiosmtplib.send(
            mensagem,
            hostname=settings.SMTP_HOST,
            username=settings.SMTP_USER,
            port=settings.SMTP_PORT,
            password=settings.SMTP_PASSWORD,
            start_tls=True if settings.SMTP_PORT == 587 else False,
            use_tls=True if settings.SMTP_PORT == 465 else False,
        )
        logger.info('sucesso de cadastro %s', email_destino)
    except Exception as e:
        logger.error('Falha crítica ao enviar e-mail para %s: %s', email_destino, str(e))

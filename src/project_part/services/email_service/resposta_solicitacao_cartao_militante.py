import logging
import pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
content = BASE_DIR / 'templates'
env = Environment(loader=FileSystemLoader(content))


async def enviar_resposta_solicitacao_cartao_militante(
    email_destino: str, nome_militante: str, numero_militante: str, status_pedido: str, observacoes: str | None
):
    try:
        template = env.get_template('resposta_solicitacao_cartao_militante.html')
        html_content = template.render(
            nome=nome_militante, numero=numero_militante, status=status_pedido, observacoes=observacoes
        )
    except Exception as e:
        logger.error('Erro ao carregar o template Jinja2: %s', str(e))
        return

    mensagem = MIMEMultipart('alternative')
    mensagem['From'] = f"UNITA PGM <{settings.SMTP_USER}>"
    mensagem['To'] = email_destino
    mensagem['Subject'] = 'Resposta à Solicitação de Cartão de Militante'
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
        )
        logger.info('E-mail de solicitação de cartão de militante enviado com sucesso para %s', email_destino)
    except Exception as e:
        logger.error('Falha crítica ao enviar e-mail para %s: %s', email_destino, str(e))

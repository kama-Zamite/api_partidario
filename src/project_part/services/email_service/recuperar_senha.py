import logging
import pathlib
import resend
from jinja2 import Environment, FileSystemLoader

from project_part.core.setting import settings

logger = logging.getLogger(__name__)

# Configuração do Resend
resend.api_key = settings.RESEND_API_KEY  # ou os.getenv("RESEND_API_KEY")

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
CAMINHO_TEMPLATES = BASE_DIR / "templates"
env = Environment(loader=FileSystemLoader(CAMINHO_TEMPLATES))


async def enviar_email_real_async(email_destino: str, token: str, nome_completo: str):
    link_completo = f"https://app-gestao-plataforma-2026.vercel.app/redefinir-senha?token={token}"

    # 1. Carregar e renderizar o template Jinja2
    try:
        content = env.get_template("recuperar_senha.html")
        html_content = content.render(link=link_completo, nome=nome_completo)
    except Exception as e:
        logger.error("Erro ao carregar o template Jinja2: %s", str(e))
        return

    # 2. Enviar via Resend (assíncrono)
    params = {
        "from": settings.EMAIL_FROM,  # ex: "UNITA PGM <onboarding@resend.dev>"
        "to": [email_destino],
        "subject": "Recuperação de Palavra-passe",
        "html": html_content,
        "reply_to": "no-reply@unita.com",  # opcional
    }

    try:
        # Versão assíncrona do SDK
        result = await resend.Emails.send_async(params)
        logger.info(
            "E-mail de recuperação enviado com sucesso para %s | ID: %s",
            email_destino,
            result.get("id"),
        )
        return result
    except Exception as e:
        logger.error("Falha crítica ao enviar e-mail para %s: %s", email_destino, str(e))
        return None














# import logging
# import pathlib
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText

# import aiosmtplib
# from jinja2 import Environment, FileSystemLoader

# from project_part.core.setting import settings

# logger = logging.getLogger(__name__)


# BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent

# CAMINHO_TEMPLATES = BASE_DIR / 'templates'
# env = Environment(loader=FileSystemLoader(CAMINHO_TEMPLATES))


# async def enviar_email_real_async(email_destino: str, token: str, nome_completo: str):
#     link_completo = f'https://app-gestao-plataforma-2026.vercel.app/redefinir-senha?token={token}'

#     try:
#         content = env.get_template('recuperar_senha.html')
#         html_content = content.render(link=link_completo, nome=nome_completo)
#     except Exception as e:
#         logger.error('Erro ao carregar o template Jinja2: %s', str(e))
#         return
#     # 1. Criar a estrutura da mensagem
#     mensagem = MIMEMultipart('alternative')
#     mensagem['From'] = f"UNITA PGM <{settings.SMTP_USER}>"
#     mensagem['To'] = email_destino
#     mensagem['Subject'] = 'Recuperação de Palavra-passe'
#     mensagem['Reply-To'] = 'no-reply@unita.com'

#     mensagem.attach(MIMEText(html_content, 'html', 'utf-8'))

#     # 3. Enviar de forma assíncrona via SMTP
#     try:
#         await aiosmtplib.send(
#             mensagem,
#             hostname=settings.SMTP_HOST,
#             port=settings.SMTP_PORT,
#             username=settings.SMTP_USER,
#             password=settings.SMTP_PASSWORD,
#             start_tls=True if settings.SMTP_PORT == 587 else False,
#             use_tls=True if settings.SMTP_PORT == 465 else False,
#         )
#         logger.info('E-mail de recuperação enviado com sucesso para %s', email_destino)
#     except Exception as e:
#         logger.error('Falha crítica ao enviar e-mail para %s: %s', email_destino, str(e))

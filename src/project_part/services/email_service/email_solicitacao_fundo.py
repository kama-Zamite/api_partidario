import pathlib
import logging
import resend
from jinja2 import Environment, FileSystemLoader
from project_part.core.setting import settings

logger = logging.getLogger(__name__)
resend.api_key = settings.RESEND_API_KEY
# Configuração do Jinja2
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
template_dir = BASE_DIR / "templates"
env = Environment(loader=FileSystemLoader(template_dir))

async def email_notificacao_solicitacao_fundo_async(
    nome_completo: str,
    email_superadmin: str,
    email_solicitante: str,
    provincia: str,
    descricao: str,
    quantidade: str,
):
    """Envia um e-mail de notificação para o solicitante de uma solicitação de fundo."""
    LOGO_URL = settings.CLAUDINARY_URL_CONFIRMACAO
    link_redirecionamento = settings.URL_ADMINISTRATIVO
    try:
        # Carregar o template HTML
        template = env.get_template("emailNotificacaoSolicitacaoFundo.html")
        # Renderizar o template com os dados fornecidos
        html_content = template.render(
            nome_completo=nome_completo,
            email_superadmin=email_superadmin,
            provincia=provincia,
            descricao=descricao,
            email_solicitante=email_solicitante,
            quantidade=f"{quantidade:,.2f} Kz",
            logo_url=LOGO_URL,
            link_redirecionamento=link_redirecionamento,
        )
        # Enviar o e-mail usando a API do Resend
    except Exception as e:
            logger.exception('erro ao carregar o tamplete jinja2 %s', e)
            return
    
    params = {
        'from': settings.EMAIL_FROM,
        'to': [email_superadmin],
        'subject': 'Solicitação de Fundo',
        'html': html_content,
        'reply_to': 'no-reply@unita.com'
    }
    try:
        result = await resend.Emails.send_async(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "Desconhecido")
        logger.info(
            "E-mail de solicitação de fundo enviado com sucesso para %s | ID: %s",
            email_superadmin,
            email_id,
        )
        return result
    except Exception as e:
        logger.error("Falha crítica ao enviar e-mail para %s: %s", email_superadmin, str(e))
        return None
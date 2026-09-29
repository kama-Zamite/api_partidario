from datetime import datetime, timezone
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
import logging
from user_agents import parse
from project_part.core.setting import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def mascarar_email(email: str) -> str:
    """Mascara o e-mail nos logs (dados pessoais)."""
    local, _, dominio = (email or '').partition('@')
    if not dominio:
        return '***'
    return f'{local[:2]}***@{dominio}'

def como_utc(dt: datetime | None) -> datetime | None:
    """Garante datetime aware (colunas DateTime sem timezone devolvem naive)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def duracao_bloqueio_min(n_bloqueios: int) -> int:
    """Bloqueio progressivo: 15, 30, 60, 120... até ao teto."""
    expoente = min(max(n_bloqueios - 1, 0), 10)
    return min(settings.BLOQUEIO_BASE_MIN * (2**expoente), settings.BLOQUEIO_MAX_MIN)

def resposta_credenciais_invalidas(background=None) -> JSONResponse:
    """Resposta idêntica para TODAS as falhas de autenticação.

    Usa o mesmo formato do HTTPException ({"detail": ...}) para o frontend
    não precisar de alterações.
    """
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={'detail': settings.MSG_CREDENCIAIS},
        headers={'Cache-Control': 'no-store'},
        background=background,
    )

def erro_interno(detalhe: str = 'Erro interno de processamento.') -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=detalhe,
    )

def descrever_cliente(user_agent: str) -> tuple[str, str]:
    """Devolve (navegador, sistema) legíveis para o e-mail de aviso."""
    try:
        ua = parse(user_agent)
        navegador = f'{ua.browser.family} {ua.browser.version_string}'.strip()
        sistema = f'{ua.os.family} {ua.os.version_string}'.strip()

        if 'other' in navegador.lower() and ua.is_bot:
            navegador = 'Ferramenta de Automação/API Docs'
        if 'other' in sistema.lower():
            sistema = 'Sistema Desconhecido'
        return navegador, sistema
    except Exception:
        logger.exception('Falha ao interpretar o User-Agent')
        return 'Navegador Desconhecido', 'Sistema Desconhecido'


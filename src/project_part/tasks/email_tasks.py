"""Tarefas de e-mail no Taskiq."""

import asyncio
import logging

from fastapi import BackgroundTasks
from project_part.core.setting import settings
from project_part.core.tk_broker import broker

# [ADAPTAR] caminho real das suas funções de e-mail
from project_part.services.email_service.email_bloqueio_temp import email_Bloqueado_temp_async
from project_part.services.email_service.loginEmail import email_sucesso_login_async


logger = logging.getLogger(__name__)

ENFILEIRAR_TIMEOUT_S = 2.0   # não deixar o login pendurado se o Redis não responder
RETRY_ESPERA_S = 5           # pausa antes de falhar, para a retentativa não ser instantânea


class EnvioEmailFalhou(RuntimeError):
    """Sinaliza a falha ao Taskiq para que ele repita a tarefa."""


# ---------------------------------------------------------------------------
# Tarefas (executadas pelo worker)
# ---------------------------------------------------------------------------
# As suas funções de e-mail engolem erros e devolvem None em caso de falha.
# Aqui tratamos None como falha para ativar a retentativa.
# Nunca coloque o token nas mensagens de erro.

@broker.task(task_name='email.bloqueio_temporario', retry_on_error=True, max_retries=5)
async def tarefa_email_bloqueio(
    nome_completo: str,
    token: str,
    email_destino: str,
    minutos: int = 15,
) -> None:
    resultado = await email_Bloqueado_temp_async(nome_completo, token, email_destino, minutos)
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de bloqueio temporário')


@broker.task(task_name='email.sucesso_login', retry_on_error=True, max_retries=3)
async def tarefa_email_login(
    nome_completo: str,
    ip_address: str,
    email_destino: str,
    navegador: str,
    sistema_operacional: str,
) -> None:
    resultado = await email_sucesso_login_async(
        nome_completo=nome_completo,
        ip_address=ip_address,
        email_destino=email_destino,
        navegador=navegador,
        sistema_operacional=sistema_operacional,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de aviso de login')




# ---------------------------------------------------------------------------
# Enfileirar com plano B (chamado pelos endpoints)
# ---------------------------------------------------------------------------
async def _enfileirar(tarefa, fallback, background: BackgroundTasks, **kwargs) -> None:

    if not settings.TASKIQ_ENABLED:
        background.add_task(fallback, **kwargs)
        return
    try:
        await asyncio.wait_for(tarefa.kiq(**kwargs), timeout=ENFILEIRAR_TIMEOUT_S)
    except Exception:
        # Em casos raros (timeout depois de a mensagem já ter entrado) pode duplicar o e-mail.
        logger.exception('Fila indisponível; a usar BackgroundTasks como plano B (%s)', tarefa.task_name)
        background.add_task(fallback, **kwargs)


async def enviar_email_bloqueio(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    token: str,
    email_destino: str,
    minutos: int,
) -> None:
    await _enfileirar(
        tarefa_email_bloqueio,
        email_Bloqueado_temp_async,
        background,
        nome_completo=nome_completo,
        token=token,
        email_destino=email_destino,
        minutos=minutos,
    )


async def enviar_email_login(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    ip_address: str,
    email_destino: str,
    navegador: str,
    sistema_operacional: str,
) -> None:
    await _enfileirar(
        tarefa_email_login,
        email_sucesso_login_async,
        background,
        nome_completo=nome_completo,
        ip_address=ip_address,
        email_destino=email_destino,
        navegador=navegador,
        sistema_operacional=sistema_operacional,
    )
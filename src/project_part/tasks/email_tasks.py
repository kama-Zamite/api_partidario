"""Tarefas de e-mail no Taskiq."""

import asyncio
import logging

from fastapi import BackgroundTasks
from project_part.core.setting import settings
from project_part.core.tk_broker import broker

# [ADAPTAR] caminho real das suas funções de e-mail
from project_part.services.email_service.email_bloqueio_temp import email_Bloqueado_temp_async
from project_part.services.email_service.pagamento_quota import email_notificacao_quota_admin_async
from project_part.services.email_service.loginEmail import email_sucesso_login_async
from project_part.services.email_service.doacao import email_notificacao_doacao_admin_async
from project_part.services.email_service.pagamento_quota_aprovar import email_notificacao_quota_aprovar_async
from project_part.services.email_service.pagamento_quota_rejeitado import email_notificacao_quota_rejeitado_async
from project_part.services.email_service.doacao_aprovada import email_notificacao_doacao_aprovada_admin_async
from project_part.services.email_service.doacao_rejeitada import email_notificacao_rejeitada_admin_async
from project_part.services.email_service.email_suporte import email_notificacao_suporte_async
from project_part.services.email_service.email_solicitacao_fundo import email_notificacao_solicitacao_fundo_async
from project_part.services.email_service.email_aprovacao_solicitacao_fundos import email_aprovacao_solicitacao_fundo_async
from project_part.services.email_service.email_rejeitar_solicitacao_fundos import email_rejeicao_solicitacao_fundo_async
from project_part.services.email_service.recuperar_senha import enviar_email_real_async
from project_part.services.email_service.confirmar_email_cadastro_user import enviar_email_confirmacao_cadastro_user_async
from project_part.services.email_service.email_cadastro_realizado_sucesso import email_sucesso_cadastro_async
from project_part.services.email_service.job_emails import (
    enviar_email_ativar_quota_async,
    enviar_email_quota_vencida_async
)


logger = logging.getLogger(__name__)

ENFILEIRAR_TIMEOUT_S = 2.0   # não deixar o login pendurado se o Redis não responder
RETRY_ESPERA_S = 5           # pausa antes de falhar, para a retentativa não ser instantânea


class EnvioEmailFalhou(RuntimeError):
    """Sinaliza a falha ao Taskiq para que ele repita a tarefa."""




# # Tarefa para enviar e-mail de quota vencida
# @broker.task(task_name='email.quota_vencida', retry_on_error=True, max_retries=3)
# async def tarefa_email_quota_vencida(
#     nome_completo: str,
#     email_destinatario: str,
#     data_vencimento: str
# ) -> None:
#     resultado = await enviar_email_quota_vencida_async(
#         nome_completo=nome_completo,
#         email_destinatario=email_destinatario,
#         data_vencimento=data_vencimento
#     )
#     if resultado is None:
#         await asyncio.sleep(RETRY_ESPERA_S)
#         raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de quota vencida')


@broker.task(task_name='email.ativar_quota', retry_on_error=True, max_retries=3)
async def tarefa_email_ativar_quota(
    nome_completo: str,
    email_destinatario: str
) -> None:
    resultado = await enviar_email_ativar_quota_async(
        nome_completo=nome_completo,
        email_destinatario=email_destinatario
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de ativação de quota')


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


@broker.task(task_name='email.notificacao_quota_admin', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_quota_admin(
    nome_completo: str,
    numero_militante: str,
    email_admin: str,
    nome_admin: str,
    quantia: float,
    meses_pagar: int,
    referencia: str,
    id_transacao: str,
) -> None:
    resultado = await email_notificacao_quota_admin_async(
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        nome_admin=nome_admin,
        quantia=quantia,
        meses_pagar=meses_pagar,
        referencia=referencia,
        id_transacao=id_transacao,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de quota')

@broker.task(task_name='email.notificacao_quota_aprovar', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_quota_aprovar(
    nome_completo: str,
    quantia: float,
    meses_pagar: int,
    referencia: str,
    email_destinatario: str,
) -> None:
    resultado = await email_notificacao_quota_aprovar_async(
        nome_completo=nome_completo,
        quantia=quantia,
        meses_pagar=meses_pagar,
        referencia=referencia,
        email_destinatario=email_destinatario,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de aprovação de quota')

@broker.task(task_name='email.notificacao_quota_rejeitado', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_quota_rejeitado(
    nome_completo: str,
    quantia: float,
    motivo_rejeicao: str,
    referencia: str,
    email_destinatario: str,
) -> None:
    resultado = await email_notificacao_quota_rejeitado_async(
        nome_completo=nome_completo,
        quantia=quantia,
        motivo_rejeicao=motivo_rejeicao,
        referencia=referencia,
        email_destinatario=email_destinatario,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de rejeição de quota')

# ---------------------------------------------------------------------------
# Tarefa de notificação de doação (executada pelo worker)
# ---------------------------------------------------------------------------
@broker.task(task_name='email.notificacao_doacao_admin', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_doacao_admin(
    nome_completo: str,
    numero_militante: str | None,
    email_admin: str,
    nome_admin: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
    doador: str | None = None,
) -> None:
    resultado = await email_notificacao_doacao_admin_async(
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        nome_admin=nome_admin,
        doador=doador,
        quantia=quantia,
        referencia=referencia,
        id_transacao=id_transacao,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de doação')

@broker.task(task_name='email.notificacao_doacao_aprovada_admin', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_doacao_aprovada_admin(
    nome_completo: str,
    numero_militante: str | None,
    email_militante: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
) -> None:
    resultado = await email_notificacao_doacao_aprovada_admin_async(
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        email_militante=email_militante,
        quantia=quantia,
        referencia=referencia,
        id_transacao=id_transacao,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de doação aprovada')


@broker.task(task_name='email.notificacao_doacao_rejeitada_admin', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_doacao_rejeitada_admin(
    nome_completo: str,
    numero_militante: str | None,
    email_militante: str,
    quantia: float,
    motivo_rejeicao: str,
    referencia: str,
    id_transacao: str,
) -> None:
    resultado = await email_notificacao_rejeitada_admin_async(
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        email_militante=email_militante,
        quantia=quantia,
        motivo_rejeicao=motivo_rejeicao,
        referencia=referencia,
        id_transacao=id_transacao,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de doação rejeitada')


# ---------------------------------------------------------------------------
# Tarefa de notificação de suporte (executada pelo worker)
# ---------------------------------------------------------------------------
@broker.task(task_name='email.notificacao_suporte', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_suporte(
    nome_completo: str,
    email_suporte: str,
    assunto: str,
    mensagem: str,
    categoria: str,
) -> None:
    resultado = await email_notificacao_suporte_async(
        nome_completo=nome_completo,
        email_suporte=email_suporte,
        assunto=assunto,
        mensagem=mensagem,
        categoria=categoria,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de suporte')


# ---------------------------------------------------------------------------
# Tarefa de notificação de solicitação de fundo (executada pelo worker)
# ---------------------------------------------------------------------------

@broker.task(task_name='email.notificacao_solicitacao_fundo', retry_on_error=True, max_retries=3)
async def tarefa_notificacao_solicitacao_fundo(
    nome_completo: str,
    email_superadmin: str,
    email_solicitante: str,
    provincia: str,
    descricao: str,
    quantidade: str,
) -> None:
    resultado = await email_notificacao_solicitacao_fundo_async(
        nome_completo=nome_completo,
        email_superadmin=email_superadmin,
        email_solicitante=email_solicitante,
        provincia=provincia,
        descricao=descricao,
        quantidade=quantidade,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de notificação de solicitação de fundo')



@broker.task(task_name='email.aprovacao_solicitacao_fundo', retry_on_error=True, max_retries=3)
async def tarefa_aprovacao_solicitacao_fundo(
    nome_completo: str,
    email_solicitante: str,
) -> None:
    resultado = await email_aprovacao_solicitacao_fundo_async(
        nome_completo=nome_completo,
        email_solicitante=email_solicitante,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de aprovação de solicitação de fundo')


@broker.task(task_name='email.rejeicao_solicitacao_fundo', retry_on_error=True, max_retries=3)
async def tarefa_rejeicao_solicitacao_fundo(
    nome_completo: str,
    email_solicitante: str,
    motivo_rejeicao: str,
    provincia: str,
    quantia: float,
) -> None:
    resultado = await email_rejeicao_solicitacao_fundo_async(
        nome_completo=nome_completo,
        email_solicitante=email_solicitante,
        motivo_rejeicao=motivo_rejeicao,
        provincia=provincia,
        quantia=quantia,
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de rejeição de solicitação de fundo')



# ---------------------------------------------------------------------------
# Tarefas de envio de e-mails
# ---------------------------------------------------------------------------

@broker.task(task_name='email.recuperacao_senha', retry_on_error=True, max_retries=3)
async def tarefa_recuperacao_senha(
    email_destino: str,
    token: str,
    nome_completo: str
):
    resultado = await enviar_email_real_async(
        email_destino = email_destino,
        token = token,
        nome_completo = nome_completo
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de rejeição de solicitação de fundo')


@broker.task(task_name='email.confirmacao_cadastro_user', retry_on_error=True, max_retries=3)
async def tarefa_confirmacao_cadastro_user(
    email_destino: str,
    secret_number: int,
    nome_completo: str
):
    resultado = await enviar_email_confirmacao_cadastro_user_async(
        email_destino=email_destino,
        secret_number=secret_number,
        nome_completo=nome_completo
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de rejeição de solicitação de fundo')

@broker.task(task_name='email.cadastro_realizado_sucesso', retry_on_error=True, max_retries=3)
async def tarefa_cadastro_realizado_sucesso(
    nome_completo: str,
    email_destino: str
):
    resultado = await email_sucesso_cadastro_async(
        nome_completo=nome_completo,
        email_destino=email_destino
    )
    if resultado is None:
        await asyncio.sleep(RETRY_ESPERA_S)
        raise EnvioEmailFalhou('Falha ao enviar o e-mail de cadastro realizado com sucesso')
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
    # nome_admin: str,
    sistema_operacional: str,
) -> None:
    await _enfileirar(
        tarefa_email_login,
        email_sucesso_login_async,
        background,
        nome_completo=nome_completo,
        # nome_admin=nome_admin,
        ip_address=ip_address,
        email_destino=email_destino,
        navegador=navegador,
        sistema_operacional=sistema_operacional,
    )


async def enviar_notificacao_quota_admin(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    numero_militante: str,
    email_admin: str,
    nome_admin: str,
    quantia: float,
    meses_pagar: int,
    referencia: str,
    id_transacao: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_quota_admin,
        email_notificacao_quota_admin_async,
        background,
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        nome_admin=nome_admin,
        email_admin=email_admin,
        quantia=quantia,
        meses_pagar=meses_pagar,
        referencia=referencia,
        id_transacao=id_transacao,
    )

async def enviar_notificacao_quota_aprovar(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    quantia: float,
    meses_pagar: int,
    referencia: str,
    email_destinatario: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_quota_aprovar,
        email_notificacao_quota_aprovar_async,
        background,
        nome_completo=nome_completo,
        quantia=quantia,
        meses_pagar=meses_pagar,
        referencia=referencia,
        email_destinatario=email_destinatario,
    )

async def enviar_notificacao_quota_rejeitado(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    quantia: float,
    motivo_rejeicao: str,
    referencia: str,
    email_destinatario: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_quota_rejeitado,
        email_notificacao_quota_rejeitado_async,
        background,
        nome_completo=nome_completo,
        quantia=quantia,
        motivo_rejeicao=motivo_rejeicao,
        referencia=referencia,
        email_destinatario=email_destinatario,
    )

async def enviar_notificacao_doacao_admin(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    numero_militante: str | None,
    email_admin: str,
    nome_admin: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
    doador: str | None = None
) -> None:
    await _enfileirar(
        tarefa_notificacao_doacao_admin,
        email_notificacao_doacao_admin_async,
        background,
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        email_admin=email_admin,
        nome_admin=nome_admin,
        quantia=quantia,
        referencia=referencia,
        doador=doador,
        id_transacao=id_transacao,
    )


async def enviar_notificacao_doacao_aprovada_admin(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    numero_militante: str | None,
    email_militante: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_doacao_aprovada_admin,
        email_notificacao_doacao_aprovada_admin_async,
        background,
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        email_militante=email_militante,
        quantia=quantia,
        referencia=referencia,
        id_transacao=id_transacao,
    )

async def enviar_notificacao_doacao_rejeitada_admin(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    numero_militante: str | None,
    email_militante: str,
    motivo_rejeicao: str,
    quantia: float,
    referencia: str,
    id_transacao: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_doacao_rejeitada_admin,
        email_notificacao_rejeitada_admin_async,
        background,
        nome_completo=nome_completo,
        numero_militante=numero_militante,
        email_militante=email_militante,
        motivo_rejeicao=motivo_rejeicao,
        quantia=quantia,
        referencia=referencia,
        id_transacao=id_transacao,
    )


async def enviar_notificacao_suporte(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_suporte: str,
    assunto: str,
    mensagem: str,
    categoria: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_suporte,
        email_notificacao_suporte_async,
        background,
        nome_completo=nome_completo,
        email_suporte=email_suporte,
        assunto=assunto,
        mensagem=mensagem,
        categoria=categoria,
    )

async def enviar_notificacao_solicitacao_fundo(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_superadmin: str,
    email_solicitante: str,
    provincia: str,
    descricao: str,
    quantidade: str,
) -> None:
    await _enfileirar(
        tarefa_notificacao_solicitacao_fundo,
        email_notificacao_solicitacao_fundo_async,
        background,
        nome_completo=nome_completo,
        email_superadmin=email_superadmin,
        email_solicitante=email_solicitante,
        provincia=provincia,
        descricao=descricao,
        quantidade=quantidade,
    )

async def enviar_aprovacao_solicitacao_fundo(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_solicitante: str,
) -> None:
    await _enfileirar(
        tarefa_aprovacao_solicitacao_fundo,
        email_aprovacao_solicitacao_fundo_async,
        background,
        nome_completo=nome_completo,
        email_solicitante=email_solicitante,
    )


async def enviar_rejeicao_solicitacao_fundo(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_solicitante: str,
    motivo_rejeicao: str,
    provincia: str,
    quantia: float,
) -> None:
    await _enfileirar(
        tarefa_rejeicao_solicitacao_fundo,
        email_rejeicao_solicitacao_fundo_async,
        background,
        nome_completo=nome_completo,
        email_solicitante=email_solicitante,
        motivo_rejeicao=motivo_rejeicao,
        provincia=provincia,
        quantia=quantia,
    )


async def enviar_email_recuperacao_senha(
    background: BackgroundTasks,
    *,
    email_destino: str,
    token: str,
    nome_completo: str  
):
    await _enfileirar(
        tarefa_recuperacao_senha,
        enviar_email_real_async,
        background,
        email_destino=email_destino,
        token=token,
        nome_completo=nome_completo
    )


async def enviar_email_confirmacao_cadastro(
    background: BackgroundTasks,
    *,
    email_destino: str,
    secret_number: int,
    nome_completo: str
):
    await _enfileirar(
        tarefa_confirmacao_cadastro_user,
        enviar_email_confirmacao_cadastro_user_async,
        background,
        email_destino = email_destino,
        secret_number = secret_number,
        nome_completo = nome_completo
    )

async def enviar_email_cadastro_realizado_sucesso(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_destino: str
):
    await _enfileirar(
        tarefa_cadastro_realizado_sucesso,
        email_sucesso_cadastro_async,
        background,
        nome_completo=nome_completo,
        email_destino=email_destino
    )


# async def enviar_email_quota_vencida(
#     background: BackgroundTasks,
#     *,
#     nome_completo: str,
#     email_destinatario: str,
#     data_vencimento: str
# ):
#     await _enfileirar(
#         tarefa_email_quota_vencida,
#         enviar_email_quota_vencida_async,
#         background,
#         nome_completo=nome_completo,
#         email_destinatario=email_destinatario,
#         data_vencimento=data_vencimento
#     )

async def enviar_email_ativar_quota(
    background: BackgroundTasks,
    *,
    nome_completo: str,
    email_destinatario: str
):
    await _enfileirar(
        tarefa_email_ativar_quota,
        enviar_email_ativar_quota_async,
        background,
        nome_completo=nome_completo,
        email_destinatario=email_destinatario
    )

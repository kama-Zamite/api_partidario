from project_part.services.sms_service.confirmar_sms_cadastro_user import send_sms_cadastro_user
from project_part.tasks.email_tasks import (
    enviar_email_confirmacao_cadastro,
    enviar_email_cadastro_realizado_sucesso,
)


# async def enviar_codigo_verificacao(user_data: bool, secret_number: str):
#     if user_data:
#         logger.info("Enviando código de ativação para o e-mail: %s", mascarar_email(dados_validados.email))
#         await enviar_email_confirmacao_cadastro(
#             backgroundTasks,
#             email_destino=dados_validados.email,   # [SEC-001] o validado, igual ao guardado
#             secret_number=secret_number,
#             nome_completo=dados_validados.nome_completo,
#             )
#     else:
#         logger.info("Enviando código de ativação por SMS para o telefone: %s", dados_validados.telefone)
#         await backgroundTasks.add_task(
#             send_sms_cadastro_user,
#             dados_validados.telefone,
#             secret_number
#         )
    
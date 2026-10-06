from project_part.model.models import Notification, RoleCategoriaNotificacao
from datetime import datetime, timezone

def preparar_aviso_primeira_quota(session, user) -> None:
    """Notificação in-app + marca de "já notificado". NÃO faz commit.

    Chamar depois de session.flush(), para o user.id já existir.
    """
    session.add(
        Notification(
            user_id=user.id,
            titulo='Ative as suas Quotas',
            mensagem=(
                f'Olá {user.nome_completo}! Efetue o pagamento da primeira quota '
                f'para ativar os benefícios de militante.'
            ),
            categoria=RoleCategoriaNotificacao.QUOTA,
        )
    )
    user.notificado_quota_atraso_em = datetime.now(timezone.utc).date()


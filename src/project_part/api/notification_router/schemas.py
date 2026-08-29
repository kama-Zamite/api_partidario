from pydantic import BaseModel

class NotificationPreferencesUpdate(BaseModel):
    notificacoes_gerais: bool | None = None
    comunicados_oficiais: bool | None = None
    eventos_mobilizacoes: bool | None = None
    contribuicoes_quota: bool | None = None
    noticias_partido: bool | None = None

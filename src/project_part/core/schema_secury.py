from datetime import datetime, date 
from pydantic import BaseModel, ConfigDict
from uuid import UUID
from project_part.model.models import EstadoCivil
from typing import List, Optional

class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_url: str | None = None
    foi_militante: bool | None = False
    militante_numero: str | None = None

    partilha_dados: bool
    cookies_personalizacao: bool

    two_factor_enabled: bool

    notificacoes_gerais: bool
    comunicados_oficiais: bool
    eventos_mobilizacoes: bool
    contribuicoes_quota: bool
    noticias_partido: bool

    consentimento_lpd: bool | None = False
    concedido_em: datetime | None = None
    versao_politica_apd: str | None = None

    criado_em: datetime | None = None
    password_alterado_em: datetime | None = None
    atualizado_em: datetime | None = None
    deletado_em: datetime | None = None
    ultimo_login: datetime | None = None

    data_expiracao_quota: date | None = None
    notificado_quota_atraso_em: date | None = None

    estado_civil: EstadoCivil | None = None
    ativo: bool
    bloqueado_permanente: bool | None = False

